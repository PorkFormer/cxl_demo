#!/usr/bin/env python3
"""Pick a short, real POT3D workload for CXL/L3 replacement experiments."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MIB = 1024 * 1024
DEFAULT_L3_MIB = 48.0
DEFAULT_MAX_RUNTIME_SECONDS = 180.0
MIN_ITERATIONS_FOR_LOCALITY = 1000
CXL_PRESSURE_L3_MULTIPLE = 10.0


@dataclass(frozen=True)
class GridDimensions:
    nr: int
    nt: int
    np: int

    @property
    def total_points(self) -> int:
        return self.nr * self.nt * self.np

    @property
    def interior_points(self) -> int:
        return max(self.nr - 2, 0) * max(self.nt - 2, 0) * max(self.np - 2, 0)


@dataclass(frozen=True)
class WorkloadVerdict:
    name: str
    test_name: str
    dimensions: GridDimensions
    runtime_seconds: float
    iterations: int
    estimated_hot_set_mib_per_rank: float
    l3_mib: float
    passes: bool
    score: float
    reason: str
    rerun_command: str


def parse_pot3d_dat(text: str) -> GridDimensions:
    values = {}
    for key in ("nr", "nt", "np"):
        match = re.search(rf"^\s*{key}\s*=\s*(\d+)\b", text, flags=re.MULTILINE)
        if not match:
            raise ValueError(f"missing {key}= in pot3d.dat")
        values[key] = int(match.group(1))
    return GridDimensions(nr=values["nr"], nt=values["nt"], np=values["np"])


def parse_testsuite_runtime(text: str, test_name: str) -> float:
    pattern = rf"^{re.escape(test_name)}\s+PASS\s+([0-9]+(?:\.[0-9]+)?)\b"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"missing PASS runtime for {test_name}")
    return float(match.group(1))


def parse_solver_iterations(text: str) -> int:
    matches = re.findall(r"Number of iterations\s*=\s*(\d+)", text)
    if not matches:
        raise ValueError("missing solver iteration count")
    return int(matches[-1])


def estimate_pcg_hot_set_mib(dimensions: GridDimensions) -> float:
    n = dimensions.interior_points
    total = dimensions.total_points

    matrix_coefficients = n * 7 * 8
    jacobi_preconditioner = n * 4
    cg_vectors = n * 4 * 8
    unpacked_stencil_field = total * 8
    seam_and_boundary_slack = total * 2

    return (
        matrix_coefficients
        + jacobi_preconditioner
        + cg_vectors
        + unpacked_stencil_field
        + seam_and_boundary_slack
    ) / MIB


def _candidate_test_names() -> tuple[str, ...]:
    return (
        "potential_field_source_surface",
        "potential_field_current_sheet",
        "open_field",
    )


def evaluate_default_candidates(
    root: Path, max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS
) -> list[WorkloadVerdict]:
    root = Path(root)
    testsuite_log = (root / "logs" / "pot3d_testsuite.log").read_text()
    verdicts = []

    for test_name in _candidate_test_names():
        input_dir = root / "src" / "POT3D" / "testsuite" / test_name / "input"
        reference_dir = root / "src" / "POT3D" / "testsuite" / test_name / "reference"
        dimensions = parse_pot3d_dat((input_dir / "pot3d.dat").read_text())
        runtime_seconds = parse_testsuite_runtime(testsuite_log, test_name)
        iterations = parse_solver_iterations((reference_dir / "pot3d.log").read_text())
        hot_set_mib = estimate_pcg_hot_set_mib(dimensions)
        fits_runtime = runtime_seconds <= max_runtime_seconds
        stresses_l3 = hot_set_mib >= DEFAULT_L3_MIB * CXL_PRESSURE_L3_MULTIPLE
        repeats_enough = iterations >= MIN_ITERATIONS_FOR_LOCALITY
        passes = fits_runtime and stresses_l3 and repeats_enough
        score = _score_candidate(runtime_seconds, hot_set_mib, iterations, max_runtime_seconds)
        reason = _reason(fits_runtime, stresses_l3, repeats_enough)
        verdicts.append(
            WorkloadVerdict(
                name=f"POT3D {test_name}",
                test_name=test_name,
                dimensions=dimensions,
                runtime_seconds=runtime_seconds,
                iterations=iterations,
                estimated_hot_set_mib_per_rank=hot_set_mib,
                l3_mib=DEFAULT_L3_MIB,
                passes=passes,
                score=score,
                reason=reason,
                rerun_command=(
                    "cd src/POT3D/testsuite && "
                    f"./run_test_suite.sh -np=4 -test={test_name}"
                ),
            )
        )

    return verdicts


def pick_recommendation(verdicts: Iterable[WorkloadVerdict]) -> WorkloadVerdict:
    passed = [item for item in verdicts if item.passes]
    if not passed:
        raise ValueError("no candidate satisfies the workload constraints")
    return sorted(passed, key=lambda item: item.score, reverse=True)[0]


def render_report(
    verdicts: Iterable[WorkloadVerdict],
    max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS,
) -> str:
    verdicts = list(verdicts)
    recommendation = pick_recommendation(verdicts)
    lines = [
        f"Recommended: {recommendation.name}",
        "Verdict: PASS",
        "",
        "Why this workload fits:",
        "- Real workload: POT3D is a production HPC potential-field solver, not a DB/vector synthetic.",
        "- Temporal locality: PCG repeatedly touches the same stencil coefficients and CG vectors.",
        f"- Runtime: {recommendation.runtime_seconds:.3f}s <= {max_runtime_seconds:.0f}s.",
        (
            "- L3 pressure: estimated hot iterative set "
            f"{recommendation.estimated_hot_set_mib_per_rank:.1f} MiB/rank "
            f">= {CXL_PRESSURE_L3_MULTIPLE:.0f}x {recommendation.l3_mib:.0f} MiB L3."
        ),
        f"- Reuse window: {recommendation.iterations} solver iterations.",
        "",
        "Excluded workload classes: Redis, YCSB, Milvus, Qdrant, GloVe, DLRM.",
        "",
        "Candidates:",
    ]
    for item in sorted(verdicts, key=lambda verdict: verdict.score, reverse=True):
        status = "PASS" if item.passes else "SKIP"
        lines.append(
            f"- {status} {item.name}: runtime={item.runtime_seconds:.3f}s, "
            f"hot_set={item.estimated_hot_set_mib_per_rank:.1f} MiB/rank, "
            f"iterations={item.iterations}, reason={item.reason}"
        )
    lines.extend(
        [
            "",
            "Rerun command:",
            recommendation.rerun_command,
        ]
    )
    return "\n".join(lines)


def _score_candidate(
    runtime_seconds: float,
    hot_set_mib: float,
    iterations: int,
    max_runtime_seconds: float,
) -> float:
    runtime_score = max(0.0, 1.0 - runtime_seconds / max_runtime_seconds)
    l3_pressure_score = min(hot_set_mib / DEFAULT_L3_MIB, 4.0) / 4.0
    locality_score = min(iterations / 4000.0, 1.0)
    return runtime_score + l3_pressure_score + locality_score


def _reason(fits_runtime: bool, stresses_l3: bool, repeats_enough: bool) -> str:
    missing = []
    if not fits_runtime:
        missing.append("too long")
    if not stresses_l3:
        missing.append(f"hot set < {CXL_PRESSURE_L3_MULTIPLE:.0f}x L3")
    if not repeats_enough:
        missing.append("too few solver iterations")
    return "meets constraints" if not missing else ", ".join(missing)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find a short real POT3D workload with clear temporal locality."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root; default is inferred from this script location",
    )
    parser.add_argument(
        "--max-runtime",
        type=float,
        default=DEFAULT_MAX_RUNTIME_SECONDS,
        help="maximum acceptable recorded runtime in seconds",
    )
    args = parser.parse_args()

    verdicts = evaluate_default_candidates(args.root, args.max_runtime)
    print(render_report(verdicts, args.max_runtime))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
