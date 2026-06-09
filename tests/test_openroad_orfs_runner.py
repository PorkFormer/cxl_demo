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

    def test_docker_command_mounts_orfs_repo_and_uses_image_toolchain(self):
        command = common.build_docker_make_command(
            orfs_path=Path("/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts"),
            image="openroad/orfs",
            memory="64g",
            container_name="orfs-place-test",
            design_config=Path("designs/nangate45/aes/config.mk"),
            target="do-place",
        )

        self.assertEqual(command[0:2], ["docker", "run"])
        self.assertIn("--rm", command)
        self.assertIn("--memory", command)
        self.assertIn("64g", command)
        self.assertIn(
            "/tmp/cxl_openroad_orfs/OpenROAD-flow-scripts:/work/OpenROAD-flow-scripts",
            command,
        )
        self.assertIn("-w", command)
        self.assertIn("/work/OpenROAD-flow-scripts", command)
        self.assertIn("openroad/orfs", command)
        self.assertIn(
            "OPENROAD_EXE=/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad",
            command,
        )
        self.assertIn(
            "OPENSTA_EXE=/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta",
            command,
        )
        self.assertIn("YOSYS_EXE=/usr/local/bin/yosys", command)
        self.assertEqual(
            command[-5:],
            [
                "make",
                "-C",
                "flow",
                "DESIGN_CONFIG=designs/nangate45/aes/config.mk",
                "do-place",
            ],
        )

    def test_sg_docker_command_wraps_quoted_docker_command(self):
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--name",
            "orfs route test",
            "openroad/orfs",
            "make",
            "DESIGN_CONFIG=designs/nangate45/aes/config.mk",
            "do-route",
        ]

        wrapped = common.wrap_docker_command(docker_command, docker_mode="sg")

        self.assertEqual(wrapped[0:3], ["sg", "docker", "-c"])
        self.assertEqual(
            wrapped[3],
            "docker run --rm --name 'orfs route test' openroad/orfs make "
            "DESIGN_CONFIG=designs/nangate45/aes/config.mk do-route",
        )

    def test_parse_memory_mib_accepts_docker_stats_units(self):
        cases = {
            "512MiB": 512.0,
            "1.5GiB": 1536.0,
            "2048KiB": 2.0,
            "1048576B": 1.0,
            "123.25MiB / 64GiB": 123.25,
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(common.parse_memory_mib(text), expected)

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
            self.assertIn("docker unavailable", metrics["error"])
            self.assertIsNotNone(metrics["exit_status"])


class FailingRunner:
    def run(self, *args, **kwargs):
        raise common.CommandError("docker unavailable")


if __name__ == "__main__":
    unittest.main()
