import copy
import unittest
from pathlib import Path

from scripts import estimate_ds4_vllm_moe_queue_gain as gain


class VllmMoeQueueGainTest(unittest.TestCase):
	def test_fixture_validates(self) -> None:
		result = gain.validate_paths(gain.default_paths())
		self.assertTrue(result["ok"], result["errors"])

	def test_hash_mismatch_rejected(self) -> None:
		path = Path("fixture.json")
		obj = gain.load(gain.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["baseline_c512_aggregate_tps"] = 123.0
		errors = gain.validate(obj, path)
		self.assertTrue(any("artifact_sha256" in item for item in errors))

	def test_amdahl_estimate_uses_moe_fraction(self) -> None:
		self.assertAlmostEqual(gain.overall_speedup(0.92, 2.0), 1.8518518518518516)
		self.assertAlmostEqual(gain.overall_speedup(0.92, 3.0), 2.586206896551724)

	def test_implied_moe_speedup_from_ds4_rows(self) -> None:
		stage_speedup = (631.6720652969875 / 209.0)
		self.assertAlmostEqual(gain.implied_moe_speedup(0.92, stage_speedup), 3.6672689352013244)

	def test_inconsistent_scenario_rejected(self) -> None:
		path = Path("fixture.json")
		obj = gain.load(gain.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["scenarios"][0]["estimated_c512_aggregate_tps"] = 999.0
		obj["artifact_sha256"] = gain.canonical_hash(obj)
		errors = gain.validate(obj, path)
		self.assertTrue(any("estimated_c512_aggregate_tps is inconsistent" in item for item in errors))

	def test_missing_required_scenario_rejected(self) -> None:
		path = Path("fixture.json")
		obj = gain.load(gain.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["scenarios"] = [item for item in obj["scenarios"] if item["id"] != "two_x_moe"]
		obj["artifact_sha256"] = gain.canonical_hash(obj)
		errors = gain.validate(obj, path)
		self.assertTrue(any("missing scenario ids" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
