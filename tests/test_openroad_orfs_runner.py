import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import openroad_orfs_common as common
import run_openroad_orfs_place as place
import run_openroad_orfs_route as route


class OpenRoadOrfsRunnerTest(unittest.TestCase):
    def test_placement_parser_uses_aes_floorplan_and_do_place_defaults(self):
        args = place.parse_args([])

        self.assertEqual(place.WORKLOAD_NAME, "placement")
        self.assertEqual(args.design_config, Path("designs/nangate45/aes/config.mk"))
        self.assertEqual(args.bootstrap_target, "floorplan")
        self.assertEqual(args.timed_target, "do-place")
        self.assertEqual(args.output, Path("logs/openroad_orfs_place_metrics.json"))

    def test_routing_parser_uses_aes_cts_and_do_route_defaults(self):
        args = route.parse_args([])

        self.assertEqual(route.WORKLOAD_NAME, "routing")
        self.assertEqual(args.design_config, Path("designs/nangate45/aes/config.mk"))
        self.assertEqual(args.bootstrap_target, "cts")
        self.assertEqual(args.timed_target, "do-route")
        self.assertEqual(args.output, Path("logs/openroad_orfs_route_metrics.json"))

    def test_native_command_runs_make_in_orfs_flow_directory(self):
        command = common.build_native_make_command(
            orfs_path=Path("/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts"),
            design_config=Path("designs/nangate45/aes/config.mk"),
            target="do-place",
        )

        self.assertEqual(
            command,
            [
                "make",
                "-C",
                "/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts/flow",
                "DESIGN_CONFIG=designs/nangate45/aes/config.mk",
                "do-place",
            ],
        )

    def test_native_tool_env_uses_explicit_executables(self):
        env = common.build_native_tool_env(
            base_env={"PATH": "/usr/bin"},
            openroad_exe=Path("/opt/or/bin/openroad"),
            opensta_exe=Path("/opt/or/bin/sta"),
            yosys_exe=Path("/opt/yosys/bin/yosys"),
        )

        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["OPENROAD_EXE"], "/opt/or/bin/openroad")
        self.assertEqual(env["OPENSTA_EXE"], "/opt/or/bin/sta")
        self.assertEqual(env["YOSYS_EXE"], "/opt/yosys/bin/yosys")

    def test_write_metrics_creates_parent_directory_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "nested" / "metrics.json"
            metrics = {"workload_name": "placement", "exit_status": 0}

            common.write_metrics(output, metrics)

            self.assertEqual(json.loads(output.read_text()), metrics)

    def test_failed_run_still_writes_error_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "metrics" / "orfs.json"
            args = place.parse_args([
                "--work-dir",
                str(Path(tmpdir) / "work"),
                "--output",
                str(output),
            ])

            with contextlib.redirect_stdout(io.StringIO()):
                status = common.run_orfs_workload(
                    args=args,
                    spec=place.SPEC,
                    runner=FailingRunner(),
                )

            metrics = json.loads(output.read_text())
            self.assertNotEqual(status, 0)
            self.assertEqual(metrics["workload_name"], "placement")
            self.assertEqual(metrics["design_config"], "designs/nangate45/aes/config.mk")
            self.assertEqual(metrics["bootstrap_stage"], "floorplan")
            self.assertEqual(metrics["timed_stage"], "do-place")
            self.assertEqual(metrics["execution"]["mode"], "native")
            self.assertNotIn("docker", metrics)
            self.assertIn("native runner unavailable", metrics["error"])
            self.assertIsNotNone(metrics["exit_status"])


class FailingRunner:
    def run(self, *args, **kwargs):
        raise common.CommandError("native runner unavailable")


if __name__ == "__main__":
    unittest.main()
