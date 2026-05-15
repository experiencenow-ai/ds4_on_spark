import copy
import tempfile
import unittest
from pathlib import Path

from scripts import ds4_local_ppn_parity_probe as local_ppn
from scripts import ds4_pipeline_telemetry as telemetry
from scripts import validate_ds4_pipeline_parity as parity


FIX = Path("fixtures/pipeline_parity")
TEL = Path("fixtures/pipeline_telemetry")
BOUNDARY = Path("fixtures/pipeline_boundary")


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

    def test_local_ppn_not_run_fixture_validates_with_blocker(self) -> None:
        obj = parity.load_json(FIX / "dsv4_local_ppn_parity_not_run.example.json")
        self.assertEqual(parity.validate_artifact(obj), [])
        self.assertEqual(obj["parity_status"], "not_run")
        self.assertEqual(obj["comparison_kind"], "hidden_state")
        self.assertIn("missing Python runtime dependencies", obj["blocker_detail"])

    def test_local_ppn_probe_emits_honest_not_run_artifact(self) -> None:
        args = type("Args", (), {})()
        args.boundary_artifact = str(BOUNDARY / "dsv4_stage_boundary_source_observed.example.json")
        args.parity_run_id = "unit-local-ppn"
        args.provider_id = "spark-ring-dsv4-layer-pipeline"
        args.pipeline_id = "unit-local-ppn"
        args.model_id = "deepseek-ai/DeepSeek-V4-Flash"
        args.runtime_id = "local_ppn_emulated_probe"
        args.quantization_id = "unused"
        args.tokenizer_sha256 = ""
        args.tokenizer_id = "deepseek-v4-flash-tokenizer"
        args.tokenizer_hash_status = "not_available"
        args.input_tokens = "fixture:unit"
        args.comparison_kind = "hidden_state"
        args.parity_status = "auto"
        args.quality_parity_eligible = False
        args.pp1_output_sha256 = ""
        args.ppn_output_sha256 = ""
        args.tolerance_max_abs_error = None
        args.tolerance_mean_abs_error = None
        args.max_abs_error = None
        args.mean_abs_error = None
        args.token_match_count = None
        args.token_total_count = None
        args.quality_parity_detail = ""
        args.blocker_detail = "unit blocker"
        obj = local_ppn.build_artifact(args)
        self.assertEqual(parity.validate_artifact(obj), [])
        self.assertEqual(obj["parity_status"], "not_run")
        self.assertEqual(obj["blocker_detail"], "unit blocker")

    def test_local_ppn_model_comparison_kinds_can_validate(self) -> None:
        source = parity.load_json(FIX / "dsv4_pipeline_parity_failed.example.json")
        for kind in ("hidden_state", "logits", "tokens"):
            with self.subTest(kind=kind):
                artifact = copy.deepcopy(source)
                artifact["parity_run_id"] = f"dsv4-local-ppn-{kind}-passed-temp"
                artifact["parity_status"] = "passed"
                artifact["comparison_kind"] = kind
                artifact["quality_parity_eligible"] = True
                artifact["max_abs_error"] = 0.0
                artifact["mean_abs_error"] = 0.0
                artifact["token_match_count"] = 1
                artifact["token_total_count"] = 1
                artifact["ppn_output_sha256"] = artifact["pp1_output_sha256"]
                artifact["tolerance"] = {"max_abs_error": 0.0, "mean_abs_error": 0.0}
                artifact["quality_parity_detail"] = f"Unit fixture: PP=1 and PP=N {kind} match."
                artifact["artifact_sha256"] = parity.artifact_sha256(artifact)
                self.assertEqual(parity.validate_artifact(artifact), [])
                self.assertTrue(parity.is_quality_parity_pass(artifact))

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
