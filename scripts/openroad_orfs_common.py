#!/usr/bin/env python3
"""Common runner for OpenROAD-flow-scripts native stage workloads."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

DEFAULT_ORFS_REPO = "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git"
DEFAULT_ORFS_COMMIT = "8abc6a9035ca36490a1577867addca732a87cee8"
DEFAULT_WORK_DIR = Path("/tmp/cxl_openroad_orfs")
DEFAULT_DESIGN_CONFIG = Path("designs/nangate45/aes/config.mk")
DEFAULT_OPENROAD_RELATIVE = Path("tools/install/OpenROAD/bin/openroad")
DEFAULT_OPENSTA_RELATIVE = Path("tools/install/OpenROAD/bin/sta")
DEFAULT_YOSYS_RELATIVE = Path("tools/install/yosys/bin/yosys")


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
    peak_memory_mib: float | None
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
    parser.add_argument(
        "--openroad-exe",
        type=Path,
        default=None,
        help="Native OpenROAD executable. Defaults to OPENROAD_EXE, ORFS tools/install, or PATH.",
    )
    parser.add_argument(
        "--opensta-exe",
        type=Path,
        default=None,
        help="Native OpenSTA executable. Defaults to OPENSTA_EXE, ORFS tools/install, or PATH.",
    )
    parser.add_argument(
        "--yosys-exe",
        type=Path,
        default=None,
        help="Native Yosys executable. Defaults to YOSYS_EXE, ORFS tools/install, or PATH.",
    )

def build_native_make_command(
    orfs_path: Path,
    design_config: Path,
    target: str,
) -> list[str]:
    return [
        "make",
        "-C",
        str(Path(orfs_path) / "flow"),
        f"DESIGN_CONFIG={design_config}",
        target,
    ]


def build_native_tool_env(
    base_env: dict[str, str] | None = None,
    openroad_exe: Path | None = None,
    opensta_exe: Path | None = None,
    yosys_exe: Path | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    if openroad_exe is not None:
        env["OPENROAD_EXE"] = str(openroad_exe)
    if opensta_exe is not None:
        env["OPENSTA_EXE"] = str(opensta_exe)
    if yosys_exe is not None:
        env["YOSYS_EXE"] = str(yosys_exe)
    return env


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
        orfs_path = ensure_orfs_repo(
            work_dir=args.work_dir,
            repo_url=args.orfs_repo,
            commit=args.orfs_commit,
            runner=runner,
        )
        metrics["orfs"]["path"] = str(orfs_path)
        metrics["orfs_paths"] = orfs_output_paths(orfs_path, args.design_config)
        native_env = resolve_native_tool_env(orfs_path, args, os.environ)
        metrics["toolchain"] = native_toolchain_metrics(native_env)

        bootstrap_command = build_native_make_command(
            orfs_path=orfs_path,
            design_config=args.design_config,
            target=args.bootstrap_target,
        )
        timed_command = build_native_make_command(
            orfs_path=orfs_path,
            design_config=args.design_config,
            target=args.timed_target,
        )
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
                env=native_env,
                runner=runner,
            )
        timed_result = run_timed_command(
            command=timed_command,
            time_log=args.time_log,
            env=native_env,
            runner=runner,
        )
        exit_status = timed_result.exit_status
        metrics.update(
            {
                "wall_time_seconds": timed_result.wall_time_seconds,
                "peak_memory_mib": timed_result.peak_memory_mib,
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
        "execution": {
            "mode": "native",
        },
        "toolchain": native_toolchain_metrics(
            build_native_tool_env(
                base_env={},
                openroad_exe=args.openroad_exe,
                opensta_exe=args.opensta_exe,
                yosys_exe=args.yosys_exe,
            )
        ),
        "design_config": str(args.design_config),
        "bootstrap_stage": args.bootstrap_target,
        "timed_stage": args.timed_target,
        "full_command": None,
        "commands": {},
        "exit_status": None,
        "wall_time_seconds": None,
        "total_wall_time_seconds": None,
        "peak_memory_mib": None,
        "time_log_path": str(args.time_log),
        "orfs_paths": {},
        "time_metrics": {},
        "error": None,
    }


def resolve_native_tool_env(
    orfs_path: Path,
    args: argparse.Namespace,
    base_env: dict[str, str],
) -> dict[str, str]:
    env = build_native_tool_env(
        base_env=base_env,
        openroad_exe=args.openroad_exe,
        opensta_exe=args.opensta_exe,
        yosys_exe=args.yosys_exe,
    )
    fill_native_tool(env, "OPENROAD_EXE", Path(orfs_path) / DEFAULT_OPENROAD_RELATIVE, "openroad")
    fill_native_tool(env, "OPENSTA_EXE", Path(orfs_path) / DEFAULT_OPENSTA_RELATIVE, "sta")
    fill_native_tool(env, "YOSYS_EXE", Path(orfs_path) / DEFAULT_YOSYS_RELATIVE, "yosys")
    return env


def fill_native_tool(env: dict[str, str], env_var: str, orfs_default: Path, path_name: str) -> None:
    if env.get(env_var):
        return
    if orfs_default.exists():
        env[env_var] = str(orfs_default)
        return
    found = shutil.which(path_name, path=env.get("PATH"))
    if found:
        env[env_var] = found


def native_toolchain_metrics(env: dict[str, str]) -> dict[str, str | None]:
    return {
        "openroad_exe": env.get("OPENROAD_EXE"),
        "opensta_exe": env.get("OPENSTA_EXE"),
        "yosys_exe": env.get("YOSYS_EXE"),
    }


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


def run_logged_command(
    command: Sequence[str],
    log_path: Path,
    title: str,
    env: dict[str, str],
    runner: Any,
) -> None:
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
                env=env,
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
    time_log: Path,
    env: dict[str, str],
    runner: Any,
) -> TimedRunResult:
    time_log = Path(time_log)
    time_log.parent.mkdir(parents=True, exist_ok=True)
    timed_command = ["/usr/bin/time", "-v", *command]
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
                env=env,
            )
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"timed target failed to start: {exc}", command=timed_command) from exc

        exit_status = process.wait()

    wall_time = time.perf_counter() - start
    time_metrics = parse_time_v_log(time_log)
    return TimedRunResult(
        exit_status=int(exit_status),
        wall_time_seconds=wall_time,
        peak_memory_mib=time_metrics.get("maximum_resident_set_mib"),
        time_metrics=time_metrics,
    )


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


def main(argv: Sequence[str] | None, spec: WorkloadSpec) -> int:
    parser = argparse.ArgumentParser(
        description=f"Run OpenROAD ORFS {spec.workload_name} stage on the native host."
    )
    add_common_arguments(parser, spec)
    args = parser.parse_args(argv)
    return run_orfs_workload(args, spec)


if __name__ == "__main__":
    raise SystemExit(
        "openroad_orfs_common.py is a shared module; run run_openroad_orfs_place.py "
        "or run_openroad_orfs_route.py"
    )
