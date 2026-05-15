import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_stage_handoff_truth as handoff


FIX = Path("fixtures/stage_handoff")


class StageHandoffTruthTest(unittest.TestCase):
	def test_stage_handoff_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = handoff.load_json(path)
				self.assertEqual(handoff.validate_artifact(obj), [])

	def test_nonfinite_success_without_hash_fails(self) -> None:
		obj = handoff.load_json(FIX / "spark012_b64_file_handoff_finite_logits.example.json")
		obj = copy.deepcopy(obj)
		obj["final_logits_hash"] = "fnv64:0000000000000000"
		errors = handoff.validate_artifact(obj)
		self.assertTrue(any("final_logits_hash" in item for item in errors))

	def test_fixed_spark_count_field_fails(self) -> None:
		obj = handoff.load_json(FIX / "spark012_b64_file_handoff_finite_logits.example.json")
		obj = copy.deepcopy(obj)
		obj["world_size"] = 3
		errors = handoff.validate_artifact(obj)
		self.assertTrue(any("fixed Spark count" in item for item in errors))

	def test_pipeline_bound_is_checked(self) -> None:
		obj = handoff.load_json(FIX / "local_b64_finite_logits.example.json")
		obj = copy.deepcopy(obj)
		obj["pipeline_rows_per_s_bound"] = 1.0
		errors = handoff.validate_artifact(obj)
		self.assertTrue(any("pipeline_rows_per_s_bound" in item for item in errors))

	def test_streaming_fixture_requires_microbatch_hashes(self) -> None:
		obj = handoff.load_json(FIX / "spark012_b64_tcp_streaming_mb2.example.json")
		obj = copy.deepcopy(obj)
		obj["final_logits_hashes"] = obj["final_logits_hashes"][:1]
		errors = handoff.validate_artifact(obj)
		self.assertTrue(any("final_logits_hashes" in item for item in errors))

	def test_streaming_fixture_cannot_claim_parity_passed(self) -> None:
		obj = handoff.load_json(FIX / "spark012_b64_tcp_streaming_mb2.example.json")
		obj = copy.deepcopy(obj)
		obj["parity_status"] = "passed"
		errors = handoff.validate_artifact(obj)
		self.assertTrue(any("parity_status" in item for item in errors))

	def test_resident_fixture_cannot_claim_production_generation_eligible(self) -> None:
		obj = handoff.load_json(FIX / "spark012_b256_tcp_resident_mb4.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		errors = handoff.validate_artifact(obj)
		self.assertTrue(any("production_generation_eligible" in item for item in errors))

	def test_resident_fixture_records_steady_state_bound(self) -> None:
		obj = handoff.load_json(FIX / "spark012_b512_tcp_resident_mb8.example.json")
		self.assertEqual(obj["slowest_resource_kind"], "stage_compute")
		self.assertEqual(obj["slowest_resource_id"], 0)
		self.assertGreater(obj["steady_state_pipeline_bound_rows_per_s"], obj["achieved_streaming_rows_per_s"])
		self.assertGreater(obj["observed_steady_state_rows_per_s"], 0.0)


if __name__ == "__main__":
	unittest.main()
