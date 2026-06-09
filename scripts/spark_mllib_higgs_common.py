#!/usr/bin/env python3
"""Run Spark MLlib RDD-based linear models on a cached HIGGS subset."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import platform
import resource
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

MIB = 1024 * 1024
DEFAULT_DATA = Path("/tmp/cxl_xgboost_higgs/HIGGS.csv.gz")
DEFAULT_WORK_DIR = Path("/tmp/cxl_spark_mllib_higgs")
DEFAULT_OUTPUT = Path("logs/spark_mllib_higgs_demo_metrics.json")
DEFAULT_FEATURE_COUNT = 28
APP_NAME = "SparkMllibHiggsCachedRddDemo"


@dataclass(frozen=True)
class LibSvmSubset:
    path: Path
    metadata_path: Path
    row_count: int
    feature_count: int
    source_sha256: str
    libsvm_sha256: str
    reused: bool


@dataclass(frozen=True)
class AlgorithmSpec:
    name: str
    optimizer: str
    iterations: int


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


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def sha256_file(path: Path, chunk_size: int = 8 * MIB) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def higgs_csv_row_to_libsvm(line: str, feature_count: int = DEFAULT_FEATURE_COUNT) -> str:
    try:
        row = next(csv.reader([line.strip()]))
    except csv.Error as exc:
        raise ValueError(f"invalid CSV row: {exc}") from exc

    expected_columns = feature_count + 1
    if len(row) != expected_columns:
        raise ValueError(f"expected {expected_columns} columns, got {len(row)}")

    label_value = float(row[0])
    if label_value not in (0.0, 1.0):
        raise ValueError(f"expected binary label 0/1, got {row[0]!r}")

    label = str(int(label_value))
    features: list[str] = []
    for index, value in enumerate(row[1:], start=1):
        value = value.strip()
        if not value:
            raise ValueError(f"empty feature value at index {index}")
        float(value)
        features.append(f"{index}:{value}")
    return f"{label} {' '.join(features)}"


def prepare_libsvm_subset(
    data_path: Path,
    row_count: int,
    work_dir: Path,
    feature_count: int = DEFAULT_FEATURE_COUNT,
) -> LibSvmSubset:
    data_path = Path(data_path)
    work_dir = Path(work_dir)
    if not data_path.exists():
        raise FileNotFoundError(f"HIGGS data file not found: {data_path}")

    source_sha256 = sha256_file(data_path)
    libsvm_path, metadata_path = subset_paths(work_dir, row_count, feature_count)
    reusable = load_reusable_subset(
        libsvm_path=libsvm_path,
        metadata_path=metadata_path,
        row_count=row_count,
        feature_count=feature_count,
        source_sha256=source_sha256,
    )
    if reusable is not None:
        return reusable

    work_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = libsvm_path.with_suffix(libsvm_path.suffix + ".tmp")
    written = 0
    try:
        opener = gzip.open if data_path.suffix == ".gz" else open
        with opener(data_path, "rt", newline="") as source, tmp_path.open("w") as target:
            for line in source:
                if written >= row_count:
                    break
                target.write(higgs_csv_row_to_libsvm(line, feature_count=feature_count))
                target.write("\n")
                written += 1
        if written != row_count:
            raise ValueError(f"requested {row_count} rows from {data_path}, got {written}")
        tmp_path.replace(libsvm_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    libsvm_sha256 = sha256_file(libsvm_path)
    metadata = {
        "format": "libsvm",
        "source_path": str(data_path),
        "source_sha256": source_sha256,
        "libsvm_path": str(libsvm_path),
        "libsvm_sha256": libsvm_sha256,
        "row_count": row_count,
        "feature_count": feature_count,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(metadata_path, metadata)
    return LibSvmSubset(
        path=libsvm_path,
        metadata_path=metadata_path,
        row_count=row_count,
        feature_count=feature_count,
        source_sha256=source_sha256,
        libsvm_sha256=libsvm_sha256,
        reused=False,
    )


def subset_paths(work_dir: Path, row_count: int, feature_count: int) -> tuple[Path, Path]:
    stem = f"higgs_{row_count}_rows_{feature_count}_features"
    return Path(work_dir) / f"{stem}.libsvm", Path(work_dir) / f"{stem}.metadata.json"


def load_reusable_subset(
    libsvm_path: Path,
    metadata_path: Path,
    row_count: int,
    feature_count: int,
    source_sha256: str,
) -> LibSvmSubset | None:
    libsvm_path = Path(libsvm_path)
    metadata_path = Path(metadata_path)
    if not libsvm_path.exists() or not metadata_path.exists():
        return None

    try:
        metadata = json.loads(metadata_path.read_text())
    except json.JSONDecodeError:
        return None

    if metadata.get("row_count") != row_count:
        return None
    if metadata.get("feature_count") != feature_count:
        return None
    if metadata.get("source_sha256") != source_sha256:
        return None
    libsvm_sha256 = metadata.get("libsvm_sha256")
    if not isinstance(libsvm_sha256, str) or not libsvm_sha256:
        return None

    return LibSvmSubset(
        path=libsvm_path,
        metadata_path=metadata_path,
        row_count=row_count,
        feature_count=feature_count,
        source_sha256=source_sha256,
        libsvm_sha256=libsvm_sha256,
        reused=True,
    )


def run_spark_training(
    args: argparse.Namespace,
    subset: LibSvmSubset,
    algorithms: Sequence[AlgorithmSpec],
) -> dict[str, Any]:
    if args.test_fraction >= 1.0:
        raise ValueError("--test-fraction must be less than 1.0")
    if not algorithms:
        raise ValueError("at least one algorithm is required")

    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")

    from pyspark import SparkConf, SparkContext
    from pyspark.mllib.classification import LogisticRegressionWithLBFGS, SVMWithSGD
    from pyspark.mllib.util import MLUtils

    conf = SparkConf().setAppName(APP_NAME).setMaster(args.master)
    sc = SparkContext(conf=conf)
    try:
        sc.setLogLevel("WARN")
        storage_level = resolve_storage_level(args.storage_level)
        data = MLUtils.loadLibSVMFile(
            sc,
            str(subset.path),
            numFeatures=subset.feature_count,
            minPartitions=args.partitions,
        )
        if data.getNumPartitions() != args.partitions:
            data = data.repartition(args.partitions)

        train, test = data.randomSplit(
            [1.0 - args.test_fraction, args.test_fraction],
            seed=args.seed,
        )
        train = train.persist(storage_level)
        test = test.persist(storage_level)

        materialize_start = time.perf_counter()
        train_count = train.count()
        test_count = test.count()
        materialize_seconds = time.perf_counter() - materialize_start
        if train_count == 0 or test_count == 0:
            raise ValueError(f"empty train/test split: train={train_count}, test={test_count}")

        algorithm_metrics = {}
        for algorithm in algorithms:
            if algorithm.name == "linear_svm":
                train_fn = lambda rdd, iterations=algorithm.iterations: SVMWithSGD.train(
                    rdd,
                    iterations=iterations,
                )
            elif algorithm.name == "logistic_regression":
                train_fn = (
                    lambda rdd, iterations=algorithm.iterations: LogisticRegressionWithLBFGS.train(
                        rdd,
                        iterations=iterations,
                    )
                )
            else:
                raise ValueError(f"unknown algorithm {algorithm.name!r}")

            algorithm_metrics[algorithm.name] = train_and_evaluate_classifier(
                name=algorithm.name,
                train_rdd=train,
                test_rdd=test,
                test_count=test_count,
                train_fn=train_fn,
                params={"iterations": algorithm.iterations, "optimizer": algorithm.optimizer},
            )

        return {
            "spark": spark_version_info(sc),
            "partition_count": data.getNumPartitions(),
            "train_partitions": train.getNumPartitions(),
            "test_partitions": test.getNumPartitions(),
            "train_count": train_count,
            "test_count": test_count,
            "materialize_seconds": materialize_seconds,
            "peak_rss_mib": peak_rss_mib(),
            "algorithms": algorithm_metrics,
        }
    finally:
        sc.stop()


def resolve_storage_level(name: str) -> Any:
    from pyspark import StorageLevel

    normalized = name.upper()
    try:
        return getattr(StorageLevel, normalized)
    except AttributeError as exc:
        available = sorted(value for value in dir(StorageLevel) if value.isupper())
        raise ValueError(f"unknown Spark storage level {name!r}; choose one of {available}") from exc


def train_and_evaluate_classifier(
    name: str,
    train_rdd: Any,
    test_rdd: Any,
    test_count: int,
    train_fn: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    train_start = time.perf_counter()
    model = train_fn(train_rdd)
    training_seconds = time.perf_counter() - train_start

    eval_start = time.perf_counter()
    errors = (
        test_rdd.map(lambda point: (float(model.predict(point.features)), float(point.label)))
        .filter(lambda prediction_label: prediction_label[0] != prediction_label[1])
        .count()
    )
    evaluation_seconds = time.perf_counter() - eval_start

    return {
        "name": name,
        "params": params,
        "training_seconds": training_seconds,
        "evaluation_seconds": evaluation_seconds,
        "error_count": int(errors),
        "error_rate": float(errors) / float(test_count),
        "model_weight_length": int(len(model.weights)),
        "intercept": float(getattr(model, "intercept", 0.0)),
    }


def build_metrics(
    args: argparse.Namespace,
    subset: LibSvmSubset,
    preprocess_seconds: float,
    spark_metrics: dict[str, Any],
    total_seconds: float,
) -> dict[str, Any]:
    return {
        "data_path": str(args.data),
        "work_dir": str(args.work_dir),
        "libsvm_path": str(subset.path),
        "metadata_path": str(subset.metadata_path),
        "source_sha256": subset.source_sha256,
        "libsvm_sha256": subset.libsvm_sha256,
        "libsvm_reused": subset.reused,
        "row_count": subset.row_count,
        "feature_count": subset.feature_count,
        "master": args.master,
        "requested_partitions": args.partitions,
        "storage_level": args.storage_level,
        "test_fraction": args.test_fraction,
        "seed": args.seed,
        "preprocess_seconds": preprocess_seconds,
        "total_seconds": total_seconds,
        "peak_rss_mib": peak_rss_mib(),
        "versions": version_info(),
        **spark_metrics,
    }


def spark_version_info(sc: Any) -> dict[str, str]:
    java_system = sc._jvm.java.lang.System
    info = {
        "spark": sc.version,
        "java": java_system.getProperty("java.version"),
        "java_vendor": java_system.getProperty("java.vendor"),
        "scala": sc._jvm.scala.util.Properties.versionNumberString(),
    }
    try:
        import pyspark

        info["pyspark"] = pyspark.__version__
    except Exception:
        pass
    return info


def version_info() -> dict[str, str]:
    return {
        "python": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "platform": platform.platform(),
    }


def peak_rss_mib() -> float:
    values = []
    ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        values.append(ru_maxrss / MIB)
    else:
        values.append(ru_maxrss / 1024)

    try:
        import psutil

        process = psutil.Process()
        root = spark_process_root(process)
        rss = root.memory_info().rss
        for child in root.children(recursive=True):
            try:
                rss += child.memory_info().rss
            except psutil.Error:
                pass
        values.append(rss / MIB)
    except Exception:
        pass

    return float(max(values))


def spark_process_root(process: Any) -> Any:
    try:
        parent = process.parent()
        while parent is not None:
            cmdline = " ".join(parent.cmdline())
            if "org.apache.spark.deploy.SparkSubmit" in cmdline or "spark-submit" in cmdline:
                return parent
            parent = parent.parent()
    except Exception:
        return process
    return process


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_metrics(path: Path, metrics: dict[str, Any]) -> None:
    write_json(path, metrics)


def run_workload(
    args: argparse.Namespace,
    algorithms: Sequence[AlgorithmSpec],
    feature_count: int = DEFAULT_FEATURE_COUNT,
) -> dict[str, Any]:
    overall_start = time.perf_counter()

    preprocess_start = time.perf_counter()
    subset = prepare_libsvm_subset(
        data_path=args.data,
        row_count=args.rows,
        work_dir=args.work_dir,
        feature_count=feature_count,
    )
    preprocess_seconds = time.perf_counter() - preprocess_start

    spark_metrics = run_spark_training(args, subset, algorithms)
    total_seconds = time.perf_counter() - overall_start
    return build_metrics(
        args=args,
        subset=subset,
        preprocess_seconds=preprocess_seconds,
        spark_metrics=spark_metrics,
        total_seconds=total_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metrics = run_workload(
        args,
        algorithms=[
            AlgorithmSpec("linear_svm", "SGD", args.svm_iterations),
            AlgorithmSpec("logistic_regression", "LBFGS", args.logreg_iterations),
        ],
    )
    write_metrics(args.output, metrics)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
