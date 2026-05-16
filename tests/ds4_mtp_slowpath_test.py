import unittest

from scripts import build_ds4_mtp_slowpath_report as build
from scripts import extract_antirez_ds4_mtp_conf_log as extract
from scripts import validate_ds4_mtp_slowpath as validate


class Ds4MtpSlowpathTest(unittest.TestCase):
	def test_extracts_timing_components(self) -> None:
		lines = [
			"ds4: mtp timing micro drafted=2 committed=2 draft=3.000 ms snapshot=1.000 ms verify=20.000 ms total=25.000 ms\n",
			"ds4: mtp timing micro drafted=2 committed=1 draft=2.000 ms snapshot=0.500 ms verify=8.000 ms replay=30.000 ms total=41.000 ms\n",
		]
		res = extract.extract_events(lines)
		timing = res.get("timing") or {}
		components = timing.get("per_component_ms") or {}
		self.assertEqual(int(timing.get("events")), 2)
		self.assertAlmostEqual(float(components.get("draft_eval_ms")), 5.0)
		self.assertAlmostEqual(float(components.get("target_eval_ms")), 28.0)
		self.assertAlmostEqual(float(components.get("output_head_ms")), 0.0)
		self.assertAlmostEqual(float(components.get("verifier_replay_ms")), 30.0)
		self.assertAlmostEqual(float(components.get("scheduler_overhead_ms")), 1.5)
		self.assertEqual(timing.get("slowest_component"), "verifier_replay_ms")
		counts = timing.get("call_counts") or {}
		self.assertEqual(counts.get("target_eval_call_count"), 2)
		self.assertEqual(counts.get("output_head_call_count"), 2)
		self.assertEqual(counts.get("verifier_replay_count"), 1)
		self.assertEqual(timing.get("emitted_tokens"), 5)

	def test_extracts_decode2_decomposition(self) -> None:
		lines = [
			"ds4: mtp timing decode2 drafted=2 committed=2 draft=3.000 ms snapshot=1.000 ms verify=20.000 ms target=12.000 ms head=6.000 ms target_calls=2 head_calls=2 draft_calls=1 replay_calls=0 rewind_calls=0 cache_sync_calls=0 cuda_sync_calls=0 emitted=3 total=25.000 ms\n",
		]
		res = extract.extract_events(lines)
		timing = res.get("timing") or {}
		components = timing.get("per_component_ms") or {}
		counts = timing.get("call_counts") or {}
		self.assertAlmostEqual(float(timing.get("verifier_ms")), 20.0)
		self.assertAlmostEqual(float(components.get("target_eval_ms")), 12.0)
		self.assertAlmostEqual(float(components.get("output_head_ms")), 6.0)
		self.assertEqual(counts.get("target_eval_call_count"), 2)
		self.assertEqual(counts.get("draft_eval_call_count"), 1)
		self.assertEqual(counts.get("output_head_call_count"), 2)
		self.assertEqual(counts.get("cuda_sync_count"), 0)
		self.assertEqual(timing.get("emitted_tokens"), 3)

	def test_builds_and_validates_slowpath_report(self) -> None:
		lines = [
			"ds4: mtp conf drafted=2 committed=2 mtp_top=7 runner=8 margin=1.000000 target_next=7 draft_next=7\n",
			"ds4: mtp timing decode2 drafted=2 committed=2 draft=3.000 ms snapshot=1.000 ms verify=20.000 ms target=12.000 ms head=6.000 ms target_calls=2 head_calls=2 draft_calls=1 replay_calls=0 rewind_calls=0 cache_sync_calls=0 cuda_sync_calls=0 emitted=3 total=25.000 ms\n",
			"ds4: prefill: 2.18 t/s, generation: 1.38 t/s\n",
		]
		report = build.build_report_from_lines(
			lines,
			run_id="test-run",
			model_id="test-model",
			runtime_id="test-runtime",
			prompt="Explain Redis streams.",
			prompt_hash="",
			mtp_draft=2,
			mtp_margin=0.0,
			baseline_generation_tps=15.07,
		)
		self.assertEqual(report.get("format"), "ds4-mtp-slowpath-v1")
		self.assertEqual(report.get("accepted_tokens"), 2)
		self.assertEqual(report.get("attempted_draft_tokens"), 2)
		self.assertEqual(report.get("draft_tokens_accepted"), 2)
		self.assertEqual(report.get("draft_tokens_attempted"), 2)
		self.assertAlmostEqual(float(report.get("accept_rate")), 1.0)
		self.assertAlmostEqual(float(report.get("speedup_vs_baseline")), 1.38 / 15.07)
		self.assertEqual(report.get("target_next_mismatch_count"), 0)
		self.assertEqual(report.get("target_next_mismatch_events"), 0)
		self.assertAlmostEqual(float(report.get("verifier_ms")), 20.0)
		self.assertAlmostEqual(float(report.get("output_head_ms")), 6.0)
		self.assertAlmostEqual(float(report.get("logging_capture_ms")), 1.0)
		self.assertAlmostEqual(float(report.get("scheduler_overhead_ms")), 1.0)
		self.assertEqual(report.get("target_eval_call_count"), 2)
		self.assertEqual(report.get("draft_eval_call_count"), 1)
		self.assertEqual(report.get("output_head_call_count"), 2)
		self.assertEqual(report.get("verifier_replay_count"), 0)
		self.assertEqual(report.get("cache_rewind_count"), 0)
		self.assertEqual(report.get("cache_sync_count"), 0)
		self.assertEqual(report.get("cuda_sync_count"), 0)
		self.assertEqual(report.get("emitted_tokens"), 3)
		self.assertAlmostEqual(float(report.get("target_eval_ms_per_emitted_token")), 4.0)
		self.assertAlmostEqual(float(report.get("target_eval_ms_per_accepted_draft_token")), 6.0)
		self.assertEqual(report.get("slowest_component"), "target_eval_ms")
		self.assertEqual(report.get("blocker_kind"), "target_verifier_overhead")
		self.assertTrue(validate.validate_report(report).get("ok"))

	def _valid_report(self) -> dict[str, object]:
		report: dict[str, object] = {
			"format": "ds4-mtp-slowpath-v1",
			"run_id": "r",
			"model_id": "m",
			"runtime_id": "rt",
			"prompt_hash": "h",
			"mtp_draft": 2,
			"mtp_margin": 0.0,
			"accepted_tokens": 1,
			"attempted_draft_tokens": 2,
			"draft_tokens_accepted": 1,
			"draft_tokens_attempted": 2,
			"accept_rate": 0.5,
			"baseline_generation_tps": 10.0,
			"mtp_generation_tps": 9.0,
			"speedup_vs_baseline": 0.9,
			"target_next_mismatch_count": 0,
			"target_next_mismatch_events": 0,
			"slowest_component": "target_eval_ms",
			"per_component_ms": {k: 0.0 for k in validate.COMPONENT_FIELDS},
			"verifier_ms": 0.0,
			"logging_capture_ms": 0.0,
			"target_eval_call_count": 1,
			"draft_eval_call_count": 1,
			"output_head_call_count": 1,
			"verifier_replay_count": 0,
			"cache_rewind_count": 0,
			"cache_sync_count": 0,
			"cuda_sync_count": 0,
			"emitted_tokens": 1,
			"target_eval_ms_per_emitted_token": 0.0,
			"target_eval_ms_per_accepted_draft_token": 0.0,
			"blocker_kind": "target_verifier_overhead",
			"blocker_detail": "slow",
		}
		for k in validate.COMPONENT_FIELDS:
			report[k] = 0.0
		return report

	def test_validator_rejects_invalid_speedup_claim(self) -> None:
		report = self._valid_report()
		report["speedup_vs_baseline"] = 1.2
		res = validate.validate_report(report)
		self.assertFalse(bool(res.get("ok")))
		self.assertTrue(any("speedup_vs_baseline > 1" in e for e in res.get("errors", [])))

	def test_validator_rejects_accept_rate_without_counts(self) -> None:
		report = self._valid_report()
		report["draft_tokens_accepted"] = 0
		report["draft_tokens_attempted"] = 0
		res = validate.validate_report(report)
		self.assertFalse(bool(res.get("ok")))
		self.assertTrue(any("draft_tokens_attempted > 0" in e for e in res.get("errors", [])))

	def test_validator_rejects_slower_mtp_without_blocker(self) -> None:
		report = self._valid_report()
		report["mtp_generation_tps"] = 5.0
		report["speedup_vs_baseline"] = 0.5
		report["blocker_kind"] = "none"
		report["blocker_detail"] = ""
		res = validate.validate_report(report)
		self.assertFalse(bool(res.get("ok")))
		self.assertTrue(any("requires blocker_kind" in e for e in res.get("errors", [])))

	def test_validator_rejects_missing_target_next_mismatch_events(self) -> None:
		report = self._valid_report()
		report.pop("target_next_mismatch_events")
		res = validate.validate_report(report)
		self.assertFalse(bool(res.get("ok")))
		self.assertTrue(any("target_next_mismatch_events" in e for e in res.get("errors", [])))

	def test_validator_rejects_missing_verifier_call_counts(self) -> None:
		for field in ("target_eval_call_count", "output_head_call_count"):
			with self.subTest(field=field):
				report = self._valid_report()
				report.pop(field)
				res = validate.validate_report(report)
				self.assertFalse(bool(res.get("ok")))
				self.assertTrue(any(field in e for e in res.get("errors", [])))


if __name__ == "__main__":
	unittest.main()
