import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_constrained_candidate_sweep as sweep


FIX = Path("fixtures/constrained_candidate_sweep")
MAIN_FIXTURE = FIX / "ds4_constrained_candidate_sweep_20260516.example.json"


class ConstrainedCandidateSweepTest(unittest.TestCase):
	def test_constrained_candidate_sweep_fixture_validates(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = sweep.load_json(path)
				self.assertEqual(sweep.validate_artifact(obj), [])

	def test_thresholds_include_runtime_enforced_2048_candidates(self) -> None:
		obj = sweep.load_json(MAIN_FIXTURE)
		self.assertEqual(obj["largest_candidate_token_count_above_600_tok_s"], 2048)
		self.assertEqual(obj["largest_candidate_token_count_above_500_tok_s"], 2048)
		self.assertIsNone(obj["first_candidate_token_count_below_500_tok_s"])
		self.assertIsNone(obj["first_unproven_candidate_token_count"])
		self.assertEqual(obj["regression_component"], "not_observed")

	def test_512_plus_candidate_sets_are_runtime_enforced(self) -> None:
		obj = sweep.load_json(MAIN_FIXTURE)
		rows = {
			int(row["candidate_token_count"]): row
			for row in obj["sweep_results"]
			if row["candidate_vocabulary_kind"] != "full_vocab_control"
		}
		for count in (512, 1024, 2048):
			row = rows[count]
			self.assertEqual(row["blocker_kind"], "none")
			self.assertEqual(row["runtime_requested_candidate_token_count"], count)
			self.assertEqual(row["runtime_enforced_candidate_token_count"], count)
			self.assertEqual(row["runtime_reported_candidate_token_count"], count)
			self.assertTrue(row["candidate_set_fully_reported"])
			self.assertGreater(row["end_to_end_output_tokens_per_s"], 600.0)

	def test_full_vocab_control_stays_separate_and_slow(self) -> None:
		obj = sweep.load_json(MAIN_FIXTURE)
		control = [row for row in obj["sweep_results"] if row["candidate_vocabulary_kind"] == "full_vocab_control"]
		self.assertEqual(len(control), 1)
		self.assertTrue(control[0]["fallback_full_vocab_used"])
		self.assertEqual(control[0]["candidate_token_count"], 0)
		self.assertLess(control[0]["end_to_end_output_tokens_per_s"], 300.0)

	def test_production_eligibility_is_rejected_for_sweep(self) -> None:
		obj = sweep.load_json(MAIN_FIXTURE)
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["artifact_sha256"] = sweep.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = sweep.validate_artifact(obj)
		self.assertTrue(any("production_generation_eligible" in item for item in errors))

	def test_bad_threshold_fails_validation(self) -> None:
		obj = sweep.load_json(MAIN_FIXTURE)
		obj = copy.deepcopy(obj)
		obj["largest_candidate_token_count_above_600_tok_s"] = 256
		obj["artifact_sha256"] = sweep.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = sweep.validate_artifact(obj)
		self.assertTrue(any("largest_candidate_token_count_above_600" in item for item in errors))

	def test_hash_mismatch_fails_validation(self) -> None:
		obj = sweep.load_json(MAIN_FIXTURE)
		obj = copy.deepcopy(obj)
		obj["run_id"] = "tampered"
		errors = sweep.validate_artifact(obj)
		self.assertTrue(any("artifact_sha256" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
