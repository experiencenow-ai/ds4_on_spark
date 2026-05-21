import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import deploy_ds4_build as deploy


TOPOLOGY = {
    "nodes": [
        {"id": "spark2", "user": "spark2", "ssh_alias": "spark2"},
        {"id": "spark3", "user": "spark3", "ssh_alias": "spark3"},
        {"id": "spark4", "user": "spark4", "ssh_alias": "spark4"},
        {"id": "spark5", "user": "spark5", "ssh_alias": "spark5"},
    ],
    "ring_200g": {
        "order": ["spark2", "spark3", "spark4", "spark5"],
        "links": [
            {"a": {"node": "spark2"}, "b": {"node": "spark3"}},
            {"a": {"node": "spark3"}, "b": {"node": "spark4"}},
            {"a": {"node": "spark4"}, "b": {"node": "spark5"}},
        ],
    },
}


class FakeRunner:
    def __init__(self) -> None:
        self.commands = []

    def __call__(self, command, timeout_seconds=None):
        text = " ".join(command)
        self.commands.append(list(command))
        if "sha256sum" in text and "awk" in text:
            return deploy.CommandResult(0, "abc123\n", "", 0.01)
        if "stat -c" in text:
            return deploy.CommandResult(0, "42\n", "", 0.01)
        if "spark_ring_fast_copy.py" in text:
            return deploy.CommandResult(0, "NATIVE_DONE bytes=42 chunks=1 seconds=0.010 gbps=0.001\n", "", 0.01)
        if "--help" in text:
            return deploy.CommandResult(0, "Usage: ds4 [(-p PROMPT | --prompt-file FILE)] [options]\n", "", 0.01)
        return deploy.CommandResult(0, "", "", 0.01)


class DeployDs4BuildTest(unittest.TestCase):
    def write_topology(self, tmp: str) -> Path:
        path = Path(tmp) / "sparknetwork.json"
        path.write_text(json.dumps(TOPOLOGY), encoding="utf-8")
        return path

    def test_rejects_non_neighbor_ring_gap(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            deploy.validate_ring_hops(TOPOLOGY, ["spark2", "spark5"])
        self.assertIn("not direct 200G neighbors", str(ctx.exception))

    def test_dry_run_prints_hash_and_target_paths_without_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            topology = self.write_topology(tmp)
            runner = FakeRunner()
            out = io.StringIO()
            args = deploy.build_parser().parse_args(
                [
                    "--topology",
                    str(topology),
                    "--dry-run",
                    "--run-id",
                    "unit",
                    "spark2",
                    "spark3",
                    "spark4",
                ]
            )
            with redirect_stdout(out):
                rc = deploy.deploy(args, runner=runner)
            text = out.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("DEPLOY_DS4_BUILD_PLAN", text)
            self.assertIn("existing_build_sha256=abc123", text)
            self.assertIn("spark2:/home/spark2/ds4-deploy/unit/ds4", text)
            self.assertIn("spark3:/home/spark3/ds4-deploy/unit", text)
            self.assertIn("dry_run=true", text)
            self.assertTrue(all("spark_ring_fast_copy.py" not in " ".join(cmd) for cmd in runner.commands))

    def test_live_plan_builds_copies_verifies_and_smokes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            topology = self.write_topology(tmp)
            runner = FakeRunner()
            out = io.StringIO()
            args = deploy.build_parser().parse_args(
                [
                    "--topology",
                    str(topology),
                    "--run-id",
                    "unit",
                    "spark2",
                    "spark3",
                ]
            )
            with redirect_stdout(out):
                rc = deploy.deploy(args, runner=runner)
            text = out.getvalue()
            self.assertEqual(rc, 0)
            joined = "\n".join(" ".join(cmd) for cmd in runner.commands)
            self.assertIn("make ds4", joined)
            self.assertIn("spark_ring_fast_copy.py", joined)
            self.assertIn("source_sha256=abc123 source_bytes=42", text)
            self.assertIn("verified_sha256 spark3:/home/spark3/ds4-deploy/unit/ds4 abc123", text)
            self.assertIn("smoke_ok spark2:/home/spark2/ds4-deploy/unit/ds4 first_line=Usage: ds4", text)
            self.assertIn("DEPLOY_DS4_BUILD_DONE nodes=2", text)


if __name__ == "__main__":
    unittest.main()
