import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_interactive_small_batch as smallbatch


FIX = Path("fixtures/interactive_small_batch")


class InteractiveSmallBatchBenchmarkTest(unittest.TestCase):
	def test_interactive_small_batch_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = smallbatch.load_json(path)
				self.assertEqual(smallbatch.validate_artifact(obj), [])

	def test_independent_rows_require_row_count_matching_batch(self) -> None:
		obj = smallbatch.load_json(FIX / "ds4_interactive_b4_independent_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["row_count"] = 1
		errors = smallbatch.validate_artifact(obj)
		self.assertTrue(any("row_count=batch_size" in item for item in errors))

	def test_combined_prompt_control_is_explicit_b1_shape(self) -> None:
		obj = smallbatch.load_json(FIX / "ds4_interactive_b4_combined_prompt_control_20260516.example.json")
		self.assertEqual(obj["prompt_shape"], "single_combined_prompt_control")
		self.assertEqual(obj["batch_size"], 1)
		self.assertEqual(obj["row_count"], 1)
		self.assertEqual(obj["logical_question_count"], 4)

	def test_constrained_output_is_rejected(self) -> None:
		obj = smallbatch.load_json(FIX / "ds4_interactive_b4_independent_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["output_mode"] = "constrained_candidate"
		errors = smallbatch.validate_artifact(obj)
		self.assertTrue(any("output_mode" in item for item in errors))

	def test_successful_small_b_cases_have_committed_tokens(self) -> None:
		for name in ("b4", "b8", "b16"):
			with self.subTest(name=name):
				obj = smallbatch.load_json(FIX / f"ds4_interactive_{name}_independent_20260516.example.json")
				self.assertEqual(obj["blocker_kind"], "none")
				self.assertTrue(obj["finite_output"])
				self.assertTrue(obj["committed_token_ids_present"])
				self.assertTrue(obj["token_hash"].startswith("fnv64:"))
				self.assertGreater(obj["aggregate_output_tokens_per_s"], 0.0)

	def test_blocked_b1_b2_are_recorded_without_speed_claim(self) -> None:
		for name in ("b1", "b2"):
			with self.subTest(name=name):
				obj = smallbatch.load_json(FIX / f"ds4_interactive_{name}_independent_20260516.example.json")
				self.assertNotEqual(obj["blocker_kind"], "none")
				self.assertEqual(obj["aggregate_output_tokens_per_s"], 0.0)
				self.assertEqual(obj["token_hash"], "not_available")

	def test_b4_independent_does_not_approach_four_x_baseline(self) -> None:
		obj = smallbatch.load_json(FIX / "ds4_interactive_b4_independent_20260516.example.json")
		self.assertLess(obj["aggregate_output_tokens_per_s"], 14.65)
		self.assertLess(obj["speedup_vs_b1"], 1.0)


if __name__ == "__main__":
	unittest.main()
