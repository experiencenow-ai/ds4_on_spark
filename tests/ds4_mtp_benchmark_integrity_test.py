import tempfile
import unittest
from pathlib import Path

from scripts import build_ds4_mtp_benchmark_integrity as build
from scripts import extract_antirez_ds4_mtp_conf_log as extract
from scripts import validate_ds4_mtp_benchmark_integrity as validate


BASE_LOG = """\
ds4: mtp bench phase=session_baseline command_sha256=abc prompt_sha256=def perf_env_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa perf_env_keys=DS4_MTP_TIMING,DS4_MTP_CONF_LOG n_predict=32 mtp_draft=2 ctx=2048 seed=1234 spec_disabled=1
ds4: prefill: 7.00 t/s, generation: 2.20 t/s
ds4: mtp bench phase=session_baseline perf_env_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa external_wall_s=70.000000 exit_code=0 n_predict=32 mtp_draft=2 ctx=2048 seed=1234 spec_disabled=1
"""

MTP_LOG = """\
ds4: mtp bench phase=mtp_draft2 command_sha256=abc prompt_sha256=def perf_env_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa perf_env_keys=DS4_MTP_TIMING,DS4_MTP_CONF_LOG n_predict=32 mtp_draft=2 ctx=2048 seed=1234 spec_disabled=0
ds4: mtp conf drafted=2 committed=2 mtp_top=7 runner=8 margin=1.000000 target_next=7 draft_next=7
ds4: mtp timing suffix2 drafted=2 committed=2 first_eval=1400.000 ms draft=20.000 ms snapshot=0.000 ms verify=120.000 ms target=120.000 ms head=0.000 ms verifier_calls=2 target_positions=3 target_calls=2 head_calls=2 head_rows=3 full_vocab_rows=3 top1_rows=0 draft_calls=1 replay_calls=0 rewind_calls=0 cache_sync_calls=0 cuda_sync_calls=0 emitted=3 total=1540.000 ms
ds4: prefill: 7.00 t/s, generation: 2.00 t/s
ds4: mtp bench phase=mtp_draft2 perf_env_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa external_wall_s=71.000000 exit_code=0 n_predict=32 mtp_draft=2 ctx=2048 seed=1234 spec_disabled=0
"""


class Ds4MtpBenchmarkIntegrityTest(unittest.TestCase):
	def test_extracts_bench_events_and_first_eval(self) -> None:
		obj = extract.extract_events(MTP_LOG.splitlines())
		self.assertEqual((obj.get("benchmark") or {}).get("external_wall_s"), 71.0)
		self.assertEqual((obj.get("benchmark") or {}).get("spec_disabled"), 0)
		timing = obj.get("timing") or {}
		components = timing.get("per_component_ms") or {}
		counts = timing.get("call_counts") or {}
		self.assertAlmostEqual(float(components.get("target_eval_ms")), 1520.0)
		self.assertEqual(int(counts.get("target_eval_call_count")), 2)
		self.assertEqual(int(counts.get("target_positions_verified")), 3)

	def test_builds_comparable_session_baseline_report(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			base = Path(td) / "base.log"
			mtp = Path(td) / "mtp.log"
			base.write_text(BASE_LOG, encoding="utf-8")
			mtp.write_text(MTP_LOG, encoding="utf-8")
			report = build.build_report(
				[base],
				[mtp],
				run_id="r",
				model_id="m",
				runtime_id="rt",
				prompt="",
				prompt_hash="def",
				prior_argmax_baseline_tps=14.65,
			)
		self.assertEqual(report["benchmark_status"], "comparable")
		self.assertTrue(report["same_cli_path"])
		self.assertTrue(report["same_perf_env"])
		self.assertTrue(report["baseline_spec_disabled"])
		self.assertTrue(report["mtp_spec_enabled"])
		self.assertAlmostEqual(float(report["speedup_vs_session_baseline"]), 2.0 / 2.2)
		self.assertAlmostEqual(float(report["speedup_vs_prior_argmax_baseline"]), 2.0 / 14.65)
		self.assertTrue(validate.validate_report(report)["ok"])

	def test_validator_rejects_unmatched_claim(self) -> None:
		report = {
			"format": "ds4-mtp-benchmark-integrity-v1",
			"benchmark_status": "comparable",
			"same_cli_path": False,
			"same_perf_env": True,
			"baseline_spec_disabled": True,
			"mtp_spec_enabled": True,
			"baseline_perf_env_sha256": "a" * 64,
			"mtp_perf_env_sha256": "a" * 64,
			"baseline_reported_generation_tps": 2.0,
			"mtp_reported_generation_tps": 3.0,
			"speedup_vs_session_baseline": 1.5,
			"baseline_external_process_wall_s": 1.0,
			"mtp_external_process_wall_s": 1.0,
			"baseline_exit_code": 0,
			"mtp_exit_code": 0,
		}
		res = validate.validate_report(report)
		self.assertFalse(res["ok"])
		self.assertTrue(any("same_cli_path" in e for e in res["errors"]))

	def test_blocks_environment_shape_mismatch(self) -> None:
		with tempfile.TemporaryDirectory() as td:
			base = Path(td) / "base.log"
			mtp = Path(td) / "mtp.log"
			base.write_text(BASE_LOG, encoding="utf-8")
			mtp.write_text(MTP_LOG.replace("a" * 64, "b" * 64), encoding="utf-8")
			report = build.build_report(
				[base],
				[mtp],
				run_id="r",
				model_id="m",
				runtime_id="rt",
				prompt="",
				prompt_hash="def",
				prior_argmax_baseline_tps=14.65,
			)
		self.assertEqual(report["benchmark_status"], "blocked")
		self.assertFalse(report["same_perf_env"])
		self.assertIn("environment shape", report["blocker_detail"])
		self.assertTrue(validate.validate_report(report)["ok"])


if __name__ == "__main__":
	unittest.main()
