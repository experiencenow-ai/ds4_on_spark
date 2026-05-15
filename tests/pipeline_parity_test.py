import copy
import tempfile
import unittest
from pathlib import Path

from scripts import ds4_pipeline_telemetry as telemetry
from scripts import validate_ds4_pipeline_parity as parity


FIX = Path("fixtures/pipeline_parity")
TEL = Path("fixtures/pipeline_telemetry")


class PipelineParityTest(unittest.TestCase):
    def test_parity_fixtures_validate(self) -> None:
        for path in sorted(FIX.glob("*.json")):
            with self.subTest(path=path.name):
                obj = parity.load_json(path)
                self.assertEqual(parity.validate_artifact(obj), [])

    def test_hash_mismatch_fails_validation(self) -> None:
        obj = parity.load_json(FIX / "dsv4_pipeline_parity_not_run.example.json")
        obj = copy.deepcopy(obj)
        obj["provider_id"] = "changed-provider"
        errors = parity.validate_artifact(obj)
        self.assertTrue(any("artifact_sha256" in item for item in errors))

    def test_passed_without_metrics_fails(self) -> None:
        obj = parity.load_json(FIX / "dsv4_pipeline_parity_failed.example.json")
        obj = copy.deepcopy(obj)
        obj["parity_status"] = "passed"
        obj["comparison_kind"] = "logits"
        obj["quality_parity_eligible"] = True
        obj["max_abs_error"] = None
        obj["artifact_sha256"] = parity.artifact_sha256(obj)
        errors = parity.validate_artifact(obj)
        self.assertTrue(any("max_abs_error" in item for item in errors))

    def test_synthetic_integrity_is_not_quality_parity(self) -> None:
        obj = parity.load_json(FIX / "synthetic_pipeline_integrity_passed.example.json")
        self.assertEqual(parity.validate_artifact(obj), [])
        self.assertFalse(parity.is_quality_parity_pass(obj))

    def test_top_level_world_size_is_rejected(self) -> None:
        obj = parity.load_json(FIX / "dsv4_pipeline_parity_not_run.example.json")
        obj = copy.deepcopy(obj)
        obj["world_size"] = 3
        obj["artifact_sha256"] = parity.artifact_sha256(obj)
        errors = parity.validate_artifact(obj)
        self.assertTrue(any("fixed Spark count" in item for item in errors))

    def test_telemetry_not_run_remains_valid_without_parity_artifact(self) -> None:
        obj = telemetry.load_json(TEL / "spark_layer_pipeline_run_not_run.example.json")
        self.assertEqual(telemetry.validate_run(obj, TEL), [])

    def test_telemetry_passed_rejects_synthetic_artifact(self) -> None:
        obj = telemetry.load_json(TEL / "spark_layer_pipeline_run_not_run.example.json")
        obj = copy.deepcopy(obj)
        obj["quality_parity_status"] = "passed"
        obj["quality_parity_artifact"] = "../pipeline_parity/synthetic_pipeline_integrity_passed.example.json"
        synth = parity.load_json(FIX / "synthetic_pipeline_integrity_passed.example.json")
        obj["quality_parity_artifact_sha256"] = synth["artifact_sha256"]
        obj["artifact_sha256"] = telemetry.artifact_sha256(obj)
        errors = telemetry.validate_run(obj, TEL)
        self.assertTrue(any("synthetic" in item or "quality parity" in item for item in errors))

    def test_telemetry_passed_accepts_real_passed_parity_artifact(self) -> None:
        source = parity.load_json(FIX / "dsv4_pipeline_parity_failed.example.json")
        artifact = copy.deepcopy(source)
        artifact["parity_run_id"] = "dsv4-pipeline-parity-passed-temp"
        artifact["parity_status"] = "passed"
        artifact["comparison_kind"] = "tokens"
        artifact["quality_parity_eligible"] = True
        artifact["max_abs_error"] = 0.0
        artifact["mean_abs_error"] = 0.0
        artifact["token_match_count"] = 1
        artifact["token_total_count"] = 1
        artifact["ppn_output_sha256"] = artifact["pp1_output_sha256"]
        artifact["tolerance"] = {"max_abs_error": 0.0, "mean_abs_error": 0.0}
        artifact["quality_parity_detail"] = "Temporary test fixture: PP=1 and PP=N tokens match."
        artifact["artifact_sha256"] = parity.artifact_sha256(artifact)
        self.assertTrue(parity.is_quality_parity_pass(artifact))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdir = root / "parity"
            tdir = root / "telemetry"
            pdir.mkdir()
            tdir.mkdir()
            parity_path = pdir / "passed.json"
            parity_path.write_text(__import__("json").dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            obj = telemetry.load_json(TEL / "spark_layer_pipeline_run_not_run.example.json")
            obj = copy.deepcopy(obj)
            obj["quality_parity_status"] = "passed"
            obj["quality_parity_artifact"] = "../parity/passed.json"
            obj["quality_parity_artifact_sha256"] = artifact["artifact_sha256"]
            obj["artifact_sha256"] = telemetry.artifact_sha256(obj)
            self.assertEqual(telemetry.validate_run(obj, tdir), [])


if __name__ == "__main__":
    unittest.main()
