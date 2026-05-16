import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_end_to_end_decode as decode


FIX = Path("fixtures/end_to_end_decode")


class EndToEndDecodeTest(unittest.TestCase):
	def test_end_to_end_decode_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = decode.load_json(path)
				self.assertEqual(decode.validate_artifact(obj), [])

	def test_success_requires_committed_token_hash(self) -> None:
		obj = decode.load_json(FIX / "ds4_b512_decode_only_1_token_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["token_hash"] = ""
		obj["artifact_sha256"] = decode.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = decode.validate_artifact(obj)
		self.assertTrue(any("token_hash" in item for item in errors))

	def test_blocked_shared_prefix_case_cannot_claim_production(self) -> None:
		obj = decode.load_json(FIX / "ds4_b512_shared_prefix_short_suffix_1_token_blocked_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["artifact_sha256"] = decode.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = decode.validate_artifact(obj)
		self.assertTrue(any("production_generation_eligible" in item for item in errors))

	def test_decode_only_success_keeps_prefix_suffix_separate(self) -> None:
		obj = decode.load_json(FIX / "ds4_b512_decode_only_1_token_20260516.example.json")
		self.assertEqual(obj["prompt_pattern"], "decode_only")
		self.assertEqual(obj["prefix_mode"], "no_prefix")
		self.assertEqual(obj["prefix_prepare_ms"], 0.0)
		self.assertEqual(obj["suffix_prefill_ms"], 0.0)
		self.assertEqual(obj["kv_update_mode"], "none")
		self.assertEqual(len(obj["per_step_decode_ms"]), 1)
		self.assertEqual(len(obj["committed_token_ids_by_step"]), 1)
		self.assertEqual(len(obj["token_hashes_by_step"]), 1)
		self.assertGreater(obj["decode_only_rows_per_s"], 15.0)

	def test_constrained_commit_exceeds_600_tok_s(self) -> None:
		obj = decode.load_json(FIX / "ds4_b512_decode_only_1_token_constrained_commit_20260516.example.json")
		self.assertEqual(obj["token_commit_mode"], "constrained_vocab_cpu_top1")
		self.assertGreater(obj["end_to_end_output_tokens_per_s"], 600.0)
		self.assertEqual(obj["production_generation_eligible"], False)

	def test_batch_and_microbatch_are_fixed_for_this_artifact(self) -> None:
		obj = decode.load_json(FIX / "ds4_b512_decode_only_1_token_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["batch_size"] = 1
		obj["artifact_sha256"] = decode.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = decode.validate_artifact(obj)
		self.assertTrue(any("batch_size" in item for item in errors))

	def test_multi_step_success_requires_kv_update_loop(self) -> None:
		obj = decode.load_json(FIX / "ds4_b512_decode_only_1_token_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["output_token_target"] = 4
		obj["decode_steps"] = 4
		obj["per_step_decode_ms"] = [obj["decode_ms"] / 4.0] * 4
		obj["committed_token_ids_by_step"] = [obj["committed_token_ids_by_step"][0]] * 4
		obj["token_hashes_by_step"] = [obj["token_hash"]] * 4
		obj["kv_update_mode"] = "none"
		obj["artifact_sha256"] = decode.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = decode.validate_artifact(obj)
		self.assertTrue(any("kv_update_mode=present" in item for item in errors))

	def test_blocked_short_output_targets_name_exact_missing_loop(self) -> None:
		for name, target in (
			("ds4_b512_shared_prefix_short_suffix_4_token_blocked_20260516.example.json", 4),
			("ds4_b512_shared_prefix_short_suffix_8_token_blocked_20260516.example.json", 8),
		):
			with self.subTest(name=name):
				obj = decode.load_json(FIX / name)
				self.assertEqual(obj["output_token_target"], target)
				self.assertEqual(obj["kv_update_mode"], "blocked")
				self.assertEqual(obj["blocker_kind"], "missing_multi_step_token_commit_kv_loop")


if __name__ == "__main__":
	unittest.main()
