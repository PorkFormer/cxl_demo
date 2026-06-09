#!/usr/bin/env python3
"""Common runner for OpenROAD-flow-scripts Docker stage workloads."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

MIB = 1024 * 1024
DEFAULT_ORFS_REPO = "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git"
DEFAULT_ORFS_COMMIT = "8abc6a9035ca36490a1577867addca732a87cee8"
DEFAULT_DOCKER_IMAGE = "openroad/orfs"
DEFAULT_WORK_DIR = Path("/tmp/cxl_openroad_orfs")
DEFAULT_DOCKER_MEMORY = "64g"
DEFAULT_DESIGN_CONFIG = Path("designs/nangate45/aes/config.mk")
CONTAINER_ORFS_PATH = "/work/OpenROAD-flow-scripts"
IMAGE_OPENROAD_EXE = "/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad"
IMAGE_OPENSTA_EXE = "/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta"
IMAGE_YOSYS_EXE = "/usr/local/bin/yosys"


@dataclass(frozen=True)
class WorkloadSpec:
    workload_name: str
    default_bootstrap_target: str
    default_timed_target: str
    default_output: Path
    default_time_log: Path


@dataclass(frozen=True)
class TimedRunResult:
    exit_status: int
    wall_time_seconds: float
    docker_stats_samples: list[dict[str, Any]]
    container_peak_memory_mib: float | None
    time_metrics: dict[str, Any]


class CommandError(RuntimeError):
    def __init__(
        self,
        message: str,
        returncode: int | None = None,
        command: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.command = list(command) if command is not None else None


class SubprocessRunner:
    def run(self, command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.run(list(command), **kwargs)

    def popen(self, command: Sequence[str], **kwargs: Any) -> subprocess.Popen[str]:
        return subprocess.Popen(list(command), **kwargs)


def add_common_arguments(parser: argparse.ArgumentParser, spec: WorkloadSpec) -> None:
    parser.add_argument("--orfs-repo", default=DEFAULT_ORFS_REPO)
    parser.add_argument("--orfs-commit", default=DEFAULT_ORFS_COMMIT)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--docker-image", default=DEFAULT_DOCKER_IMAGE)
    parser.add_argument("--docker-memory", default=DEFAULT_DOCKER_MEMORY)
    parser.add_argument("--docker-mode", choices=("auto", "direct", "sg"), default="auto")
    parser.add_argument("--stats-interval", type=positive_float, default=1.0)
    parser.add_argument("--design-config", type=Path, default=DEFAULT_DESIGN_CONFIG)
    parser.add_argument("--bootstrap-target", default=spec.default_bootstrap_target)
    parser.add_argument("--timed-target", default=spec.default_timed_target)
    parser.add_argument("--output", type=Path, default=spec.default_output)
    parser.add_argument("--time-log", type=Path, default=spec.default_time_log)
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Run only the timed target; useful when the bootstrap stage already exists.",
    )


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_memory_mib(text: str) -> float:
    """Parse Docker memory strings such as '123MiB / 64GiB' into MiB."""
    first_value = text.split("/", 1)[0].strip().replace(",", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)", first_value)
    if not match:
        raise ValueError(f"cannot parse memory value {text!r}")

    value = float(match.group(1))
    unit = match.group(2)
    factors = {
        "B": 1 / MIB,
        "KiB": 1 / 1024,
        "MiB": 1.0,
        "GiB": 1024.0,
        "TiB": 1024.0 * 1024.0,
        "KB": 1000 / MIB,
        "MB": 1000 * 1000 / MIB,
        "GB": 1000 * 1000 * 1000 / MIB,
        "TB": 1000 * 1000 * 1000 * 1000 / MIB,
    }
    if unit not in factors:
        raise ValueError(f"unsupported memory unit {unit!r} in {text!r}")
    return value * factors[unit]


def build_docker_make_command(
    orfs_path: Path,
    image: str,
    memory: str,
    container_name: str,
    design_config: Path,
    target: str,
) -> list[str]:
    mount = f"{Path(orfs_path)}:{CONTAINER_ORFS_PATH}"
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--memory",
        memory,
        "-e",
        f"OPENROAD_EXE={IMAGE_OPENROAD_EXE}",
        "-e",
        f"OPENSTA_EXE={IMAGE_OPENSTA_EXE}",
        "-e",
        f"YOSYS_EXE={IMAGE_YOSYS_EXE}",
        "-v",
        mount,
        "-w",
        CONTAINER_ORFS_PATH,
        image,
        "make",
        "-C",
        "flow",
        f"DESIGN_CONFIG={design_config}",
        target,
    ]


def wrap_docker_command(command: Sequence[str], docker_mode: str) -> list[str]:
    if docker_mode == "direct":
        return list(command)
    if docker_mode == "sg":
        return ["sg", "docker", "-c", shlex.join(command)]
    raise ValueError(f"unknown docker mode {docker_mode!r}")


def write_metrics(path: Path, metrics: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")


def run_orfs_workload(
    args: argparse.Namespace,
    spec: WorkloadSpec,
    runner: Any | None = None,
) -> int:
    runner = runner or SubprocessRunner()
    start = time.perf_counter()
    exit_status: int | None = None
    metrics = initial_metrics(args, spec)

    try:
        docker_mode = resolve_docker_mode(args.docker_mode, runner)
        metrics["docker"]["mode"] = docker_mode

        orfs_path = ensure_orfs_repo(
            work_dir=args.work_dir,
            repo_url=args.orfs_repo,
            commit=args.orfs_commit,
            runner=runner,
        )
        metrics["orfs"]["path"] = str(orfs_path)
        metrics["orfs_paths"] = orfs_output_paths(orfs_path, args.design_config)
        metrics["docker"]["image_digest"] = docker_image_digest(
            args.docker_image,
            docker_mode=docker_mode,
            runner=runner,
        )

        bootstrap_container = container_name(spec.workload_name, args.bootstrap_target)
        timed_container = container_name(spec.workload_name, args.timed_target)
        bootstrap_docker_command = build_docker_make_command(
            orfs_path=orfs_path,
            image=args.docker_image,
            memory=args.docker_memory,
            container_name=bootstrap_container,
            design_config=args.design_config,
            target=args.bootstrap_target,
        )
        timed_docker_command = build_docker_make_command(
            orfs_path=orfs_path,
            image=args.docker_image,
            memory=args.docker_memory,
            container_name=timed_container,
            design_config=args.design_config,
            target=args.timed_target,
        )
        bootstrap_command = wrap_docker_command(bootstrap_docker_command, docker_mode)
        timed_command = wrap_docker_command(timed_docker_command, docker_mode)
        metrics["full_command"] = shlex.join(["/usr/bin/time", "-v", *timed_command])
        metrics["commands"] = {
            "bootstrap": shlex.join(bootstrap_command),
            "timed": metrics["full_command"],
        }

        if not args.skip_bootstrap:
            run_logged_command(
                command=bootstrap_command,
                log_path=args.time_log,
                title=f"bootstrap {args.bootstrap_target}",
                runner=runner,
            )
        timed_result = run_timed_command(
            command=timed_command,
            docker_mode=docker_mode,
            container_name=timed_container,
            time_log=args.time_log,
            stats_interval_seconds=args.stats_interval,
            runner=runner,
        )
        exit_status = timed_result.exit_status
        metrics.update(
            {
                "wall_time_seconds": timed_result.wall_time_seconds,
                "docker_stats_samples": timed_result.docker_stats_samples,
                "container_peak_memory_mib": timed_result.container_peak_memory_mib,
                "time_metrics": timed_result.time_metrics,
            }
        )
        if exit_status != 0:
            metrics["error"] = f"timed target exited with status {exit_status}"
    except Exception as exc:
        exit_status = getattr(exc, "returncode", None) or 1
        metrics["error"] = str(exc)
    finally:
        metrics["exit_status"] = int(exit_status if exit_status is not None else 1)
        metrics["total_wall_time_seconds"] = time.perf_counter() - start
        write_metrics(args.output, metrics)

    print(json.dumps(metrics, indent=2, sort_keys=True))
    return int(metrics["exit_status"])


def initial_metrics(args: argparse.Namespace, spec: WorkloadSpec) -> dict[str, Any]:
    return {
        "workload_family": "openroad-orfs",
        "workload_name": spec.workload_name,
        "orfs": {
            "repo": args.orfs_repo,
            "commit": args.orfs_commit,
            "path": str(Path(args.work_dir) / "OpenROAD-flow-scripts"),
        },
        "docker": {
            "mode": args.docker_mode,
            "image": args.docker_image,
            "image_digest": None,
            "memory": args.docker_memory,
        },
        "design_config": str(args.design_config),
        "bootstrap_stage": args.bootstrap_target,
        "timed_stage": args.timed_target,
        "full_command": None,
        "commands": {},
        "exit_status": None,
        "wall_time_seconds": None,
        "total_wall_time_seconds": None,
        "container_peak_memory_mib": None,
        "docker_stats_samples": [],
        "time_log_path": str(args.time_log),
        "orfs_paths": {},
        "time_metrics": {},
        "error": None,
    }


def resolve_docker_mode(requested: str, runner: Any) -> str:
    if requested == "direct":
        require_command_success(["docker", "--version"], "direct docker unavailable", runner)
        return "direct"
    if requested == "sg":
        require_command_success(
            wrap_docker_command(["docker", "--version"], "sg"),
            "sg docker unavailable",
            runner,
        )
        return "sg"
    if requested != "auto":
        raise ValueError(f"unknown docker mode {requested!r}")

    if command_succeeds(["docker", "--version"], runner):
        return "direct"
    if command_succeeds(wrap_docker_command(["docker", "--version"], "sg"), runner):
        return "sg"
    raise CommandError("docker unavailable: direct docker and sg docker both failed")


def command_succeeds(command: Sequence[str], runner: Any) -> bool:
    try:
        result = runner.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return False
    return result.returncode == 0


def require_command_success(command: Sequence[str], message: str, runner: Any) -> None:
    try:
        result = runner.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as exc:
        raise CommandError(f"{message}: {exc}", command=command) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CommandError(
            f"{message}: {detail}",
            returncode=result.returncode,
            command=command,
        )


def ensure_orfs_repo(work_dir: Path, repo_url: str, commit: str, runner: Any) -> Path:
    work_dir = Path(work_dir)
    repo_path = work_dir / "OpenROAD-flow-scripts"
    work_dir.mkdir(parents=True, exist_ok=True)
    if not repo_path.exists():
        run_checked(["git", "clone", repo_url, str(repo_path)], runner)
    elif not (repo_path / ".git").exists():
        raise CommandError(f"ORFS path exists but is not a git repo: {repo_path}")

    run_checked(["git", "-C", str(repo_path), "fetch", "--depth", "1", "origin", commit], runner)
    run_checked(["git", "-C", str(repo_path), "checkout", "--detach", commit], runner)
    return repo_path


def run_checked(command: Sequence[str], runner: Any) -> subprocess.CompletedProcess[str]:
    try:
        result = runner.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except CommandError:
        raise
    except Exception as exc:
        raise CommandError(f"command failed: {shlex.join(command)}: {exc}", command=command) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CommandError(
            f"command failed ({result.returncode}): {shlex.join(command)}: {detail}",
            returncode=result.returncode,
            command=command,
        )
    return result


def docker_image_digest(image: str, docker_mode: str, runner: Any) -> str | None:
    command = wrap_docker_command(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
        docker_mode,
    )
    try:
        result = runner.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        digests = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return None
    if isinstance(digests, list) and digests:
        return str(digests[0])
    return None


def run_logged_command(command: Sequence[str], log_path: Path, title: str, runner: Any) -> None:
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as log:
        log.write(f"\n## {title}\n")
        log.write(f"$ {shlex.join(command)}\n")
        log.flush()
        try:
            result = runner.run(
                list(command),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"{title} failed: {exc}", command=command) from exc
        if result.returncode != 0:
            raise CommandError(
                f"{title} failed with status {result.returncode}",
                returncode=result.returncode,
                command=command,
            )


def run_timed_command(
    command: Sequence[str],
    docker_mode: str,
    container_name: str,
    time_log: Path,
    stats_interval_seconds: float,
    runner: Any,
) -> TimedRunResult:
    time_log = Path(time_log)
    time_log.parent.mkdir(parents=True, exist_ok=True)
    timed_command = ["/usr/bin/time", "-v", *command]
    samples: list[dict[str, Any]] = []
    start = time.perf_counter()

    with time_log.open("a") as log:
        log.write(f"\n## timed target\n")
        log.write(f"$ {shlex.join(timed_command)}\n")
        log.flush()
        try:
            process = runner.popen(
                timed_command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"timed target failed to start: {exc}", command=timed_command) from exc

        while True:
            exit_status = process.poll()
            sample = docker_stats_sample(container_name, docker_mode, runner)
            if sample is not None:
                samples.append(sample)
            if exit_status is not None:
                break
            time.sleep(stats_interval_seconds)

    wall_time = time.perf_counter() - start
    peak_memory = None
    if samples:
        peak_memory = max(sample["memory_mib"] for sample in samples)
    return TimedRunResult(
        exit_status=int(exit_status),
        wall_time_seconds=wall_time,
        docker_stats_samples=samples,
        container_peak_memory_mib=peak_memory,
        time_metrics=parse_time_v_log(time_log),
    )


def docker_stats_sample(container_name: str, docker_mode: str, runner: Any) -> dict[str, Any] | None:
    command = wrap_docker_command(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container_name],
        docker_mode,
    )
    try:
        result = runner.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip().splitlines()
    if not raw:
        return None
    try:
        memory_mib = parse_memory_mib(raw[0])
    except ValueError:
        return None
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "memory_mib": memory_mib,
        "raw": raw[0],
    }


def parse_time_v_log(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    text = path.read_text(errors="replace")
    metrics: dict[str, Any] = {}
    elapsed_matches = re.findall(
        r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*(\S+)",
        text,
    )
    rss_matches = re.findall(r"Maximum resident set size \(kbytes\):\s*(\d+)", text)
    exit_matches = re.findall(r"Exit status:\s*(\d+)", text)
    if elapsed_matches:
        metrics["elapsed_seconds"] = parse_elapsed_seconds(elapsed_matches[-1])
    if rss_matches:
        metrics["maximum_resident_set_mib"] = int(rss_matches[-1]) / 1024.0
    if exit_matches:
        metrics["exit_status"] = int(exit_matches[-1])
    return metrics


def parse_elapsed_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return float(value)


def orfs_output_paths(orfs_path: Path, design_config: Path) -> dict[str, str]:
    parts = Path(design_config).parts
    if len(parts) >= 3 and parts[0] == "designs":
        platform = parts[1]
        design = parts[2]
        return {
            "logs": str(Path(orfs_path) / "flow" / "logs" / platform / design),
            "results": str(Path(orfs_path) / "flow" / "results" / platform / design),
            "reports": str(Path(orfs_path) / "flow" / "reports" / platform / design),
        }
    return {
        "logs": str(Path(orfs_path) / "flow" / "logs"),
        "results": str(Path(orfs_path) / "flow" / "results"),
        "reports": str(Path(orfs_path) / "flow" / "reports"),
    }


def container_name(workload_name: str, target: str) -> str:
    raw = f"cxl-openroad-orfs-{workload_name}-{target}-{os.getpid()}-{int(time.time())}"
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", raw)[:120]


def main(argv: Sequence[str] | None, spec: WorkloadSpec) -> int:
    parser = argparse.ArgumentParser(
        description=f"Run OpenROAD ORFS {spec.workload_name} stage in Docker."
    )
    add_common_arguments(parser, spec)
    args = parser.parse_args(argv)
    return run_orfs_workload(args, spec)


if __name__ == "__main__":
    raise SystemExit(
        "openroad_orfs_common.py is a shared module; run run_openroad_orfs_place.py "
        "or run_openroad_orfs_route.py"
    )
