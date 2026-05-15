import copy
import tempfile
import unittest
from pathlib import Path

from scripts import validate_ds4_full_stack_truth as truth


FIX = Path("fixtures/full_stack_truth")


class FullStackTruthTest(unittest.TestCase):
    def test_full_stack_truth_fixtures_validate(self) -> None:
        for path in sorted(FIX.glob("*.json")):
            with self.subTest(path=path.name):
                obj = truth.load_json(path)
                self.assertEqual(truth.validate_record(obj), [])

    def test_hash_mismatch_fails_validation(self) -> None:
        obj = truth.load_json(FIX / "full_stack_b1_13_3tok_success.example.json")
        obj = copy.deepcopy(obj)
        obj["tokens_per_second"] = 14.0
        errors = truth.validate_record(obj)
        self.assertTrue(any("artifact_sha256" in item for item in errors))

    def test_full_stack_success_requires_all_layers(self) -> None:
        obj = truth.load_json(FIX / "full_stack_b128_80tok_success.example.json")
        obj = copy.deepcopy(obj)
        obj["layers_executed"] = 42
        obj["artifact_sha256"] = truth.artifact_sha256(obj)
        errors = truth.validate_record(obj)
        self.assertTrue(any("full-stack success" in item for item in errors))

    def test_success_requires_finite_output_and_hash(self) -> None:
        obj = truth.load_json(FIX / "full_stack_b128_80tok_success.example.json")
        obj = copy.deepcopy(obj)
        obj["finite_output"] = False
        obj["output_hash"] = ""
        obj["artifact_sha256"] = truth.artifact_sha256(obj)
        errors = truth.validate_record(obj)
        self.assertTrue(any("finite_output" in item for item in errors))
        self.assertTrue(any("output_hash" in item for item in errors))

    def test_batch_claim_requires_batch_size(self) -> None:
        obj = truth.load_json(FIX / "full_stack_b128_80tok_success.example.json")
        obj = copy.deepcopy(obj)
        obj["batch_size"] = 0
        obj["artifact_sha256"] = truth.artifact_sha256(obj)
        errors = truth.validate_record(obj)
        self.assertTrue(any("batch_size" in item for item in errors))

    def test_realization_ratio_requires_named_ceilings(self) -> None:
        obj = truth.load_json(FIX / "full_stack_b1_13_3tok_success.example.json")
        obj = copy.deepcopy(obj)
        obj["realization_ratio"].pop("vs_synthetic_layer_ceiling")
        obj["artifact_sha256"] = truth.artifact_sha256(obj)
        errors = truth.validate_record(obj)
        self.assertTrue(any("vs_synthetic_layer_ceiling" in item for item in errors))

    def test_component_only_ceilings_are_not_labeled_end_to_end(self) -> None:
        obj = truth.load_json(FIX / "synthetic_layer_409_component_only.example.json")
        self.assertEqual(truth.validate_record(obj), [])
        self.assertEqual(obj["path_kind"], "batch_stack_no_head")
        self.assertFalse(obj["includes_output_head"])

    def test_blocker_classifier_identifies_residency_failures(self) -> None:
        self.assertEqual(
            truth.classify_blocker("q8_0 lazy range upload timed out", 1),
            "q8_0_lazy_range_upload",
        )
        self.assertEqual(
            truth.classify_blocker("CUDA model range upload sync failed for attn_out_a", 1),
            "q8_0_lazy_range_upload",
        )
        self.assertEqual(
            truth.classify_blocker("moe_down_expert_batched full-slab fallback timed out", 1),
            "full_slab_fallback",
        )
        self.assertEqual(
            truth.classify_blocker("ds4: accelerator stopped startup model cache after 7.26 GiB", 1),
            "startup_preload_timeout",
        )

    def test_record_builder_parses_output_head_probe(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            out = root / "probe.out"
            err = root / "probe.err"
            out.write_text(
                '{"cuda_output_head_probe":true,"avg_ms":197.955,"best_ms":2.579,'
                '"best_heads_per_s":387.807,"logits_fnv64":"d99730a7a09d8f8a",'
                '"logits_nonfinite":0}\n',
                encoding="utf-8",
            )
            err.write_text("", encoding="utf-8")
            args = type("Args", (), {})()
            args.stdout = str(out)
            args.stderr = str(err)
            args.rc = 0
            args.path_kind = "output_head"
            args.run_id = "unit-output-head"
            args.model_id = "deepseek-ai/DeepSeek-V4-Flash"
            args.runtime_id = "antirez-ds4-cuda-stack-probe"
            args.quantization_id = "fixture.gguf"
            args.spark_node = "spark0-fixture"
            args.batch_size = 1
            args.layers_executed = 0
            args.includes_output_head = True
            args.includes_attention = False
            args.includes_kv = False
            args.includes_sampling = False
            args.warmup_policy = "unit"
            args.residency_policy = "unit"
            obj = truth.build_record(args)
            self.assertEqual(truth.validate_record(obj), [])
            self.assertEqual(obj["failure_status"], "success")
            self.assertEqual(obj["output_hash"], "fnv64:d99730a7a09d8f8a")

    def test_top_level_world_size_is_rejected(self) -> None:
        obj = truth.load_json(FIX / "full_stack_b1_13_3tok_success.example.json")
        obj = copy.deepcopy(obj)
        obj["world_size"] = 3
        obj["artifact_sha256"] = truth.artifact_sha256(obj)
        errors = truth.validate_record(obj)
        self.assertTrue(any("fixed Spark count" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
