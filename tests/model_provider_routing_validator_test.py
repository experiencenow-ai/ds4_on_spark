import copy
import unittest
from pathlib import Path

from scripts import route_model_provider_requests as router
from scripts import select_model_provider
from scripts import validate_model_provider_routing as validator


FIXTURE = Path("fixtures/model_provider_routes/centaur_provider_route_requests_20260522.example.json")


def generated_plan() -> dict:
    plan, errors = router.load_request_plan(FIXTURE)
    if errors:
        raise AssertionError(errors)
    profiles, profile_errors = select_model_provider.load_profile_records([])
    if profile_errors:
        raise AssertionError(profile_errors)
    return router.route_request_plan(plan, profiles)


class ModelProviderRoutingValidatorTest(unittest.TestCase):
    def test_default_route_request_fixture_validates(self) -> None:
        result = validator.validate_paths(validator.default_paths())
        self.assertTrue(result["ok"], result["errors"])
        self.assertGreaterEqual(result["artifact_count"], 1)

    def test_generated_routing_plan_validates(self) -> None:
        plan = generated_plan()
        errors = validator.validate_artifact(plan, Path("generated.json"))
        self.assertEqual(errors, [])

    def test_rejects_provider_load_drift(self) -> None:
        plan = generated_plan()
        plan = copy.deepcopy(plan)
        plan["provider_load"]["vllm-dsv4-flash-pp2-200g-no-mtp"]["batch_tokens"] += 1
        errors = validator.validate_artifact(plan, Path("generated.json"))
        self.assertTrue(any("provider_load does not match routes" in item for item in errors))

    def test_rejects_capacity_summary_drift(self) -> None:
        plan = generated_plan()
        plan = copy.deepcopy(plan)
        plan["capacity_summary"]["blocked_request_count"] += 1
        errors = validator.validate_artifact(plan, Path("generated.json"))
        self.assertTrue(any("capacity_summary does not match" in item for item in errors))

    def test_rejects_selected_count_drift(self) -> None:
        plan = generated_plan()
        plan = copy.deepcopy(plan)
        plan["selected_count"] += 1
        errors = validator.validate_artifact(plan, Path("generated.json"))
        self.assertTrue(any("selected_count must match" in item for item in errors))

    def test_blocked_route_requires_blocker_kind(self) -> None:
        plan = generated_plan()
        plan = copy.deepcopy(plan)
        blocked = [route for route in plan["routes"] if route["selected"] is False][0]
        blocked["blocker_kind"] = None
        errors = validator.validate_artifact(plan, Path("generated.json"))
        self.assertTrue(any("blocker_kind must be present" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
