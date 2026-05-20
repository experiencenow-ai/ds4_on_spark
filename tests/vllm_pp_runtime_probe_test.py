import copy
import unittest
from pathlib import Path

from scripts import run_ds4_vllm_pp_warm_probe as warm_probe
from scripts import validate_ds4_vllm_pp_runtime_probe as validate


FIXTURE = Path("fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_mgmt_gb10_indexer_fallback_20260520.example.json")
WARM_FIXTURE = Path("fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_mgmt_gb10_warm_eager_2tok_decodefallback_20260520.example.json")
STRICT_FASTPATH_FIXTURE = Path("fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_mgmt_gb10_sm121_triton_indexer_cg_20260520.example.json")
MEGAMOE_BLOCKED_FIXTURE = Path("fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_mgmt_gb10_sm121_megamoe_blocked_20260520.example.json")
BATCH16_STRICT_FIXTURE = Path("fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_mgmt_gb10_sm121_flashinfer_cutlass_b16_16tps_20260520.example.json")
BATCH16_10SAMPLE_FIXTURE = Path("fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_mgmt_gb10_sm121_flashinfer_cutlass_b16_10sample_20260520.example.json")


class VllmPpRuntimeProbeTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validate.validate_paths([FIXTURE])
        self.assertEqual(result["errors"], [])

    def test_warm_fixture_validates(self) -> None:
        result = validate.validate_paths([WARM_FIXTURE])
        self.assertEqual(result["errors"], [])

    def test_strict_fastpath_fixture_validates(self) -> None:
        result = validate.validate_paths([STRICT_FASTPATH_FIXTURE])
        self.assertEqual(result["errors"], [])

    def test_megamoe_blocked_fixture_validates(self) -> None:
        result = validate.validate_paths([MEGAMOE_BLOCKED_FIXTURE])
        self.assertEqual(result["errors"], [])

    def test_batch16_strict_fixture_validates(self) -> None:
        result = validate.validate_paths([BATCH16_STRICT_FIXTURE])
        self.assertEqual(result["errors"], [])

    def test_batch16_10sample_fixture_validates(self) -> None:
        result = validate.validate_paths([BATCH16_10SAMPLE_FIXTURE])
        self.assertEqual(result["errors"], [])

    def test_passed_artifact_requires_token_hash(self) -> None:
        obj = validate.load_json(FIXTURE)
        obj.pop("token_hash")
        errors = validate.validate_artifact(obj, FIXTURE)
        self.assertTrue(any("token_hash" in item for item in errors))

    def test_warm_artifact_requires_measured_token_hash(self) -> None:
        obj = validate.load_json(WARM_FIXTURE)
        obj.pop("measured_token_hash")
        errors = validate.validate_artifact(obj, WARM_FIXTURE)
        self.assertTrue(any("measured_token_hash" in item for item in errors))

    def test_token_ids_must_match_generated_tokens(self) -> None:
        obj = copy.deepcopy(validate.load_json(FIXTURE))
        obj["generated_tokens"] = 2
        errors = validate.validate_artifact(obj, FIXTURE)
        self.assertTrue(any("token_ids length" in item for item in errors))

    def test_batch_prompt_generation_can_use_distinct_rows(self) -> None:
        prompts = warm_probe.make_prompts("prompt", 3, unique_prompts=True)
        self.assertEqual(prompts, ["prompt\nRow: 0", "prompt\nRow: 1", "prompt\nRow: 2"])

    def test_batch_prompt_generation_can_share_prefix_exactly(self) -> None:
        prompts = warm_probe.make_prompts("prompt", 3, unique_prompts=False)
        self.assertEqual(prompts, ["prompt", "prompt", "prompt"])

    def test_flatten_ids_preserves_batch_order(self) -> None:
        self.assertEqual(warm_probe.flatten_ids([[1, 2], [], [3]]), [1, 2, 3])

    def test_tps_for_tokens_handles_zero_seconds(self) -> None:
        self.assertEqual(warm_probe.tps_for_tokens(4, 0.0), 0.0)
        self.assertEqual(warm_probe.tps_for_tokens(4, 2.0), 2.0)


if __name__ == "__main__":
    unittest.main()
