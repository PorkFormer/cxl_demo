import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_spark_mllib_higgs_demo as demo
import run_spark_mllib_higgs_logreg as logreg_workload
import run_spark_mllib_higgs_svm as svm_workload


class SparkMllibHiggsDemoTest(unittest.TestCase):
    def test_parser_uses_plan_defaults(self):
        args = demo.parse_args([])

        self.assertEqual(args.data, Path("/tmp/cxl_xgboost_higgs/HIGGS.csv.gz"))
        self.assertEqual(args.rows, 2_000_000)
        self.assertEqual(args.work_dir, Path("/tmp/cxl_spark_mllib_higgs"))
        self.assertEqual(args.master, "local[16]")
        self.assertEqual(args.partitions, 64)
        self.assertEqual(args.storage_level, "MEMORY_ONLY")
        self.assertEqual(args.svm_iterations, 30)
        self.assertEqual(args.logreg_iterations, 30)
        self.assertEqual(args.seed, 20260609)
        self.assertEqual(args.output, Path("logs/spark_mllib_higgs_demo_metrics.json"))

    def test_svm_workload_parser_uses_independent_defaults(self):
        args = svm_workload.parse_args([])

        self.assertEqual(svm_workload.ALGORITHM_NAME, "linear_svm")
        self.assertEqual(args.data, Path("/tmp/cxl_xgboost_higgs/HIGGS.csv.gz"))
        self.assertEqual(args.rows, 2_000_000)
        self.assertEqual(args.work_dir, Path("/tmp/cxl_spark_mllib_higgs"))
        self.assertEqual(args.master, "local[16]")
        self.assertEqual(args.partitions, 64)
        self.assertEqual(args.storage_level, "MEMORY_ONLY")
        self.assertEqual(args.iterations, 30)
        self.assertEqual(args.output, Path("logs/spark_mllib_higgs_svm_metrics.json"))

    def test_logreg_workload_parser_uses_independent_defaults(self):
        args = logreg_workload.parse_args([])

        self.assertEqual(logreg_workload.ALGORITHM_NAME, "logistic_regression")
        self.assertEqual(args.data, Path("/tmp/cxl_xgboost_higgs/HIGGS.csv.gz"))
        self.assertEqual(args.rows, 2_000_000)
        self.assertEqual(args.work_dir, Path("/tmp/cxl_spark_mllib_higgs"))
        self.assertEqual(args.master, "local[16]")
        self.assertEqual(args.partitions, 64)
        self.assertEqual(args.storage_level, "MEMORY_ONLY")
        self.assertEqual(args.iterations, 30)
        self.assertEqual(args.output, Path("logs/spark_mllib_higgs_logreg_metrics.json"))

    def test_higgs_csv_row_to_libsvm_keeps_all_one_based_features(self):
        line = "1,0.1,-2.5,3e-4\n"

        converted = demo.higgs_csv_row_to_libsvm(line, feature_count=3)

        self.assertEqual(converted, "1 1:0.1 2:-2.5 3:3e-4")

    def test_preprocess_writes_metadata_and_reuses_matching_subset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            data_path = tmp / "HIGGS.csv.gz"
            rows = [
                "1,0.1,0.2,0.3\n",
                "0,1.1,1.2,1.3\n",
                "1,2.1,2.2,2.3\n",
            ]
            with gzip.open(data_path, "wt") as handle:
                handle.writelines(rows)

            first = demo.prepare_libsvm_subset(
                data_path=data_path,
                row_count=2,
                work_dir=tmp / "work",
                feature_count=3,
            )
            second = demo.prepare_libsvm_subset(
                data_path=data_path,
                row_count=2,
                work_dir=tmp / "work",
                feature_count=3,
            )

            source_sha256 = hashlib.sha256(data_path.read_bytes()).hexdigest()
            metadata = json.loads(first.metadata_path.read_text())
            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(first.path.read_text().splitlines(), [
                "1 1:0.1 2:0.2 3:0.3",
                "0 1:1.1 2:1.2 3:1.3",
            ])
            self.assertEqual(metadata["row_count"], 2)
            self.assertEqual(metadata["feature_count"], 3)
            self.assertEqual(metadata["source_sha256"], source_sha256)
            self.assertEqual(second.libsvm_sha256, metadata["libsvm_sha256"])

    def test_metadata_mismatch_forces_regeneration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            data_path = tmp / "HIGGS.csv.gz"
            with gzip.open(data_path, "wt") as handle:
                handle.write("1,0.1,0.2\n")
                handle.write("0,0.3,0.4\n")

            subset = demo.prepare_libsvm_subset(
                data_path=data_path,
                row_count=1,
                work_dir=tmp / "work",
                feature_count=2,
            )
            metadata = json.loads(subset.metadata_path.read_text())
            metadata["row_count"] = 999
            subset.metadata_path.write_text(json.dumps(metadata))

            regenerated = demo.prepare_libsvm_subset(
                data_path=data_path,
                row_count=1,
                work_dir=tmp / "work",
                feature_count=2,
            )

            self.assertFalse(regenerated.reused)
            self.assertEqual(json.loads(subset.metadata_path.read_text())["row_count"], 1)

    def test_write_metrics_creates_parent_directory_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "nested" / "metrics.json"
            metrics = {"row_count": 2, "algorithms": {"svm": {"error_rate": 0.25}}}

            demo.write_metrics(output, metrics)

            self.assertEqual(json.loads(output.read_text()), metrics)

    def test_spark_process_root_detects_sparksubmit_parent(self):
        spark_parent = FakeProcess(["java", "org.apache.spark.deploy.SparkSubmit"])
        python_driver = FakeProcess(["python3", "script.py"], parent=spark_parent)

        self.assertIs(demo.spark_process_root(python_driver), spark_parent)


class FakeProcess:
    def __init__(self, cmdline, parent=None):
        self._cmdline = cmdline
        self._parent = parent

    def cmdline(self):
        return self._cmdline

    def parent(self):
        return self._parent


if __name__ == "__main__":
    unittest.main()
