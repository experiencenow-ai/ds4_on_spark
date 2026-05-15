import copy
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import ds4_stage_boundary_shape_probe as boundary


FIX = Path("fixtures/pipeline_boundary")


class PipelineBoundaryTest(unittest.TestCase):
    def test_boundary_fixtures_validate(self) -> None:
        for path in sorted(FIX.glob("*.json")):
            with self.subTest(path=path.name):
                obj = boundary.load_json(path)
                self.assertEqual(boundary.validate_artifact(obj), [])

    def test_observed_fixture_has_source_static_shape(self) -> None:
        obj = boundary.load_json(FIX / "dsv4_stage_boundary_source_observed.example.json")
        self.assertEqual(obj["probe_status"], "observed")
        self.assertEqual(obj["probe_kind"], "source_static")
        self.assertEqual(obj["observed_tensor_shape"], ["batch", "sequence", 4, 4096])
        self.assertEqual(obj["boundary_after_layers"], [14, 28])

    def test_not_available_fixture_has_blocker_detail(self) -> None:
        obj = boundary.load_json(FIX / "dsv4_stage_boundary_not_available.example.json")
        self.assertEqual(obj["probe_status"], "not_available")
        self.assertTrue(obj["blocker_detail"])

    def test_hash_mismatch_fails(self) -> None:
        obj = boundary.load_json(FIX / "dsv4_stage_boundary_source_observed.example.json")
        obj = copy.deepcopy(obj)
        obj["layout"] = "changed"
        errors = boundary.validate_artifact(obj)
        self.assertTrue(any("artifact_sha256" in item for item in errors))

    def test_top_level_world_size_is_rejected(self) -> None:
        obj = boundary.load_json(FIX / "dsv4_stage_boundary_source_observed.example.json")
        obj = copy.deepcopy(obj)
        obj["world_size"] = 3
        obj["artifact_sha256"] = boundary.artifact_sha256(obj)
        errors = boundary.validate_artifact(obj)
        self.assertTrue(any("fixed Spark count" in item for item in errors))

    def test_default_not_available_probe_emits_valid_artifact(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/ds4_stage_boundary_shape_probe.py", "--probe-status", "not_available"],
            check=True,
            capture_output=True,
            text=True,
        )
        obj = __import__("json").loads(proc.stdout)
        self.assertEqual(boundary.validate_artifact(obj), [])
        self.assertEqual(obj["probe_status"], "not_available")


if __name__ == "__main__":
    unittest.main()
