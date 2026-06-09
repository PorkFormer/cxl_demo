#!/usr/bin/env python3
"""Run a CPU-only XGBoost hist training demo on a HIGGS CSV subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import psutil
import sklearn
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

MIB = 1024 * 1024
DEFAULT_DATA = Path("/tmp/cxl_xgboost_higgs/HIGGS.csv.gz")
DEFAULT_OUTPUT = Path("logs/xgboost_higgs_demo_metrics.json")


@dataclass(frozen=True)
class HiggsSubset:
    features: np.ndarray
    labels: np.ndarray
    row_count: int
    feature_count: int
    sha256: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train XGBoost on a CPU-only HIGGS subset and write JSON metrics."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="HIGGS.csv.gz path")
    parser.add_argument("--rows", type=positive_int, default=2_000_000)
    parser.add_argument("--rounds", type=positive_int, default=50)
    parser.add_argument("--threads", type=positive_int, default=16)
    parser.add_argument("--max-depth", type=positive_int, default=10)
    parser.add_argument("--max-bin", type=positive_int, default=256)
    parser.add_argument("--learning-rate", type=positive_float, default=0.1)
    parser.add_argument("--test-size", type=positive_float, default=0.2)
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
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_higgs_subset(path: Path, rows: int) -> HiggsSubset:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"HIGGS data file not found: {path}")

    data_sha256 = sha256_file(path)
    frame = pd.read_csv(path, header=None, nrows=rows, compression="infer", dtype=np.float32)
    if frame.empty:
        raise ValueError(f"no rows loaded from {path}")
    if frame.shape[1] < 2:
        raise ValueError(f"expected label plus features in {path}, got {frame.shape[1]} column")

    labels = frame.iloc[:, 0].to_numpy(dtype=np.float32, copy=True)
    features = frame.iloc[:, 1:].to_numpy(dtype=np.float32, copy=True)
    return HiggsSubset(
        features=features,
        labels=labels,
        row_count=int(features.shape[0]),
        feature_count=int(features.shape[1]),
        sha256=data_sha256,
    )


def build_xgboost_params(
    threads: int,
    max_depth: int,
    max_bin: int,
    seed: int,
    learning_rate: float = 0.1,
) -> dict[str, object]:
    return {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "tree_method": "hist",
        "device": "cpu",
        "nthread": threads,
        "max_depth": max_depth,
        "max_bin": max_bin,
        "eta": learning_rate,
        "seed": seed,
        "verbosity": 1,
    }


def train_and_evaluate(dataset: HiggsSubset, args: argparse.Namespace) -> dict[str, object]:
    stratify = dataset.labels if _can_stratify(dataset.labels) else None
    x_train, x_test, y_train, y_test = train_test_split(
        dataset.features,
        dataset.labels,
        test_size=args.test_size,
        random_state=args.seed,
        stratify=stratify,
    )

    dtrain = xgb.DMatrix(x_train, label=y_train)
    dtest = xgb.DMatrix(x_test, label=y_test)
    params = build_xgboost_params(
        threads=args.threads,
        max_depth=args.max_depth,
        max_bin=args.max_bin,
        seed=args.seed,
        learning_rate=args.learning_rate,
    )

    start = time.perf_counter()
    booster = xgb.train(
        params=params,
        dtrain=dtrain,
        num_boost_round=args.rounds,
        evals=[(dtrain, "train"), (dtest, "test")],
        verbose_eval=False,
    )
    train_seconds = time.perf_counter() - start
    predictions = booster.predict(dtest)
    auc = float(roc_auc_score(y_test, predictions))

    return {
        "auc": auc,
        "train_seconds": train_seconds,
        "train_rows": int(x_train.shape[0]),
        "test_rows": int(x_test.shape[0]),
        "peak_rss_mib": peak_rss_mib(),
        "params": params,
    }


def build_metrics(
    dataset: HiggsSubset,
    args: argparse.Namespace,
    load_seconds: float,
    train_metrics: dict[str, object],
    total_seconds: float,
) -> dict[str, object]:
    return {
        "data_path": str(args.data),
        "data_sha256": dataset.sha256,
        "row_count": dataset.row_count,
        "feature_count": dataset.feature_count,
        "rounds": args.rounds,
        "threads": args.threads,
        "max_depth": args.max_depth,
        "max_bin": args.max_bin,
        "learning_rate": args.learning_rate,
        "test_size": args.test_size,
        "seed": args.seed,
        "versions": version_info(),
        "load_seconds": load_seconds,
        "total_seconds": total_seconds,
        **train_metrics,
    }


def version_info() -> dict[str, str]:
    return {
        "python": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "xgboost": xgb.__version__,
        "sklearn": sklearn.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "psutil": psutil.__version__,
    }


def peak_rss_mib() -> float:
    current_rss = psutil.Process().memory_info().rss / MIB
    ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        resource_peak = ru_maxrss / MIB
    else:
        resource_peak = ru_maxrss / 1024
    return float(max(current_rss, resource_peak))


def write_metrics(path: Path, metrics: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")


def _can_stratify(labels: np.ndarray) -> bool:
    _, counts = np.unique(labels, return_counts=True)
    return len(counts) > 1 and bool(np.all(counts >= 2))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    overall_start = time.perf_counter()

    load_start = time.perf_counter()
    dataset = load_higgs_subset(args.data, args.rows)
    load_seconds = time.perf_counter() - load_start

    train_metrics = train_and_evaluate(dataset, args)
    total_seconds = time.perf_counter() - overall_start
    metrics = build_metrics(dataset, args, load_seconds, train_metrics, total_seconds)
    write_metrics(args.output, metrics)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
