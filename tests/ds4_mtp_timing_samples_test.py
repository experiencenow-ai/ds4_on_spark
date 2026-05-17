import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_ds4_mtp_timing_samples as build
from scripts import validate_ds4_mtp_timing_samples as validate


def _sample(idx: int, generation_tps: float) -> dict[str, object]:
	return {
		"speed": {
			"generation_tps": generation_tps,
			"prefill_tps": 2.0,
		},
		"totals": {
			"draft_tokens_accepted_est": 2,
			"draft_tokens_attempted_est": 2,
			"draft_accept_rate_est": 1.0,
		},
		"mismatches": {
			"target_next_mismatch_events": 0,
		},
		"timing": {
			"events": 1,
		},
		"sample_diag": {
			"direct": 1,
			"suffix2_attempts": 1,
			"suffix2_full_accepts": 1,
		},
		"benchmark": {
			"events": [
				{
					"phase": "mtp",
					"external_wall_s": 1.0 + float(idx),
					"command_sha256": "sha256:cmd",
					"perf_env_sha256": "sha256:env",
					"perf_env_keys": ["DS4_MTP_DRAFT"],
					"prompt_sha256": "sha256:prompt",
					"n_predict": 32,
					"mtp_draft": 2,
					"ctx": 2048,
					"seed": 123,
					"spec_disabled": 0,
					"exit_code": 0,
				}
			],
		},
	}


class Ds4MtpTimingSamplesTest(unittest.TestCase):
	def _write_samples(self, root: Path, count: int, *, mismatch_env: bool = False, mismatch_prompt: bool = False) -> list[Path]:
		paths = []
		for idx in range(count):
			obj = _sample(idx, 10.0 + float(idx))
			if mismatch_env and idx == (count - 1):
				obj["benchmark"]["events"][0]["perf_env_sha256"] = "sha256:other"  # type: ignore[index]
			if mismatch_prompt and idx == (count - 1):
				obj["benchmark"]["events"][0]["prompt_sha256"] = "sha256:other-prompt"  # type: ignore[index]
			path = root / f"sample-{idx}.json"
			path.write_text(json.dumps(obj), encoding="utf-8")
			paths.append(path)
		return paths

	def test_builds_and_validates_ten_sample_report(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			paths = self._write_samples(Path(tmp), 10)
			report = build.build_report(
				paths,
				run_id="r",
				label="k2",
				min_sample_count=10,
				baseline_tps=10.0,
			)
		self.assertEqual(report["format"], "ds4-mtp-timing-samples-v1")
		self.assertEqual(report["sample_status"], "passed")
		self.assertEqual(report["sample_count"], 10)
		self.assertAlmostEqual(float(report["generation_tps_median"]), 14.5)
		self.assertGreater(float(report["generation_tps_stdev"]), 0.0)
		self.assertAlmostEqual(float(report["speedup_vs_baseline_median"]), 1.45)
		self.assertEqual(report["sample_records"][0]["sample_diag"]["suffix2_full_accepts"], 1)
		self.assertTrue(validate.validate_report(report)["ok"])

	def test_builder_derives_measured_mode_acceptance_from_sample_diag(self) -> None:
		obj = _sample(0, 20.0)
		obj["totals"] = {
			"draft_tokens_accepted_est": 0,
			"draft_tokens_attempted_est": 0,
			"draft_accept_rate_est": None,
		}
		obj["sample_diag"] = {
			"direct": 1,
			"suffix2_attempts": 3,
			"suffix2_full_accepts": 1,
			"suffix2_partial_accepts": 1,
			"suffix2_rejects": 1,
		}
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "sample.json"
			path.write_text(json.dumps(obj), encoding="utf-8")
			report = build.build_report(
				[path],
				run_id="r",
				label="k2",
				min_sample_count=1,
				baseline_tps=None,
			)
		record = report["sample_records"][0]
		self.assertEqual(record["accepted_draft_tokens"], 3)
		self.assertEqual(record["attempted_draft_tokens"], 6)
		self.assertEqual(record["accept_rate"], 0.5)

	def test_builder_marks_nine_samples_insufficient(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			paths = self._write_samples(Path(tmp), 9)
			report = build.build_report(
				paths,
				run_id="r",
				label="k2",
				min_sample_count=10,
				baseline_tps=10.0,
			)
		self.assertEqual(report["sample_status"], "insufficient_samples")
		self.assertIn("requires at least 10", str(report["blocker_detail"]))
		self.assertTrue(validate.validate_report(report)["ok"])

	def test_builder_blocks_mismatched_env(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			paths = self._write_samples(Path(tmp), 10, mismatch_env=True)
			report = build.build_report(
				paths,
				run_id="r",
				label="k2",
				min_sample_count=10,
				baseline_tps=10.0,
			)
		self.assertEqual(report["sample_status"], "blocked")
		self.assertIn("perf_env_sha256", str(report["blocker_detail"]))
		self.assertTrue(validate.validate_report(report)["ok"])
		report["sample_status"] = "passed"
		report["blocker_detail"] = ""
		res = validate.validate_report(report)
		self.assertFalse(res["ok"])
		self.assertTrue(any("perf_env_sha256" in err for err in res["errors"]))

	def test_builder_blocks_mismatched_prompt(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			paths = self._write_samples(Path(tmp), 10, mismatch_prompt=True)
			report = build.build_report(
				paths,
				run_id="r",
				label="k2",
				min_sample_count=10,
				baseline_tps=10.0,
			)
		self.assertEqual(report["sample_status"], "blocked")
		self.assertIn("prompt_sha256", str(report["blocker_detail"]))
		self.assertTrue(validate.validate_report(report)["ok"])
		report["sample_status"] = "passed"
		report["blocker_detail"] = ""
		res = validate.validate_report(report)
		self.assertFalse(res["ok"])
		self.assertTrue(any("prompt_sha256" in err for err in res["errors"]))

	def test_validator_rejects_passed_report_with_too_few_samples(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			paths = self._write_samples(Path(tmp), 9)
			report = build.build_report(
				paths,
				run_id="r",
				label="k2",
				min_sample_count=10,
				baseline_tps=10.0,
			)
		report["sample_status"] = "passed"
		report["blocker_detail"] = ""
		res = validate.validate_report(report)
		self.assertFalse(res["ok"])
		self.assertTrue(any("sample_count >= min_sample_count" in err for err in res["errors"]))

	def test_validator_rejects_min_sample_count_below_ten(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			paths = self._write_samples(Path(tmp), 10)
			report = build.build_report(
				paths,
				run_id="r",
				label="k2",
				min_sample_count=10,
				baseline_tps=10.0,
			)
		report["min_sample_count"] = 1
		res = validate.validate_report(report)
		self.assertFalse(res["ok"])
		self.assertTrue(any("integer >= 10" in err for err in res["errors"]))


if __name__ == "__main__":
	unittest.main()
