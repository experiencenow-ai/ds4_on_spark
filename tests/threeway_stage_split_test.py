import json
import unittest
from pathlib import Path


FIX = Path("fixtures/threeway_stage_split")


class ThreewayStageSplitTest(unittest.TestCase):
	def test_success_fixture_is_consistent(self) -> None:
		obj = json.loads((FIX / "spark012_b64_explicit_preload_success.example.json").read_text(encoding="utf-8"))
		self.assertEqual(obj["format"], "ds4-threeway-stage-split-v1")
		self.assertTrue(obj["all_stages_success"])
		self.assertEqual(obj["preload_policy"], "explicit_stage_preload")
		self.assertEqual(obj["stage_layer_ranges"], [[0, 15], [15, 29], [29, 43]])
		self.assertEqual(len(obj["stages"]), obj["stage_count"])
		self.assertEqual(obj["slowest_stage"], 0)
		self.assertAlmostEqual(obj["pipeline_rows_per_s_bound"], obj["batch"] * 1000.0 / obj["slowest_stage_ms"])
		for stage in obj["stages"]:
			self.assertEqual(stage["rc"], 0)
			self.assertEqual(stage["out_nonfinite"], 0)
			self.assertGreater(stage["preloaded_tensors"], 400)
			self.assertGreater(stage["preloaded_bytes_gib"], 25.0)

	def test_fixture_does_not_claim_end_to_end_generation(self) -> None:
		obj = json.loads((FIX / "spark012_b64_explicit_preload_success.example.json").read_text(encoding="utf-8"))
		joined = "\n".join(obj.get("notes", []))
		self.assertIn("not end-to-end generation", joined)
		self.assertNotIn("tok_s", obj)
		self.assertNotIn("spark_count", obj)
		self.assertNotIn("world_size", obj)


if __name__ == "__main__":
	unittest.main()
