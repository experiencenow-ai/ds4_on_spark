import copy
import unittest
from pathlib import Path

from scripts import select_model_provider as selector
from scripts import validate_model_provider_profiles as profile_validator


class SelectModelProviderTest(unittest.TestCase):
    def test_selects_measured_vllm_near_frontier_batch_lane(self) -> None:
        profiles, errors = selector.load_profile_records([])
        self.assertEqual(errors, [])
        result = selector.select_provider(profiles, "near_frontier_local", "hard_reasoning", 16384)
        self.assertTrue(result["selected"], result)
        self.assertEqual(result["selected_provider"]["provider_id"], "vllm-dsv4-flash-pp2-200g-no-mtp")
        self.assertEqual(result["selected_provider"]["tier"], "near_frontier_local")
        self.assertGreater(result["selected_provider"]["measured_output_tps"], 100.0)

    def test_no_silent_lower_tier_selection(self) -> None:
        profile = profile_validator.load_profile(Path("fixtures/model_providers/vllm_deepseek_v4_flash_pp2_200g_near_frontier_20260522.example.json"))
        profile = copy.deepcopy(profile)
        profile["provider_id"] = "too-small"
        profile["tier"] = "local_small"
        result = selector.select_provider([profile], "near_frontier_local", "hard_reasoning", 16384)
        self.assertFalse(result["selected"])
        self.assertEqual(result["blocker_kind"], "no_eligible_provider")
        self.assertEqual(result["rejection_summary"]["tier_below_required"], 1)

    def test_lane_mismatch_returns_structured_blocker(self) -> None:
        profiles, errors = selector.load_profile_records([])
        self.assertEqual(errors, [])
        result = selector.select_provider(profiles, "local_coder", "unserved_lane", 256)
        self.assertFalse(result["selected"])
        self.assertEqual(result["blocker_kind"], "no_eligible_provider")
        self.assertIn("lane_not_supported", result["rejection_summary"])

    def test_max_wait_budget_filters_selected_provider(self) -> None:
        profiles, errors = selector.load_profile_records([])
        self.assertEqual(errors, [])
        result = selector.select_provider(profiles, "near_frontier_local", "hard_reasoning", 16384, max_wait_ms=10)
        self.assertFalse(result["selected"])
        self.assertGreaterEqual(result["rejection_summary"]["maximum_wait_ms_exceeds_budget"], 1)
        self.assertIn("maximum_wait_ms_exceeds_budget", result["rejections_by_provider"]["vllm-dsv4-flash-pp2-200g-no-mtp"])

    def test_allow_non_production_supports_planning_only(self) -> None:
        profiles, errors = selector.load_profile_records([])
        self.assertEqual(errors, [])
        result = selector.select_provider(profiles, "local_small", "candidate_prefilter", 1024, require_production_eligible=False)
        self.assertTrue(result["selected"], result)
        self.assertEqual(result["selected_provider"]["tier"], "local_small")

    def test_selects_measured_local_small_provider_by_default(self) -> None:
        profiles, errors = selector.load_profile_records([])
        self.assertEqual(errors, [])
        result = selector.select_provider(profiles, "local_small", "candidate_prefilter", 32)
        self.assertTrue(result["selected"], result)
        self.assertEqual(result["selected_provider"]["provider_id"], "spark2-hf-qwen-qwen3-5-2b-local_small-measured")
        self.assertGreater(result["selected_provider"]["measured_output_tps"], 20.0)

    def test_selects_measured_local_coder_provider_by_default(self) -> None:
        profiles, errors = selector.load_profile_records([])
        self.assertEqual(errors, [])
        result = selector.select_provider(profiles, "local_coder", "schema_repair", 32)
        self.assertTrue(result["selected"], result)
        self.assertEqual(result["selected_provider"]["provider_id"], "spark2-hf-qwen-qwen3-5-2b-local_coder-measured")
        self.assertEqual(result["selected_provider"]["tier"], "local_coder")


if __name__ == "__main__":
    unittest.main()
