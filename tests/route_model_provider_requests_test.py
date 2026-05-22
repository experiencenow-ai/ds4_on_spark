import copy
import unittest
from pathlib import Path

from scripts import route_model_provider_requests as router
from scripts import select_model_provider


FIXTURE = Path("fixtures/model_provider_routes/centaur_provider_route_requests_20260522.example.json")


class RouteModelProviderRequestsTest(unittest.TestCase):
    def test_fixture_plan_routes_selected_and_blocked_nodes(self) -> None:
        plan, errors = router.load_request_plan(FIXTURE)
        self.assertEqual(errors, [])
        profiles, profile_errors = select_model_provider.load_profile_records([])
        self.assertEqual(profile_errors, [])
        result = router.route_request_plan(plan, profiles)
        self.assertEqual(result["format"], "centaur-provider-routing-plan-v1")
        self.assertEqual(result["request_count"], 4)
        self.assertEqual(result["selected_count"], 3)
        self.assertEqual(result["blocked_count"], 1)
        self.assertFalse(result["all_requests_routed"])
        self.assertEqual(result["blocker_summary"], {"no_eligible_provider": 1})
        vllm_load = result["provider_load"]["vllm-dsv4-flash-pp2-200g-no-mtp"]
        self.assertEqual(vllm_load["request_count"], 2)
        self.assertEqual(vllm_load["batch_tokens"], 32768)
        self.assertEqual(vllm_load["nodes"], ["n_hard_reasoning", "n_batch_judge"])
        self.assertGreater(vllm_load["estimated_service_ms_at_measured_output_tps"], 100000.0)
        self.assertFalse(result["capacity_summary"]["all_requests_capacity_estimated"])
        self.assertEqual(result["capacity_summary"]["blocked_request_count"], 1)

    def test_blocked_route_keeps_structured_rejection_summary(self) -> None:
        plan, errors = router.load_request_plan(FIXTURE)
        self.assertEqual(errors, [])
        profiles, profile_errors = select_model_provider.load_profile_records([])
        self.assertEqual(profile_errors, [])
        result = router.route_request_plan(plan, profiles)
        blocked = [route for route in result["routes"] if route["selected"] is False]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["node_id"], "n_too_fast_hard_reasoning")
        self.assertEqual(blocked[0]["blocker_kind"], "no_eligible_provider")
        self.assertIn("maximum_wait_ms_exceeds_budget", blocked[0]["rejection_summary"])

    def test_capacity_summary_tracks_unknown_capacity_provider(self) -> None:
        plan, errors = router.load_request_plan(FIXTURE)
        self.assertEqual(errors, [])
        profiles, profile_errors = select_model_provider.load_profile_records([])
        self.assertEqual(profile_errors, [])
        result = router.route_request_plan(plan, profiles)
        self.assertIn("standard-local-small-openai-compatible", result["capacity_summary"]["unknown_capacity_provider_ids"])
        self.assertFalse(result["capacity_summary"]["all_selected_capacity_estimated"])
        self.assertIsNone(result["provider_load"]["standard-local-small-openai-compatible"]["estimated_service_ms_at_measured_output_tps"])

    def test_all_estimated_when_only_measured_vllm_nodes_route(self) -> None:
        plan, errors = router.load_request_plan(FIXTURE)
        self.assertEqual(errors, [])
        measured_only = copy.deepcopy(plan)
        measured_only["requests"] = measured_only["requests"][:2]
        profiles, profile_errors = select_model_provider.load_profile_records([])
        self.assertEqual(profile_errors, [])
        result = router.route_request_plan(measured_only, profiles)
        self.assertTrue(result["all_requests_routed"])
        self.assertTrue(result["capacity_summary"]["all_requests_capacity_estimated"])
        self.assertEqual(result["capacity_summary"]["unknown_capacity_provider_ids"], [])
        self.assertGreater(result["capacity_summary"]["estimated_parallel_service_ms_at_measured_output_tps"], 100000.0)

    def test_rejects_duplicate_node_ids(self) -> None:
        plan, errors = router.load_request_plan(FIXTURE)
        self.assertEqual(errors, [])
        duplicate = copy.deepcopy(plan)
        duplicate["requests"][1]["node_id"] = duplicate["requests"][0]["node_id"]
        errors = router.validate_request_plan(duplicate)
        self.assertTrue(any("node_id must be unique" in item for item in errors))

    def test_rejects_unknown_request_tier(self) -> None:
        plan, errors = router.load_request_plan(FIXTURE)
        self.assertEqual(errors, [])
        bad = copy.deepcopy(plan)
        bad["requests"][0]["tier"] = "wizard"
        errors = router.validate_request_plan(bad)
        self.assertTrue(any("tier is unknown" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
