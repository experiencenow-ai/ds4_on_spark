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


if __name__ == "__main__":
	unittest.main()
