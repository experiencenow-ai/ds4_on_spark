import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_ds4_mtp_timing_samples_summary as build


def _report(status: str, median: float, cv: float) -> dict[str, object]:
	return {
		"format": "ds4-mtp-timing-samples-v1",
		"sample_status": status,
		"sample_count": 10,
		"generation_tps_median": median,
		"generation_tps_mean": median,
		"generation_tps_stdev": median * cv,
		"generation_tps_cv": cv,
		"sample_records": [
			{
				"accept_rate": 1.0,
				"accepted_draft_tokens": 84,
				"attempted_draft_tokens": 84,
				"sample_diag": {
					"serial_steps": 0,
					"suffix2_fallbacks": 0,
				},
			}
			for _ in range(10)
		],
	}


class Ds4MtpTimingSamplesSummaryTest(unittest.TestCase):
	def test_marks_stable_reports_passed(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			base = root / "base.json"
			mtp = root / "mtp.json"
			base.write_text(json.dumps(_report("passed", 10.0, 0.05)), encoding="utf-8")
			mtp.write_text(json.dumps(_report("passed", 18.0, 0.08)), encoding="utf-8")
			obj = build.build_summary(base, mtp, max_cv_for_direction=0.15)
		self.assertEqual(obj["decision_status"], "passed")
		self.assertTrue(obj["baseline_timing_stable"])
		self.assertTrue(obj["mtp_timing_stable"])
		self.assertEqual(obj["mtp_suffix2_fallback_sample_count"], 0)
		self.assertEqual(obj["mtp_serial_step_sample_count"], 0)
		self.assertAlmostEqual(float(obj["speedup_vs_baseline_median"]), 1.8)

	def test_marks_high_variance_mtp_unstable(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			base = root / "base.json"
			mtp = root / "mtp.json"
			base.write_text(json.dumps(_report("passed", 10.0, 0.05)), encoding="utf-8")
			mtp.write_text(json.dumps(_report("passed", 18.0, 0.30)), encoding="utf-8")
			obj = build.build_summary(base, mtp, max_cv_for_direction=0.15)
		self.assertEqual(obj["decision_status"], "unstable")
		self.assertFalse(obj["mtp_timing_stable"])
		self.assertIn("MTP generation_tps_cv", str(obj["blocker_detail"]))

	def test_blocks_mtp_fallback_samples(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			base = root / "base.json"
			mtp = root / "mtp.json"
			base.write_text(json.dumps(_report("passed", 10.0, 0.05)), encoding="utf-8")
			mtp_report = _report("passed", 18.0, 0.08)
			mtp_report["sample_records"][0]["sample_diag"]["suffix2_fallbacks"] = 1  # type: ignore[index]
			mtp.write_text(json.dumps(mtp_report), encoding="utf-8")
			obj = build.build_summary(base, mtp, max_cv_for_direction=0.15)
		self.assertEqual(obj["decision_status"], "blocked")
		self.assertEqual(obj["mtp_suffix2_fallback_sample_count"], 1)
		self.assertIn("fallbacks", str(obj["blocker_detail"]))

	def test_reports_nonfull_accept_samples_without_blocking(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			base = root / "base.json"
			mtp = root / "mtp.json"
			base.write_text(json.dumps(_report("passed", 10.0, 0.05)), encoding="utf-8")
			mtp_report = _report("passed", 18.0, 0.08)
			mtp_report["sample_records"][0]["accept_rate"] = 0.5  # type: ignore[index]
			mtp_report["sample_records"][0]["accepted_draft_tokens"] = 42  # type: ignore[index]
			mtp_report["sample_records"][0]["attempted_draft_tokens"] = 84  # type: ignore[index]
			mtp.write_text(json.dumps(mtp_report), encoding="utf-8")
			obj = build.build_summary(base, mtp, max_cv_for_direction=0.15)
		self.assertEqual(obj["decision_status"], "passed")
		self.assertEqual(obj["mtp_suffix2_nonfull_sample_count"], 1)
		self.assertAlmostEqual(float(obj["mtp_accept_rate_min"]), 0.5)

	def test_blocks_when_sample_report_did_not_pass(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			base = root / "base.json"
			mtp = root / "mtp.json"
			base.write_text(json.dumps(_report("insufficient_samples", 10.0, 0.05)), encoding="utf-8")
			mtp.write_text(json.dumps(_report("passed", 18.0, 0.08)), encoding="utf-8")
			obj = build.build_summary(base, mtp, max_cv_for_direction=0.15)
		self.assertEqual(obj["decision_status"], "blocked")
		self.assertIn("must both pass", str(obj["blocker_detail"]))


if __name__ == "__main__":
	unittest.main()
