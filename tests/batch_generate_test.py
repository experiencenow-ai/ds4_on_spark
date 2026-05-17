import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_batch_generate as batch


FIX = Path("fixtures/batch_generate")


class BatchGenerateTest(unittest.TestCase):
	def test_batch_generate_fixtures_validate(self) -> None:
		objs = [batch.load_json(path) for path in sorted(FIX.glob("*.json"))]
		for obj, errors in batch.validate_documents(objs):
			with self.subTest(request_id=obj.get("request_id"), fmt=obj.get("format")):
				self.assertEqual(errors, [])

	def test_constrained_result_tokens_are_inside_candidate_set(self) -> None:
		request = batch.load_json(FIX / "b512_constrained_numeric_request.example.json")
		result = batch.load_json(FIX / "b512_constrained_numeric_result.example.json")
		self.assertEqual(batch.validate_result(result, request), [])
		request_rows = {row["row_id"]: set(row["candidate_token_ids"]) for row in request["rows"]}
		for row in result["rows"]:
			self.assertTrue(set(row["committed_token_ids"]).issubset(request_rows[row["row_id"]]))

	def test_full_vocab_result_uses_full_vocab_path(self) -> None:
		result = batch.load_json(FIX / "b512_full_vocab_result.example.json")
		groups = result["telemetry"]["output_mode_groups"]
		self.assertEqual(groups[0]["output_mode"], "full_vocab")
		self.assertEqual(groups[0]["selected_rate_source"], "full_vocab_output_head")
		self.assertGreater(result["telemetry"]["full_vocab_commit_ms"], 0.0)
		self.assertEqual(result["telemetry"]["constrained_commit_ms"], 0.0)

	def test_mixed_output_modes_split_internally(self) -> None:
		result = batch.load_json(FIX / "mixed_output_modes_result.example.json")
		groups = {group["output_mode"]: group for group in result["telemetry"]["output_mode_groups"]}
		self.assertEqual(groups["constrained_candidate"]["row_count"], 384)
		self.assertEqual(groups["full_vocab"]["row_count"], 96)
		self.assertEqual(groups["grammar_constrained"]["row_count"], 32)
		self.assertEqual(groups["full_vocab"]["selected_rate_source"], "full_vocab_output_head")
		self.assertEqual(groups["constrained_candidate"]["selected_rate_source"], "constrained_candidate_commit")

	def test_max_output_tokens_supports_more_than_eight(self) -> None:
		request = batch.load_json(FIX / "variable_max_output_tokens_request.example.json")
		result = batch.load_json(FIX / "variable_max_output_tokens_result.example.json")
		row_by_id = {row["row_id"]: row for row in result["rows"]}
		long_rows = [row for row in request["rows"] if row["max_output_tokens"] == 32]
		self.assertEqual(len(long_rows), 128)
		self.assertEqual(len(row_by_id[long_rows[0]["row_id"]]["committed_token_ids"]), 32)

	def test_missing_token_hash_blocks_production_eligibility(self) -> None:
		request = batch.load_json(FIX / "b512_constrained_numeric_request.example.json")
		result = copy.deepcopy(batch.load_json(FIX / "b512_constrained_numeric_result.example.json"))
		result["telemetry"]["production_generation_eligible"] = True
		result["telemetry"]["derived_artifact"] = False
		result["telemetry"]["parity_status"] = "passed"
		result["telemetry"]["parity_artifact_sha256"] = "sha256:" + "a" * 64
		result["telemetry"]["shared_prefix_suffix_runtime_used"] = True
		result["telemetry"]["blocker_kind"] = "none"
		result["telemetry"]["blocker_detail"] = ""
		result["rows"][0]["token_hash"] = ""
		errors = batch.validate_result(result, request)
		self.assertTrue(any("token_hash" in error for error in errors))

	def test_finite_logits_only_cannot_be_production_eligible(self) -> None:
		request = batch.load_json(FIX / "b512_constrained_numeric_request.example.json")
		request = copy.deepcopy(request)
		request["request_id"] = "req_finite_logits_only"
		request["batch_policy"]["target_active_rows"] = 1
		request["rows"] = [copy.deepcopy(request["rows"][0])]
		request["rows"][0]["output_mode"] = "finite_logits_only"
		request["rows"][0].pop("candidate_token_ids", None)
		result = batch.build_result_from_request(request)
		result["telemetry"]["production_generation_eligible"] = True
		result["telemetry"]["derived_artifact"] = False
		result["telemetry"]["parity_status"] = "passed"
		result["telemetry"]["parity_artifact_sha256"] = "sha256:" + "b" * 64
		result["telemetry"]["shared_prefix_suffix_runtime_used"] = True
		result["telemetry"]["blocker_kind"] = "none"
		result["telemetry"]["blocker_detail"] = ""
		errors = batch.validate_result(result, request)
		self.assertTrue(any("finite_logits_only" in error for error in errors))

	def test_one_giant_prompt_is_not_b512(self) -> None:
		request = batch.load_json(FIX / "b512_full_vocab_request.example.json")
		request = copy.deepcopy(request)
		request["request_id"] = "req_one_giant_prompt"
		request["rows"] = [request["rows"][0]]
		request["rows"][0]["suffix_token_ids"] = list(range(512))
		result = batch.build_result_from_request(request)
		self.assertEqual(result["telemetry"]["batch_size"], 1)
		self.assertEqual(result["telemetry"]["active_rows"], 1)
		self.assertNotEqual(result["telemetry"]["batch_size"], request["batch_policy"]["target_active_rows"])

	def test_fixed_spark_count_field_fails(self) -> None:
		request = copy.deepcopy(batch.load_json(FIX / "b512_constrained_numeric_request.example.json"))
		request["world_size"] = 3
		errors = batch.validate_request(request)
		self.assertTrue(any("fixed Spark count" in error for error in errors))

	def test_live_smoke_prefix_kv_required_blocks_with_exact_hook(self) -> None:
		request = batch.load_json(FIX / "live_smoke_b512_constrained_1tok_request.example.json")
		result = batch.load_json(FIX / "live_smoke_b512_constrained_1tok_result.example.json")
		self.assertEqual(batch.validate_result(result, request), [])
		self.assertEqual(result["status"], "blocked")
		self.assertEqual(result["telemetry"]["blocker_kind"], "missing_prefix_kv_runtime_hook")
		self.assertFalse(result["telemetry"]["production_generation_eligible"])

	def test_live_smoke_mixed_modes_split_when_blocked(self) -> None:
		result = batch.load_json(FIX / "live_smoke_mixed_output_modes_result.example.json")
		groups = {group["output_mode"]: group for group in result["telemetry"]["output_mode_groups"]}
		self.assertEqual(groups["constrained_candidate"]["row_count"], 384)
		self.assertEqual(groups["full_vocab"]["row_count"], 128)

	def test_live_smoke_multi_prefix_groups_are_not_rejected(self) -> None:
		result = batch.load_json(FIX / "live_smoke_multi_prefix_constrained_result.example.json")
		groups = {group["prefix_handle"]: group["row_count"] for group in result["telemetry"]["prefix_handle_groups"]}
		self.assertEqual(groups["prefix:repo-skeleton:v1"], 256)
		self.assertEqual(groups["prefix:repo-skeleton-alt:v1"], 256)


if __name__ == "__main__":
	unittest.main()
