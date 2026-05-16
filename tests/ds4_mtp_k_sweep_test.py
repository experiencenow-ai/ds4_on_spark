import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_ds4_mtp_k_sweep as build
from scripts import validate_ds4_mtp_k_sweep as validate


FIX = Path("fixtures/mtp")


class Ds4MtpKSweepTest(unittest.TestCase):
	def test_k345_fixture_validates(self) -> None:
		path = FIX / "ds4_mtp_k345_sweep_20260516.example.json"
		obj = json.loads(path.read_text(encoding="utf-8"))
		self.assertTrue(validate.validate_report(obj)["ok"])
		self.assertEqual(obj["k_values_tested_or_classified"], [3, 4, 5])
		self.assertFalse(obj["k_power_of_two_required"])
		self.assertEqual(obj["k_results"][0]["measurement_status"], "measured")
		self.assertAlmostEqual(float(obj["k_results"][0]["target_positions_per_invocation"]), 4.0)

	def test_builder_classifies_k345_against_k2_reference(self) -> None:
		measurement = {
			"baseline_tps": 11.02,
			"mtp_tps": 20.55,
			"speedup_vs_baseline": 20.55 / 11.02,
			"accepted_draft_tokens": 84,
			"attempted_draft_tokens": 84,
			"accept_rate": 1.0,
			"emitted_tokens": 126,
			"target_verifier_invocation_count": 42,
			"target_positions_verified": 126,
			"target_positions_per_invocation": 3.0,
			"output_head_invocation_count": 42,
			"full_vocab_logits_rows": 42,
			"top1_only_rows": 84,
			"slowest_component": "target_eval_ms",
		}
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "economics.json"
			path.write_text(json.dumps(measurement), encoding="utf-8")
			obj = build.build_sweep(
				run_id="r",
				model_id="m",
				runtime_id="rt",
				prompt_hash="p",
				k_values=[3, 4, 5],
				supported_k={2, 3},
				idle_slots=[2, 3, 4, 5],
				accept_prob=None,
				measured_paths=[path],
			)
		self.assertTrue(validate.validate_report(obj)["ok"])
		self.assertEqual([row["k"] for row in obj["k_results"]], [3, 4, 5])
		self.assertEqual([row["k"] for row in obj["reference_measurements"]], [2])
		self.assertEqual(obj["k_results"][0]["measurement_status"], "supported_unmeasured")
		self.assertEqual(obj["k_results"][1]["measurement_status"], "projected_unsupported_runtime")
		self.assertEqual(obj["k_results"][2]["measurement_status"], "projected_unsupported_runtime")
		self.assertEqual(obj["blocker_kind"], "candidate_k_needs_spark_measurement")
		self.assertEqual(obj["best_projected_k_by_idle_rows"][1]["best_k_for_sequence_latency"], 3)
		self.assertEqual(obj["best_projected_k_by_idle_rows"][2]["best_k_for_sequence_latency"], 4)
		self.assertEqual(obj["best_projected_k_by_idle_rows"][3]["best_k_for_sequence_latency"], 5)

	def test_validator_rejects_power_of_two_only_sweep(self) -> None:
		obj = build.build_sweep(
			run_id="r",
			model_id="m",
			runtime_id="rt",
			prompt_hash="p",
			k_values=[4],
			supported_k=set(),
			idle_slots=[4],
			accept_prob=0.9,
			measured_paths=[],
		)
		res = validate.validate_report(obj)
		self.assertFalse(res["ok"])
		self.assertTrue(any("non-power-of-two" in err for err in res["errors"]))

	def test_validator_rejects_bad_idle_fit(self) -> None:
		obj = build.build_sweep(
			run_id="r",
			model_id="m",
			runtime_id="rt",
			prompt_hash="p",
			k_values=[3, 4, 5],
			supported_k=set(),
			idle_slots=[3],
			accept_prob=0.9,
			measured_paths=[],
		)
		obj["k_results"][0]["fits_idle_extra_rows"]["3"] = False
		obj["artifact_sha256"] = validate.artifact_sha256(obj)
		res = validate.validate_report(obj)
		self.assertFalse(res["ok"])
		self.assertTrue(any("fits_idle_extra_rows" in err for err in res["errors"]))


if __name__ == "__main__":
	unittest.main()
