#!/usr/bin/env python3
"""Run OpenROAD ORFS AES placement as an independent workload entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from openroad_orfs_common import WorkloadSpec, add_common_arguments, run_orfs_workload

WORKLOAD_NAME = "placement"
SPEC = WorkloadSpec(
    workload_name=WORKLOAD_NAME,
    default_bootstrap_target="floorplan",
    default_timed_target="do-place",
    default_output=Path("logs/openroad_orfs_place_metrics.json"),
    default_time_log=Path("logs/openroad_orfs_place_time.log"),
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap ORFS AES through floorplan, then time do-place."
    )
    add_common_arguments(parser, SPEC)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return run_orfs_workload(parse_args(argv), SPEC)


if __name__ == "__main__":
    raise SystemExit(main())
