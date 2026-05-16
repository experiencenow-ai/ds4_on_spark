import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import build_ds4_prompt_decode_smoke as smoke


FIX = Path("fixtures/prompt_decode_smoke")


class PromptDecodeSmokeTest(unittest.TestCase):
	def test_prompt_decode_smoke_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = smoke.load_json(path)
				self.assertEqual(smoke.validate_artifact(obj), [])

	def test_blocked_smoke_cannot_claim_production_eligibility(self) -> None:
		obj = smoke.load_json(FIX / "dsv4_b512_slice_tile8_prompt_decode_smoke_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["artifact_sha256"] = smoke.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = smoke.validate_artifact(obj)
		self.assertTrue(any("production_generation_eligible" in item for item in errors))

	def test_committed_token_smoke_requires_token_hash(self) -> None:
		obj = smoke.load_json(FIX / "dsv4_b512_slice_tile8_prompt_decode_smoke_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["token_commit_status"] = "committed"
		obj["committed_token_ids"] = [1]
		obj["token_hash"] = ""
		obj["blocker_kind"] = "none"
		obj["blocker_detail"] = ""
		obj["artifact_sha256"] = smoke.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = smoke.validate_artifact(obj)
		self.assertTrue(any("token_hash" in item for item in errors))

	def test_committed_argmax_artifact_with_passed_parity_can_be_eligible(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			token_path = root / "token.json"
			out_path = root / "smoke.json"
			with redirect_stdout(io.StringIO()):
				self.assertEqual(smoke.main_args_for_test([
					"token-commit-export",
					"--pp1-export", "fixtures/pipeline_outputs/dsv4_slice_tile8_pp1_output_export_20260516.example.json",
					"--run-id", "unit-token-commit",
					"--committed-token-ids", "[42]",
					"--commit-policy", "argmax",
					"--batch-size", "512",
					"--row-count", "512",
					"--out", str(token_path),
				]), 0)
				self.assertEqual(smoke.main_args_for_test([
					"build",
					"--stage-handoff", "fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_slice_tile8.example.json",
					"--pp1-export", "fixtures/pipeline_outputs/dsv4_slice_tile8_pp1_output_export_20260516.example.json",
					"--ppn-export", "fixtures/pipeline_outputs/dsv4_slice_tile8_ppn_output_export_20260516.example.json",
					"--parity-artifact", "fixtures/pipeline_parity/dsv4_slice_tile8_cross_spark_ppn_passed_20260516.example.json",
					"--token-commit-export", str(token_path),
					"--production-generation-eligible",
					"--out", str(out_path),
				]), 0)
			obj = smoke.load_json(out_path)
			self.assertEqual(smoke.validate_artifact(obj), [])
			self.assertEqual(smoke.eligibility_errors(obj), [])
			self.assertTrue(obj["production_generation_eligible"])

	def test_synthetic_parity_cannot_satisfy_eligibility(self) -> None:
		obj = smoke.load_json(FIX / "dsv4_b512_slice_tile8_prompt_decode_smoke_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["token_commit_status"] = "committed"
		obj["committed_token_ids"] = [42]
		obj["token_hash"] = smoke.token_hash([42])
		obj["blocker_kind"] = "none"
		obj["blocker_detail"] = ""
		obj["synthetic_evidence"] = True
		obj["artifact_sha256"] = smoke.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = smoke.validate_artifact(obj)
		self.assertTrue(any("synthetic-only" in item for item in errors))

	def test_optimized_kernel_flags_must_match_parity(self) -> None:
		obj = smoke.load_json(FIX / "dsv4_b512_slice_tile8_prompt_decode_smoke_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["token_commit_status"] = "committed"
		obj["committed_token_ids"] = [42]
		obj["token_hash"] = smoke.token_hash([42])
		obj["blocker_kind"] = "none"
		obj["blocker_detail"] = ""
		obj["optimized_kernel_flags"] = {"DS4_CUDA_MOE_SLICE_TILE8": "0"}
		obj["artifact_sha256"] = smoke.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = smoke.validate_artifact(obj)
		self.assertTrue(any("optimized kernel flags" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
