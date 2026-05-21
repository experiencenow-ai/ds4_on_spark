import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_no_dp_batched_marlin as patcher


CONFIG = """from dataclasses import dataclass
from enum import IntEnum


class FusedMoEParallelConfig:
    @property
    def use_batched_activation_format(self):
        return self.use_deepep_ll_kernels or self.use_nixl_ep_kernels
"""


ALL2ALL_UTILS = """from typing import Any

import torch


def maybe_make_prepare_finalize(moe, quant_config, routing_tables=None, allow_new_interface=False, use_monolithic=False):
    if not moe.moe_parallel_config.use_all2all_kernels:
        if not allow_new_interface:
            return None
        if moe.moe_parallel_config.dp_size > 1:
            return make_moe_prepare_and_finalize_naive_dp_ep(
                is_sequence_parallel=moe.moe_parallel_config.is_sequence_parallel,
                num_dispatchers=(device_communicator.all2all_manager.world_size),
                use_monolithic=use_monolithic,
            )
        else:
            return make_moe_prepare_and_finalize_no_dp_ep(use_monolithic)
"""


MARLIN_MOE = """from collections.abc import Callable


class BatchedMarlinExperts:
    def workspace_shapes(
        self,
        M,
        N,
        K,
        topk,
        global_num_experts,
        local_num_experts,
        expert_tokens_meta,
        activation,
    ):
        assert self.num_dispatchers is not None
        assert self.max_num_tokens is not None
        num_dispatchers = self.num_dispatchers
        num_experts = local_num_experts
        max_num_tokens = self.max_num_tokens
        workspace13 = (num_experts * max_num_tokens * num_dispatchers, max(K, N * 2))
        workspace2 = (num_experts * max_num_tokens * num_dispatchers, N)
        output = (num_experts, max_num_tokens * num_dispatchers, K)
        return (workspace13, workspace2, output)
"""


BATCHED_PREPARE_FINALIZE = """import torch


class BatchedPrepareAndFinalize:
    def prepare(self, a1, topk_weights, topk_ids, num_experts, expert_map, apply_router_weight_on_input, quant_config, defer_input_quant=False):
        num_tokens, hidden_dim = a1.size()
        topk = topk_ids.size(1)

        tokens_per_expert = torch.zeros(num_experts, dtype=torch.int, device=a1.device)

        num_local_experts = self.num_local_experts

        if quant_config.quant_dtype is None:
            b_type = a1.dtype
        else:
            b_type = quant_config.quant_dtype

        for expert_id in range(first_expert, last_expert):
            topks = torch.any(topk_ids == expert_id, dim=1).flatten()
            rows = torch.count_nonzero(topks.flatten())
            if rows == 0:
                continue
            idx = expert_id - first_expert
            tokens_per_expert[idx] = rows
            rhs = a1[: topks.numel()][topks]
            if quant_config.quant_dtype is not None:
                if a1_scale is not None:
                    if quant_config.is_per_act_token:
                        rhs_a1_scale = a1_scale[: topks.numel()][topks]
                    else:
                        rhs_a1_scale = a1_scale
                else:
                    rhs_a1_scale = None
                b_a1[idx, :rows, :], b_s = moe_kernel_quantize_input(
                    rhs,
                    rhs_a1_scale,
                    quant_config.quant_dtype,
                    quant_config.per_act_token_quant,
                    quant_config.block_shape,
                )
                assert b_s is not None
                if quant_config.is_per_act_token:
                    b_a1_scale[idx, :rows] = b_s[:rows]
                else:
                    b_a1_scale[idx, : b_s.shape[0]] = b_s
            else:
                b_a1[idx, :rows, :] = rhs
"""


TOPK_WEIGHT_AND_REDUCE = """import torch


def apply_topk_weight_and_reduce(fused_expert_output, output, topk_weights, topk_ids, first_expert, last_expert, apply_router_weight_on_input):
    if output is not None:
        for expert_id in range(first_expert, last_expert):
            matching_tokens = topk_ids == expert_id
            topks = torch.any(matching_tokens, dim=1).flatten()
            rows = torch.count_nonzero(topks)
            rhs = fused_expert_output[expert_id - first_expert, :rows, :]
            if not apply_router_weight_on_input:
                rhs.mul_(topk_weights[matching_tokens].view(rhs.size(0), 1))
            output[topks] = output[topks] + rhs
"""


