#!/usr/bin/env python3
"""Run both Spark MLlib RDD linear-model workloads on HIGGS."""

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
    LibSvmSubset,
    build_metrics,
    higgs_csv_row_to_libsvm,
    load_reusable_subset,
    peak_rss_mib,
    positive_float,
    positive_int,
    prepare_libsvm_subset,
    run_spark_training as _run_spark_training,
    run_workload,
    sha256_file,
    spark_process_root,
    subset_paths,
    version_info,
    write_metrics,
)

DEFAULT_OUTPUT = Path("logs/spark_mllib_higgs_demo_metrics.json")
APP_NAME = "SparkMllibHiggsCachedRddDemo"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train Spark MLlib RDD SVM and logistic regression on HIGGS."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="HIGGS.csv.gz path")
    parser.add_argument("--rows", type=positive_int, default=2_000_000)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--master", default="local[16]")
    parser.add_argument("--partitions", type=positive_int, default=64)
    parser.add_argument("--storage-level", default="MEMORY_ONLY")
    parser.add_argument("--svm-iterations", type=positive_int, default=30)
    parser.add_argument("--logreg-iterations", type=positive_int, default=30)
    parser.add_argument("--test-fraction", type=positive_float, default=0.2)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def run_spark_training(args: argparse.Namespace, subset: LibSvmSubset) -> dict[str, object]:
    return _run_spark_training(
        args,
        subset,
        algorithms=[
            AlgorithmSpec("linear_svm", "SGD", args.svm_iterations),
            AlgorithmSpec("logistic_regression", "LBFGS", args.logreg_iterations),
        ],
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metrics = run_workload(
        args,
        algorithms=[
            AlgorithmSpec("linear_svm", "SGD", args.svm_iterations),
            AlgorithmSpec("logistic_regression", "LBFGS", args.logreg_iterations),
        ],
        feature_count=DEFAULT_FEATURE_COUNT,
    )
    write_metrics(args.output, metrics)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
