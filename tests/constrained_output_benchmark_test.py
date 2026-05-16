import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_constrained_output_benchmark as bench


FIX = Path("fixtures/constrained_output")


class ConstrainedOutputBenchmarkTest(unittest.TestCase):
	def test_constrained_output_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = bench.load_json(path)
				self.assertEqual(bench.validate_artifact(obj), [])

	def test_numeric_candidate_set_is_explicit(self) -> None:
		obj = bench.load_json(FIX / "ds4_b512_constrained_numeric_hit_1_token_20260516.example.json")
		self.assertEqual(obj["candidate_vocabulary_kind"], "numeric_ids")
		self.assertEqual(obj["candidate_token_count"], 15)
		self.assertGreater(obj["end_to_end_output_tokens_per_s"], 600.0)
		self.assertEqual(obj["token_commit_mode"], "constrained_vocab_cpu_top1")
		self.assertTrue(obj["candidate_token_ids_sha256"].startswith("sha256:"))

	def test_full_vocab_control_is_not_constrained_lane(self) -> None:
		obj = bench.load_json(FIX / "ds4_b512_full_vocab_control_hit_1_token_20260516.example.json")
		self.assertEqual(obj["candidate_vocabulary_kind"], "full_vocab")
		self.assertEqual(obj["candidate_token_count"], 0)
		self.assertEqual(obj["token_commit_mode"], "full_vocab_batch_head")
		self.assertLess(obj["end_to_end_output_tokens_per_s"], 300.0)

	def test_production_gate_rejects_derived_fixture(self) -> None:
		obj = bench.load_json(FIX / "ds4_b512_constrained_numeric_hit_4_token_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["artifact_sha256"] = bench.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = bench.validate_artifact(obj)
		self.assertTrue(any("real shared-prefix hit/fork runtime hook" in item for item in errors))
		self.assertTrue(any("derived measurement_source" in item for item in errors))

	def test_production_gate_rejects_full_vocab_control(self) -> None:
		obj = bench.load_json(FIX / "ds4_b512_full_vocab_control_hit_1_token_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["runtime_hook_status"] = "shared_prefix_hit_fork_runtime"
		obj["artifact_sha256"] = bench.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = bench.validate_artifact(obj)
		self.assertTrue(any("full-vocab control" in item for item in errors))

	def test_production_gate_accepts_real_shared_prefix_hook_shape(self) -> None:
		obj = bench.load_json(FIX / "ds4_b512_constrained_numeric_hit_1_token_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["runtime_hook_status"] = "shared_prefix_hit_fork_runtime"
		obj["production_generation_eligible"] = True
		obj["artifact_sha256"] = bench.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		self.assertEqual(bench.validate_artifact(obj), [])

	def test_parity_flag_mismatch_fails_validation(self) -> None:
		obj = bench.load_json(FIX / "ds4_b512_constrained_numeric_hit_1_token_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["optimized_kernel_flags"]["DS4_CUDA_MOE_SLICE_TILE8"] = "0"
		obj["optimized_kernel_flags_match_parity"] = False
		obj["artifact_sha256"] = bench.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = bench.validate_artifact(obj)
		self.assertTrue(any("optimized_kernel_flags" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
