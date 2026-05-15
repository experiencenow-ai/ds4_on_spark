import json
import unittest
from pathlib import Path


FIX = Path("fixtures/stage_kernel_profile")


class StageKernelProfileTest(unittest.TestCase):
	def test_stage_profile_fixtures_identify_routed_moe_bottleneck(self) -> None:
		for path in sorted(FIX.glob("*_kernel_profile_b512.example.json")):
			with self.subTest(path=path.name):
				obj = json.loads(path.read_text(encoding="utf-8"))
				self.assertEqual(obj["format"], "ds4-stage-kernel-profile-v1")
				self.assertEqual(obj["mode"], "stage-profile")
				self.assertFalse(obj["production_generation_eligible"])
				self.assertEqual(obj["parity_status"], "not_run")
				self.assertEqual(len(obj["stage_summaries"]), 1)
				summary = obj["stage_summaries"][0]
				self.assertGreater(summary["sum_layer_ms"], 0.0)
				self.assertGreater(summary["sum_ffn_ms"], 0.0)
				self.assertGreater(summary["sum_moe_ms"], 0.0)
				self.assertGreater(summary["ffn_fraction_of_layer"], 0.90)
				self.assertGreater(summary["moe_fraction_of_layer"], 0.90)
				self.assertEqual(len(summary["layers"]), summary["layer_count"])

	def test_moe_variant_sweep_keeps_p2_enabled(self) -> None:
		obj = json.loads((FIX / "spark0_moe_variant_sweep_b512.example.json").read_text(encoding="utf-8"))
		self.assertEqual(obj["mode"], "moe-variant-sweep")
		by_variant = {}
		for row in obj["rows"]:
			by_variant.setdefault(row["variant"], []).append(row)
		self.assertIn("default", by_variant)
		self.assertIn("tile4", by_variant)
		self.assertIn("no_p2", by_variant)
		default_best = min(float(row["best_ms"]) for row in by_variant["default"])
		no_p2_best = min(float(row["best_ms"]) for row in by_variant["no_p2"])
		self.assertGreater(no_p2_best, default_best * 1.5)


if __name__ == "__main__":
	unittest.main()
