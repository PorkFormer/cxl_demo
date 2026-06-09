#!/usr/bin/env python3
"""Run OpenROAD ORFS AES routing as an independent workload entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from openroad_orfs_common import WorkloadSpec, add_common_arguments, run_orfs_workload

WORKLOAD_NAME = "routing"
SPEC = WorkloadSpec(
    workload_name=WORKLOAD_NAME,
    default_bootstrap_target="cts",
    default_timed_target="do-route",
    default_output=Path("logs/openroad_orfs_route_metrics.json"),
    default_time_log=Path("logs/openroad_orfs_route_time.log"),
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap ORFS AES through CTS, then time do-route."
    )
    add_common_arguments(parser, SPEC)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return run_orfs_workload(parse_args(argv), SPEC)


if __name__ == "__main__":
    raise SystemExit(main())
