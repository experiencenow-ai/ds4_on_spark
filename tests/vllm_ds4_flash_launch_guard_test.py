import tempfile
import unittest
from pathlib import Path

from scripts import vllm_ds4_flash_launch_guard as guard


GOOD_RECIPE = """recipe_version: "1"
name: good
container: vllm-node-dsv4
defaults:
  max_model_len: 200000
  max_num_batched_tokens: 8192
  max_num_seqs: 512
  gpu_memory_utilization: 0.8
command: |
  vllm serve /models/deepseek-v4-flash \\
    --tokenizer-mode deepseek_v4 \\
    --max-model-len {max_model_len} \\
    --max-num-seqs {max_num_seqs} \\
    --max-num-batched-tokens {max_num_batched_tokens} \\
    --gpu-memory-utilization {gpu_memory_utilization} \\
    --no-enable-prefix-caching
"""


class VllmDs4FlashLaunchGuardTest(unittest.TestCase):
	def write_tmp(self, text: str) -> Path:
		f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
		with f:
			f.write(text)
		return(Path(f.name))

	def test_known_safe_no_prefix_8192_passes(self) -> None:
		path = self.write_tmp(GOOD_RECIPE)
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.OK, result)
		self.assertEqual(result["effective"]["prefix_caching"], "disabled")
		self.assertEqual(result["effective"]["max_num_batched_tokens"], 8192)

	def test_prefix_cache_enabled_blocks(self) -> None:
		path = self.write_tmp(GOOD_RECIPE.replace("--no-enable-prefix-caching", "--enable-prefix-caching"))
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.BAD)
		self.assertTrue(any(i["kind"] == "prefix_cache_c512_rank0_kill_risk" for i in result["issues"]))

	def test_small_batched_token_graph_profile_blocks(self) -> None:
		path = self.write_tmp(GOOD_RECIPE.replace("max_num_batched_tokens: 8192", "max_num_batched_tokens: 512"))
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.BAD)
		self.assertTrue(any(i["kind"] == "cuda_graph_kv_starvation_risk" for i in result["issues"]))

	def test_duplicate_batched_token_flag_blocks(self) -> None:
		text = GOOD_RECIPE.replace("--no-enable-prefix-caching", "--no-enable-prefix-caching --max-num-batched-tokens 512")
		path = self.write_tmp(text)
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.BAD)
		self.assertTrue(any(i["kind"] == "duplicate_max_num_batched_tokens" for i in result["issues"]))


if __name__ == "__main__":
	unittest.main()
