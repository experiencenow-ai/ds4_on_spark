import copy
import tempfile
import unittest
from pathlib import Path

from scripts import build_ds4_mtp_k2_production_benchmark as build
from scripts import validate_ds4_mtp_k2_production_benchmark as validate


FIX = Path("fixtures/mtp_k2_production")

BASE_LOG = """\
ds4: mtp bench phase=session_baseline command_sha256=abc prompt_sha256=def n_predict=126 mtp_draft=2 ctx=4096 seed=1234 spec_disabled=1 prompt_shape=short_instruction
ds4: prefill: 7.00 t/s, generation: 11.02 t/s
ds4: mtp bench phase=session_baseline external_wall_s=12.0 exit_code=0 n_predict=126 mtp_draft=2 ctx=4096 seed=1234 spec_disabled=1
"""

MTP_LOG = """\
ds4: mtp bench phase=mtp_draft2 command_sha256=abc prompt_sha256=def n_predict=126 mtp_draft=2 ctx=4096 seed=1234 spec_disabled=0 prompt_shape=short_instruction
ds4: mtp timing suffix2 drafted=84 committed=84 first_eval=0.000 ms draft=1.000 ms snapshot=0.000 ms verify=1.000 ms target=1.000 ms head=0.000 ms verifier_calls=42 target_positions=126 target_calls=42 head_calls=42 head_rows=126 full_vocab_rows=42 top1_rows=84 draft_calls=84 replay_calls=0 rewind_calls=0 cache_sync_calls=0 cuda_sync_calls=0 emitted=126 total=2.000 ms
ds4: prefill: 7.00 t/s, generation: 20.55 t/s
ds4: mtp bench phase=mtp_draft2 external_wall_s=7.0 exit_code=0 n_predict=126 mtp_draft=2 ctx=4096 seed=1234 spec_disabled=0
"""


class MtpK2ProductionBenchmarkTest(unittest.TestCase):
	def test_mtp_k2_production_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				self.assertEqual(validate.validate_artifact(validate.load_json(path)), [])

	def test_pr1125_fixture_records_matched_speedup(self) -> None:
		obj = validate.load_json(FIX / "pr1125_n126_short_instruction_stdout.example.json")
		self.assertAlmostEqual(obj["speedup_vs_baseline"], 20.55 / 11.02)
		self.assertAlmostEqual(obj["accept_rate"], 1.0)
		self.assertEqual(obj["target_next_mismatch_events"], 0)
		self.assertEqual(obj["target_positions_per_invocation"], 3.0)
		self.assertFalse(obj["production_eligible"])
		self.assertIn("benchmark_matrix_not_complete", obj["production_blockers"])

	def test_tail_case_must_match_n_predict_modulo(self) -> None:
		obj = copy.deepcopy(validate.load_json(FIX / "tail_n127_short_instruction_not_run.example.json"))
		obj["tail_case"] = "n_predict_mod_3_0"
		errors = validate.validate_artifact(obj)
		self.assertTrue(any("tail_case must be n_predict_mod_3_1" in error for error in errors))

	def test_production_eligible_requires_tail_and_matrix_pass(self) -> None:
		obj = copy.deepcopy(validate.load_json(FIX / "tail_n128_short_instruction_not_run.example.json"))
		obj["production_eligible"] = True
		obj["blocker_kind"] = "none"
		obj["benchmark_matrix_status"] = "passed"
		errors = validate.validate_artifact(obj)
		self.assertTrue(any("tail_acceptance_status=passed" in error for error in errors))

	def test_production_eligible_rejects_mismatch(self) -> None:
		obj = copy.deepcopy(validate.load_json(FIX / "pr1125_n126_short_instruction_stdout.example.json"))
		obj["production_eligible"] = True
		obj["benchmark_matrix_status"] = "passed"
		obj["production_blockers"] = []
		obj["target_next_mismatch_events"] = 1
		errors = validate.validate_artifact(obj)
		self.assertTrue(any("target_next_mismatch_events=0" in error for error in errors))

	def test_builder_extracts_pr1125_shape_metrics(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			base = Path(td) / "base.log"
			mtp = Path(td) / "mtp.log"
			base.write_text(BASE_LOG, encoding="utf-8")
			mtp.write_text(MTP_LOG, encoding="utf-8")
			obj = build.build_artifact(
				[base],
				[mtp],
				run_id="run",
				model_id="model",
				runtime_id="runtime",
				quantization_id="quant",
				prompt_id="short_instruction",
				prompt="prompt",
				prompt_hash="sha256:abc",
				n_predict=126,
				stdout_suppressed=False,
				suppress_output_mode="stdout",
				tail_acceptance_status="passed",
				benchmark_matrix_status="not_complete",
			)
		self.assertEqual(validate.validate_artifact(obj), [])
		self.assertEqual(obj["accepted_draft_tokens"], 84)
		self.assertEqual(obj["attempted_draft_tokens"], 84)
		self.assertEqual(obj["verifier_invocation_count"], 42)
		self.assertEqual(obj["full_vocab_logits_rows"], 42)
		self.assertEqual(obj["top1_only_rows"], 84)
		self.assertEqual(obj["tail_case"], "n_predict_mod_3_0")


if __name__ == "__main__":
	unittest.main()
