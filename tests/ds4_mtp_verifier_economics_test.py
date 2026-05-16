import unittest
from pathlib import Path

from scripts import build_ds4_mtp_verifier_economics as build
from scripts import validate_ds4_mtp_verifier_economics as validate

FIX = Path("fixtures/mtp")


class Ds4MtpVerifierEconomicsTest(unittest.TestCase):
	def test_verifier_economics_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*verifier_economics*.json")):
			with self.subTest(path=path.name):
				import json
				obj = json.loads(path.read_text(encoding="utf-8"))
				self.assertTrue(validate.validate_report(obj)["ok"])

	def test_builds_decode2_economics(self) -> None:
		lines = [
			"ds4: mtp conf drafted=2 committed=2 mtp_top=7 runner=8 margin=1.000000 target_next=7 draft_next=7\n",
			"ds4: mtp timing decode2 drafted=2 committed=2 draft=3.000 ms snapshot=1.000 ms verify=20.000 ms target=12.000 ms head=6.000 ms target_calls=2 head_calls=2 draft_calls=1 replay_calls=0 rewind_calls=0 cache_sync_calls=0 cuda_sync_calls=0 emitted=3 total=25.000 ms\n",
			"ds4: prefill: 2.18 t/s, generation: 2.00 t/s\n",
		]
		report = build.build_report_from_lines(
			lines,
			run_id="r",
			model_id="m",
			runtime_id="rt",
			prompt="p",
			prompt_hash="",
			baseline_tps=14.65,
			mtp_tps=None,
		)
		self.assertEqual(report["format"], "ds4-mtp-verifier-economics-v1")
		self.assertEqual(report["accepted_draft_tokens"], 2)
		self.assertEqual(report["attempted_draft_tokens"], 2)
		self.assertAlmostEqual(float(report["accept_rate"]), 1.0)
		self.assertEqual(report["target_verifier_invocation_count"], 1)
		self.assertEqual(report["target_positions_verified"], 2)
		self.assertAlmostEqual(float(report["target_positions_per_invocation"]), 2.0)
		self.assertEqual(report["output_head_invocation_count"], 2)
		self.assertEqual(report["output_head_rows"], 2)
		self.assertEqual(report["full_vocab_logits_rows"], 1)
		self.assertEqual(report["top1_only_rows"], 1)
		self.assertEqual(report["blocker_kind"], "target_output_head_token_for_token")
		self.assertTrue(validate.validate_report(report)["ok"])

	def test_fused_head_economics_reduce_output_head_invocations(self) -> None:
		lines = [
			"ds4: mtp conf drafted=2 committed=2 mtp_top=7 runner=8 margin=1.000000 target_next=7 draft_next=7\n",
			"ds4: mtp timing decode2 drafted=2 committed=2 draft=3.000 ms snapshot=1.000 ms verify=19.000 ms target=12.000 ms head=3.000 ms target_calls=2 head_calls=1 head_rows=2 full_vocab_rows=1 top1_rows=1 draft_calls=1 replay_calls=0 rewind_calls=0 cache_sync_calls=0 cuda_sync_calls=0 emitted=3 total=22.000 ms\n",
			"ds4: prefill: 2.18 t/s, generation: 2.30 t/s\n",
		]
		report = build.build_report_from_lines(
			lines,
			run_id="r",
			model_id="m",
			runtime_id="rt",
			prompt="p",
			prompt_hash="",
			baseline_tps=14.65,
			mtp_tps=None,
		)
		report["target_suffix_verifier_implemented"] = True
		report["target_suffix_verifier_delegates_to_serial_decode"] = True
		report["staged_kv_ready"] = False
		report["true_suffix_blocker"] = "target_suffix_verify_k2 delegates to serial target decode"
		report["exact_next_code_change"] = "replace delegate with one batched K=2 target suffix graph"
		self.assertEqual(report["output_head_invocation_count"], 1)
		self.assertEqual(report["output_head_rows"], 2)
		self.assertEqual(report["full_vocab_logits_rows"], 1)
		self.assertEqual(report["top1_only_rows"], 1)
		self.assertEqual(report["blocker_kind"], "target_verifier_overhead")
		self.assertTrue(validate.validate_report(report)["ok"])

	def test_true_suffix_log_tracks_invocations_vs_positions(self) -> None:
		lines = [
			"ds4: mtp conf drafted=2 committed=2 mtp_top=7 runner=8 margin=1.000000 target_next=7 draft_next=7\n",
			"ds4: mtp timing suffix2 drafted=2 committed=2 draft=3.000 ms snapshot=1.000 ms verify=9.000 ms target=6.000 ms head=2.000 ms verifier_calls=1 target_positions=2 target_calls=1 head_calls=1 head_rows=2 full_vocab_rows=1 top1_rows=1 draft_calls=1 replay_calls=0 rewind_calls=0 cache_sync_calls=0 cuda_sync_calls=0 emitted=3 total=13.000 ms\n",
			"ds4: prefill: 2.18 t/s, generation: 16.00 t/s\n",
		]
		report = build.build_report_from_lines(
			lines,
			run_id="r",
			model_id="m",
			runtime_id="rt",
			prompt="p",
			prompt_hash="",
			baseline_tps=14.65,
			mtp_tps=None,
		)
		self.assertEqual(report["target_verifier_invocation_count"], 1)
		self.assertEqual(report["target_positions_verified"], 2)
		self.assertAlmostEqual(float(report["target_positions_per_invocation"]), 2.0)
		self.assertEqual(report["output_head_invocation_count"], 1)
		self.assertEqual(report["blocker_kind"], "none")
		self.assertTrue(validate.validate_report(report)["ok"])

	def test_target_suffix_blocker_requires_explicit_staging_fields(self) -> None:
		report = {
			"format": "ds4-mtp-verifier-economics-v1",
			"baseline_tps": 10.0,
			"mtp_tps": 5.0,
			"speedup_vs_baseline": 0.5,
			"accepted_draft_tokens": 2,
			"attempted_draft_tokens": 2,
			"accept_rate": 1.0,
			"emitted_tokens": 3,
			"target_verifier_invocation_count": 1,
			"target_positions_verified": 2,
			"target_positions_per_invocation": 2.0,
			"target_eval_ms": 10.0,
			"target_eval_ms_per_invocation": 10.0,
			"target_eval_ms_per_verified_position": 5.0,
			"output_head_invocation_count": 1,
			"output_head_rows": 2,
			"full_vocab_logits_rows": 1,
			"top1_only_rows": 1,
			"draft_eval_ms": 1.0,
			"snapshot_ms": 0.0,
			"kv_commit_ms": 0.0,
			"kv_restore_ms": 0.0,
			"logits_readback_ms": 0.0,
			"token_commit_ms": 0.0,
			"slowest_component": "target_eval_ms",
			"blocker_kind": "target_suffix_verifier_still_serial",
			"blocker_detail": "slow",
		}
		res = validate.validate_report(report)
		self.assertFalse(res["ok"])
		self.assertTrue(any("staged_kv_ready" in e for e in res["errors"]))

	def test_validator_rejects_bad_speedup(self) -> None:
		report = {
			"format": "ds4-mtp-verifier-economics-v1",
			"baseline_tps": 10.0,
			"mtp_tps": 5.0,
			"speedup_vs_baseline": 2.0,
			"accepted_draft_tokens": 1,
			"attempted_draft_tokens": 2,
			"accept_rate": 0.5,
			"emitted_tokens": 1,
			"target_verifier_invocation_count": 1,
			"target_positions_verified": 1,
			"target_positions_per_invocation": 1.0,
			"target_eval_ms": 1.0,
			"target_eval_ms_per_invocation": 1.0,
			"target_eval_ms_per_verified_position": 1.0,
			"output_head_invocation_count": 1,
			"output_head_rows": 1,
			"full_vocab_logits_rows": 1,
			"top1_only_rows": 0,
			"draft_eval_ms": 0.0,
			"snapshot_ms": 0.0,
			"kv_commit_ms": 0.0,
			"kv_restore_ms": 0.0,
			"logits_readback_ms": 0.0,
			"token_commit_ms": 0.0,
			"slowest_component": "target_eval_ms",
			"blocker_kind": "target_output_head_token_for_token",
			"blocker_detail": "slow",
		}
		res = validate.validate_report(report)
		self.assertFalse(res["ok"])
		self.assertTrue(any("speedup_vs_baseline" in e for e in res["errors"]))


if __name__ == "__main__":
	unittest.main()
