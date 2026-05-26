import argparse
import tempfile
import unittest
from pathlib import Path

from scripts import spark_memory_launch_guard as guard


class SparkMemoryLaunchGuardTest(unittest.TestCase):
	def args(self, **overrides):
		data = {
			"model_path": "",
			"model_gib": 57.0,
			"weight_multiplier": 1.2,
			"ctx_tokens": 32768,
			"parallel": 4,
			"kv_mib_per_1k_token_slot": 1.0,
			"extra_gib": 4.0,
			"reserve_gib": 16.0,
			"commit_multiplier": 1.0,
			"min_swap_free_gib": 4.0,
			"exclusive": True,
		}
		data.update(overrides)
		return(argparse.Namespace(**data))

	def meminfo(self, mem_available_gib: float, swap_free_gib: float = 16.0, commit_margin_gib: float = 96.0):
		return({
			"MemAvailable": int(mem_available_gib * 1024 * 1024),
			"SwapFree": int(swap_free_gib * 1024 * 1024),
			"CommitLimit": int(128.0 * 1024 * 1024),
			"Committed_AS": int((128.0 - commit_margin_gib) * 1024 * 1024),
		})

	def test_blocks_ling_sized_launch_with_qwen_resident_and_low_available_memory(self):
		rows = [{"pid": 123, "rss_kib": 3_000_000, "vsz_kib": 150_000_000, "comm": "python", "args": "vllm serve /home/spark7/models/hf/Qwen/Qwen3.6-27B-FP8"}]
		result = guard.evaluate(self.args(), self.meminfo(8.0), rows)
		self.assertEqual(result["status"], guard.BLOCKED)
		kinds = {item["kind"] for item in result["issues"]}
		self.assertIn("resident_runtime_present", kinds)
		self.assertIn("insufficient_physical_memory", kinds)

	def test_passes_when_memory_is_clean_and_sufficient(self):
		result = guard.evaluate(self.args(model_gib=8.0, ctx_tokens=8192, parallel=1), self.meminfo(64.0), [])
		self.assertEqual(result["status"], guard.PASSED)

	def test_model_path_size_is_used_when_no_explicit_size(self):
		with tempfile.NamedTemporaryFile(delete=False) as fp:
			fp.truncate(1024 * 1024)
			path = Path(fp.name)
		try:
			result = guard.evaluate(self.args(model_path=str(path), model_gib=None), self.meminfo(32.0), [])
			self.assertAlmostEqual(result["estimate"]["model_weight_gib"], 0.001, places=3)
		finally:
			path.unlink(missing_ok=True)


if __name__ == "__main__":
	unittest.main()
