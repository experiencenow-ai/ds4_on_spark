import copy
import unittest
from pathlib import Path

from scripts import ds4_pipeline_telemetry as telemetry


FIX = Path("fixtures/pipeline_telemetry")


class PipelineTelemetryTest(unittest.TestCase):
    def test_example_artifact_validates(self) -> None:
        artifact = telemetry.load_json(FIX / "spark_layer_pipeline_run_not_run.example.json")
        self.assertEqual(telemetry.validate_run(artifact), [])
        self.assertEqual(artifact["stage_count"], 3)
        self.assertEqual(artifact["quality_parity_status"], "not_run")

    def test_combine_builds_generic_n_stage_artifact(self) -> None:
        manifest = telemetry.load_json(FIX / "ds4_pipeline_manifest.example.json")
        sequential = telemetry.load_json(FIX / "sequential.example.json")
        stages = [
            telemetry.load_json(FIX / "stage0.example.json"),
            telemetry.load_json(FIX / "stage1.example.json"),
            telemetry.load_json(FIX / "stage2.example.json"),
        ]
        artifact = telemetry.build_run(manifest, sequential, stages, "not_run", "not run")
        self.assertEqual(telemetry.validate_run(artifact), [])
        self.assertAlmostEqual(artifact["speedup_over_sequential"], 43.16546763 / 15.0)
        self.assertEqual(artifact["slowest_stage_id"], "spark2")

    def test_quality_parity_status_is_required(self) -> None:
        artifact = telemetry.load_json(FIX / "spark_layer_pipeline_run_not_run.example.json")
        artifact = copy.deepcopy(artifact)
        del artifact["quality_parity_status"]
        errors = telemetry.validate_run(artifact)
        self.assertTrue(any("quality_parity_status" in item for item in errors))

    def test_sequential_baseline_is_required_for_speedup_claim(self) -> None:
        artifact = telemetry.load_json(FIX / "spark_layer_pipeline_run_not_run.example.json")
        artifact = copy.deepcopy(artifact)
        artifact["sequential_items_per_s"] = 0.0
        errors = telemetry.validate_run(artifact)
        self.assertTrue(any("sequential_items_per_s" in item for item in errors))

    def test_four_stage_manifest_is_valid(self) -> None:
        manifest = telemetry.load_json(FIX / "ds4_pipeline_manifest.example.json")
        sequential = telemetry.load_json(FIX / "sequential.example.json")
        stages = [
            telemetry.load_json(FIX / "stage0.example.json"),
            telemetry.load_json(FIX / "stage1.example.json"),
            telemetry.load_json(FIX / "stage2.example.json"),
            telemetry.load_json(FIX / "stage2.example.json"),
        ]
        manifest = copy.deepcopy(manifest)
        manifest["stage_nodes"] = ["s0", "s1", "s2", "s3"]
        stages[3] = copy.deepcopy(stages[3])
        stages[3]["rank"] = 3
        stages[3]["stage_node"] = "s3"
        artifact = telemetry.build_run(manifest, sequential, stages, "passed", "fixture parity")
        self.assertEqual(telemetry.validate_run(artifact), [])
        self.assertEqual(artifact["stage_count"], 4)


if __name__ == "__main__":
    unittest.main()