class PatchVllmDs4NoDpBatchedMarlinTest(unittest.TestCase):
	def test_config_patch_adds_env_gate(self) -> None:
		once = patcher.patch_config(CONFIG)
		twice = patcher.patch_config(once)
		self.assertEqual(once, twice)
		self.assertIn("import os", once)
		self.assertIn("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN", once)
		self.assertIn("not self.use_all2all_kernels", once)
		self.assertIn("self.dp_size == 1", once)

	def test_all2all_patch_returns_batched_prepare_finalize(self) -> None:
		once = patcher.patch_all2all_utils(ALL2ALL_UTILS)
		twice = patcher.patch_all2all_utils(once)
		self.assertEqual(once, twice)
		self.assertIn("BatchedPrepareAndFinalize", once)
		self.assertIn("logger.warning_once", once)
		self.assertIn("rank=moe.ep_rank", once)
		self.assertIn("num_local_experts=moe.num_local_experts", once)

	def test_marlin_patch_keeps_workspace_by_local_experts(self) -> None:
		once = patcher.patch_marlin_moe(MARLIN_MOE)
		twice = patcher.patch_marlin_moe(once)
		self.assertEqual(once, twice)
		self.assertIn("num_experts = local_num_experts", once)
		self.assertNotIn("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN", once)

	def test_marlin_patch_reverts_previous_global_workspace(self) -> None:
		previous = patcher.patch_marlin_moe(
			MARLIN_MOE.replace(
				"        num_experts = local_num_experts\n",
				"""        num_experts = (
            global_num_experts
            if os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
            else local_num_experts
        )
""",
			).replace(
				"from collections.abc import Callable\n",
				"from collections.abc import Callable\nimport os\n",
			)
		)
		self.assertIn("num_experts = local_num_experts", previous)
		self.assertNotIn("import os", previous)

	def test_batched_prepare_patch_uses_local_token_counter_under_flag(self) -> None:
		once = patcher.patch_batched_prepare_finalize(BATCHED_PREPARE_FINALIZE)
		twice = patcher.patch_batched_prepare_finalize(once)
		self.assertEqual(once, twice)
		self.assertIn("import os", once)
		self.assertIn("token_counter_experts", once)
		self.assertIn("num_local_experts", once)
		self.assertIn("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN", once)
		self.assertIn("scatter_add_", once)
		self.assertIn("torch.sum(topks_i32)", once)
		self.assertNotIn("if rows == 0", once)

	def test_topk_reduce_patch_avoids_host_scalar_branch_under_flag(self) -> None:
		once = patcher.patch_topk_weight_and_reduce(TOPK_WEIGHT_AND_REDUCE)
		twice = patcher.patch_topk_weight_and_reduce(once)
		self.assertEqual(once, twice)
		self.assertIn("import os", once)
		self.assertIn("index_select", once)
		self.assertIn("output.add_", once)
		self.assertIn("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN", once)

	def test_patch_package_dir_writes_backups(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp) / "vllm"
			(root / "model_executor" / "layers" / "fused_moe").mkdir(parents=True)
			config = root / "model_executor" / "layers" / "fused_moe" / "config.py"
			all2all = root / "model_executor" / "layers" / "fused_moe" / "all2all_utils.py"
			marlin = root / "model_executor" / "layers" / "fused_moe" / "experts" / "marlin_moe.py"
			batched = root / "model_executor" / "layers" / "fused_moe" / "prepare_finalize" / "batched.py"
			topk_reduce = root / "model_executor" / "layers" / "fused_moe" / "topk_weight_and_reduce.py"
			marlin.parent.mkdir(parents=True)
			batched.parent.mkdir(parents=True)
			config.write_text(CONFIG, encoding="utf-8")
			all2all.write_text(ALL2ALL_UTILS, encoding="utf-8")
			marlin.write_text(MARLIN_MOE, encoding="utf-8")
			batched.write_text(BATCHED_PREPARE_FINALIZE, encoding="utf-8")
			topk_reduce.write_text(TOPK_WEIGHT_AND_REDUCE, encoding="utf-8")
			result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
			self.assertTrue(result["changed"])
			self.assertTrue((config.with_name(config.name + ".bak")).exists())
			self.assertTrue((all2all.with_name(all2all.name + ".bak")).exists())
			self.assertFalse(result["files"]["marlin_moe"]["changed"])
			self.assertFalse((marlin.with_name(marlin.name + ".bak")).exists())
			self.assertTrue((batched.with_name(batched.name + ".bak")).exists())
			self.assertTrue((topk_reduce.with_name(topk_reduce.name + ".bak")).exists())
			result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
			self.assertFalse(result2["changed"])

	def test_cli_refuses_default_write_for_known_wedge_profile(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			result = subprocess.run(
				[
					sys.executable,
					"scripts/patch_vllm_ds4_no_dp_batched_marlin.py",
					"--vllm-package-dir",
					tmp,
				],
				capture_output=True,
				text=True,
			)
			self.assertNotEqual(result.returncode, 0)
			self.assertIn("refusing to write known Spark4-wedging prototype", result.stderr)
			self.assertIn(patcher.UNSAFE_WRITE_FLAG, result.stderr)


if __name__ == "__main__":
	unittest.main()
