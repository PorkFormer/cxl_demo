#!/usr/bin/env python3
"""Run the Spark MLlib RDD Linear SVM workload on HIGGS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from spark_mllib_higgs_common import (
    DEFAULT_DATA,
    DEFAULT_FEATURE_COUNT,
    DEFAULT_WORK_DIR,
    AlgorithmSpec,
    positive_float,
    positive_int,
    run_workload,
    write_metrics,
)

ALGORITHM_NAME = "linear_svm"
DEFAULT_OUTPUT = Path("logs/spark_mllib_higgs_svm_metrics.json")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train only Spark MLlib RDD Linear SVM on HIGGS."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="HIGGS.csv.gz path")
    parser.add_argument("--rows", type=positive_int, default=2_000_000)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--master", default="local[16]")
    parser.add_argument("--partitions", type=positive_int, default=64)
    parser.add_argument("--storage-level", default="MEMORY_ONLY")
    parser.add_argument("--iterations", type=positive_int, default=30)
    parser.add_argument("--test-fraction", type=positive_float, default=0.2)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metrics = run_workload(
        args,
        algorithms=[AlgorithmSpec(ALGORITHM_NAME, "SGD", args.iterations)],
        feature_count=DEFAULT_FEATURE_COUNT,
    )
    write_metrics(args.output, metrics)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
