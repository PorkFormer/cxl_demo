import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import pot3d_workload_demo as demo


class Pot3dWorkloadDemoTest(unittest.TestCase):
    def test_parses_pot3d_grid_dimensions(self):
        text = """
 &topology
  nr=101
  nt=181
  np=361
 /
 &inputvars
  ifprec=1
 /
"""

        dims = demo.parse_pot3d_dat(text)

        self.assertEqual(dims, demo.GridDimensions(nr=101, nt=181, np=361))

    def test_parses_runtime_and_iterations_from_logs(self):
        runtime_log = """
Summary of test results:
potential_field_current_sheet        PASS         85.229     8.368     0.10
"""
        solver_log = """
 ### The field solver converged.
 Number of iterations =          3678
"""

        self.assertEqual(
            demo.parse_testsuite_runtime(runtime_log, "potential_field_current_sheet"),
            85.229,
        )
        self.assertEqual(demo.parse_solver_iterations(solver_log), 3678)

    def test_recommends_current_sheet_and_excludes_db_vector_workloads(self):
        verdicts = demo.evaluate_default_candidates(ROOT, max_runtime_seconds=180.0)
        recommended = demo.pick_recommendation(verdicts)

        self.assertEqual(recommended.name, "POT3D potential_field_current_sheet")
        self.assertTrue(recommended.passes)
        self.assertGreater(recommended.estimated_hot_set_mib_per_rank, 48.0)
        self.assertGreaterEqual(recommended.iterations, 1000)
        self.assertLessEqual(recommended.runtime_seconds, 180.0)
        self.assertTrue(all("redis" not in item.name.lower() for item in verdicts))
        self.assertTrue(all("ycsb" not in item.name.lower() for item in verdicts))
        self.assertTrue(all("milvus" not in item.name.lower() for item in verdicts))
        self.assertTrue(all("qdrant" not in item.name.lower() for item in verdicts))
        self.assertTrue(all("glove" not in item.name.lower() for item in verdicts))
        self.assertTrue(all("dlrm" not in item.name.lower() for item in verdicts))

    def test_cli_output_contains_verdict_and_rerun_command(self):
        output = demo.render_report(
            demo.evaluate_default_candidates(ROOT, max_runtime_seconds=180.0),
            max_runtime_seconds=180.0,
        )

        self.assertIn("Recommended: POT3D potential_field_current_sheet", output)
        self.assertIn("Verdict: PASS", output)
        self.assertIn("./run_test_suite.sh -np=4 -test=potential_field_current_sheet", output)


if __name__ == "__main__":
    unittest.main()
