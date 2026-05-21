import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import vllm_memory_safety_preflight as preflight


SAFE_SCRIPT = """#!/bin/bash
vllm serve /models/deepseek-v4-flash \\
  --tokenizer-mode deepseek_v4 \\
  --tensor-parallel-size 2 \\
  --max-model-len 200000 \\
  --max-num-seqs 512 \\
  --max-num-batched-tokens 8192 \\
  --gpu-memory-utilization 0.8 \\
  --no-enable-prefix-caching
"""


class VllmMemorySafetyPreflightTest(unittest.TestCase):
	def write_tmp(self, text: str = SAFE_SCRIPT) -> Path:
		tmp = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False)
		tmp.write(text)
		tmp.close()
		return(Path(tmp.name))

	def test_blocks_known_insufficient_kv_headroom(self) -> None:
		result = preflight.evaluate_path(self.write_tmp(), available_kv_gib=6.07)
		self.assertEqual(result["status"], preflight.BAD)
		self.assertTrue(any(item["kind"] == "kv_request_exceeds_available" for item in result["issues"]))
		self.assertAlmostEqual(result["estimates"]["estimated_one_request_kv_gib"], 13.83)

	def test_passes_with_enough_kv_and_free_memory(self) -> None:
		result = preflight.evaluate_path(self.write_tmp(), available_kv_gib=16.0, gpu_free_gib=12.0)
		self.assertEqual(result["status"], preflight.OK)
		self.assertEqual(result["recommended_action"], "launch profile passed memory preflight")

	def test_requires_memory_sample_when_configured(self) -> None:
		result = preflight.evaluate_path(self.write_tmp(), require_memory_sample=True)
		self.assertEqual(result["status"], preflight.BAD)
		self.assertTrue(any(item["kind"] == "memory_sample_required" for item in result["issues"]))

	def test_runtime_hard_floor_requests_graceful_shutdown(self) -> None:
		result = preflight.evaluate_path(self.write_tmp(), available_kv_gib=16.0, runtime_free_gib=4.0)
		self.assertEqual(result["status"], preflight.BAD)
		self.assertTrue(any(item["kind"] == "runtime_gpu_memory_hard_floor" for item in result["issues"]))
		self.assertIn("terminate", result["recommended_action"])

	def test_cli_returns_blocked_status(self) -> None:
		cmd = [
			"python3",
			"scripts/vllm_memory_safety_preflight.py",
			str(self.write_tmp()),
			"--available-kv-gib",
			"6.07",
		]
		result = subprocess.run(cmd, text=True, capture_output=True)
		self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
		self.assertIn("kv_request_exceeds_available", result.stdout)


if __name__ == "__main__":
	unittest.main()
