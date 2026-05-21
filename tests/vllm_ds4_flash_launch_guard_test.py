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
  tensor_parallel_size: 2
command: |
  vllm serve /models/deepseek-v4-flash \\
    --tokenizer-mode deepseek_v4 \\
    --tensor-parallel-size {tensor_parallel_size} \\
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
		self.assertGreater(result["memory_estimate"]["headroom_after_estimate_gib"], result["memory_estimate"]["minimum_headroom_gib"])

	def test_prefix_cache_enabled_blocks(self) -> None:
		path = self.write_tmp(GOOD_RECIPE.replace("--no-enable-prefix-caching", "--enable-prefix-caching"))
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.BAD)
		self.assertTrue(any(i["kind"] == "prefix_cache_c512_rank0_kill_risk" for i in result["issues"]))
		self.assertTrue(any(i["blocker_kind"] == "prefix_enabled_c512_risk" and i["recommended_fix"] for i in result["issues"]))

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

	def test_low_free_memory_blocks_with_structured_fix(self) -> None:
		text = GOOD_RECIPE.replace("gpu_memory_utilization: 0.8", "gpu_memory_utilization: 0.8\n  free_gpu_memory_gib: 70\n  declared_headroom_gib: 8")
		path = self.write_tmp(text)
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.BAD)
		self.assertLess(result["memory_estimate"]["headroom_after_estimate_gib"], result["memory_estimate"]["minimum_headroom_gib"])
		self.assertTrue(any(i["blocker_kind"] == "low_free_memory" and "free GPU memory" in i["recommended_fix"] for i in result["issues"]))

	def test_cross_node_tp_requires_gloo_socket_ifname(self) -> None:
		text = GOOD_RECIPE.replace("vllm serve", "vllm serve --nnodes 2 --tensor-parallel-size 2")
		path = self.write_tmp(text)
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.BAD)
		self.assertTrue(any(i["kind"] == "missing_gloo_socket_ifname" for i in result["issues"]))
		self.assertTrue(any(i["blocker_kind"] == "cross_node_gloo_loopback" and "GLOO_SOCKET_IFNAME" in i["recommended_fix"] for i in result["issues"]))

	def test_cross_node_tp_accepts_explicit_gloo_socket_ifname(self) -> None:
		text = GOOD_RECIPE.replace("vllm serve", "GLOO_SOCKET_IFNAME=enp1s0f1np1 vllm serve --nnodes 2 --tensor-parallel-size 2")
		path = self.write_tmp(text)
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.OK, result)

	def test_ds4_flash_rejects_bad_block_size(self) -> None:
		text = GOOD_RECIPE.replace("--no-enable-prefix-caching", "--block-size 256 --no-enable-prefix-caching")
		path = self.write_tmp(text)
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.BAD)
		self.assertEqual(result["effective"]["block_size"], 256)
		self.assertTrue(any(i["kind"] == "ds4_flash_block_size_mismatch" for i in result["issues"]))

	def test_ds4_flash_accepts_required_block_size(self) -> None:
		text = GOOD_RECIPE.replace("--no-enable-prefix-caching", "--block-size 128 --no-enable-prefix-caching")
		path = self.write_tmp(text)
		result = guard.validate_path(path)
		self.assertEqual(result["status"], guard.OK, result)
		self.assertEqual(result["effective"]["block_size"], 128)


if __name__ == "__main__":
	unittest.main()
