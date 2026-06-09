import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_xgboost_higgs_demo as demo


class XgboostHiggsDemoTest(unittest.TestCase):
    def test_parser_uses_plan_defaults(self):
        args = demo.parse_args([])

        self.assertEqual(args.data, Path("/tmp/cxl_xgboost_higgs/HIGGS.csv.gz"))
        self.assertEqual(args.rows, 2_000_000)
        self.assertEqual(args.rounds, 50)
        self.assertEqual(args.threads, 16)
        self.assertEqual(args.max_depth, 10)
        self.assertEqual(args.max_bin, 256)
        self.assertEqual(args.output, Path("logs/xgboost_higgs_demo_metrics.json"))

    def test_load_higgs_subset_reads_requested_rows_and_hashes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "HIGGS.csv.gz"
            rows = [
                "1,0.1,0.2,0.3,0.4\n",
                "0,1.1,1.2,1.3,1.4\n",
                "1,2.1,2.2,2.3,2.4\n",
            ]
            with gzip.open(data_path, "wt") as handle:
                handle.writelines(rows)

            dataset = demo.load_higgs_subset(data_path, rows=2)

            self.assertEqual(dataset.row_count, 2)
            self.assertEqual(dataset.feature_count, 4)
            self.assertEqual(dataset.labels.tolist(), [1.0, 0.0])
            self.assertEqual(dataset.features.shape, (2, 4))
            self.assertEqual(dataset.sha256, hashlib.sha256(data_path.read_bytes()).hexdigest())

    def test_build_xgboost_params_forces_cpu_hist_mode(self):
        params = demo.build_xgboost_params(threads=8, max_depth=6, max_bin=128, seed=17)

        self.assertEqual(params["tree_method"], "hist")
        self.assertEqual(params["device"], "cpu")
        self.assertEqual(params["nthread"], 8)
        self.assertEqual(params["max_depth"], 6)
        self.assertEqual(params["max_bin"], 128)
        self.assertEqual(params["seed"], 17)

    def test_write_metrics_creates_parent_directory_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "nested" / "metrics.json"
            metrics = {"row_count": 2, "train_seconds": 0.1}

            demo.write_metrics(output, metrics)

            self.assertEqual(json.loads(output.read_text()), metrics)


if __name__ == "__main__":
    unittest.main()
