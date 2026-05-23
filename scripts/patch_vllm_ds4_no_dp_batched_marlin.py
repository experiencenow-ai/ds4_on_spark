#!/usr/bin/env python3
"""Patch vLLM MXFP4 MoE to prototype no-DP BatchedMarlin on DS4."""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.vllm_patch_utils import locate_vllm_package_dir
from scripts._lib.vllm_patch_utils import replace_once
from scripts._lib.vllm_patch_utils import write_patch_file


PATCH_ID = "ds4-vllm-no-dp-batched-marlin-prototype"
UNSAFE_WRITE_FLAG = "--unsafe-allow-spark4-wedge-profile"
UNSAFE_WRITE_DETAIL = (
	"This no-DP BatchedMarlin prototype selected BATCHED_MARLIN, then wedged "
	"Spark4 during FULL_AND_PIECEWISE CUDA graph capture before API readiness. "
	"Use only on an expendable node after a reboot/power-cycle plan is in place."
)


class PatchError(RuntimeError):
	pass


_replace = partial(replace_once, error_type=PatchError)
_write = write_patch_file
locate_package_dir = partial(locate_vllm_package_dir, error_type=PatchError)


def patch_config(text: str) -> str:
	text, _ = _replace(
		text,
		"from dataclasses import dataclass\n",
		"from dataclasses import dataclass\nimport os\n",
		"config os import",
	)
	text, _ = _replace(
		text,
		"""    @property
    def use_batched_activation_format(self):
        return self.use_deepep_ll_kernels or self.use_nixl_ep_kernels
""",
		"""    @property
    def use_batched_activation_format(self):
        return (
            self.use_deepep_ll_kernels
            or self.use_nixl_ep_kernels
            or (
                os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
                and not self.use_all2all_kernels
                and self.dp_size == 1
            )
        )
""",
		"batched activation force gate",
	)
	return(text)


def patch_all2all_utils(text: str) -> str:
	text, _ = _replace(
		text,
		"from typing import Any\n",
		"import os\nfrom typing import Any\n",
		"all2all os import",
	)
	old_standard = """        else:
            return make_moe_prepare_and_finalize_no_dp_ep(use_monolithic)
"""
	old_global = """        else:
            if (
                os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
                and not use_monolithic
                and moe.dp_size == 1
            ):
                from vllm.model_executor.layers.fused_moe.prepare_finalize.batched import (
                    BatchedPrepareAndFinalize,
                )

                logger.warning_once(
                    "DS4 forcing no-DP BatchedPrepareAndFinalize for MXFP4 MoE "
                    "prototype: global_experts=%d local_experts=%d max_tokens=%d",
                    moe.num_experts,
                    moe.num_local_experts,
                    moe.max_num_tokens,
                )
                return BatchedPrepareAndFinalize(
                    max_num_tokens=moe.max_num_tokens,
                    num_local_experts=moe.num_experts,
                    num_dispatchers=1,
                    rank=0,
                )
            return make_moe_prepare_and_finalize_no_dp_ep(use_monolithic)
"""
	new_local = """        else:
            if (
                os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
                and not use_monolithic
                and moe.dp_size == 1
            ):
                from vllm.model_executor.layers.fused_moe.prepare_finalize.batched import (
                    BatchedPrepareAndFinalize,
                )

                logger.warning_once(
                    "DS4 forcing no-DP BatchedPrepareAndFinalize for MXFP4 MoE "
                    "prototype: global_experts=%d local_experts=%d ep_rank=%d "
                    "max_tokens=%d",
                    moe.num_experts,
                    moe.num_local_experts,
                    moe.ep_rank,
                    moe.max_num_tokens,
                )
                return BatchedPrepareAndFinalize(
                    max_num_tokens=moe.max_num_tokens,
                    num_local_experts=moe.num_local_experts,
                    num_dispatchers=1,
                    rank=moe.ep_rank,
                )
            return make_moe_prepare_and_finalize_no_dp_ep(use_monolithic)
"""
	if new_local not in text:
		if old_global in text:
			text = text.replace(old_global, new_local, 1)
		elif old_standard in text:
			text = text.replace(old_standard, new_local, 1)
		else:
			raise PatchError("missing expected block: no-DP batched prepare/finalize force")
	return(text)


def patch_marlin_moe(text: str) -> str:
	text = text.replace(
		"from collections.abc import Callable\nimport os\n",
		"from collections.abc import Callable\n",
	)
	old_global = """        num_dispatchers = self.num_dispatchers
        num_experts = (
            global_num_experts
            if os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
            else local_num_experts
        )
        max_num_tokens = self.max_num_tokens
"""
	new_local = """        num_dispatchers = self.num_dispatchers
        num_experts = local_num_experts
        max_num_tokens = self.max_num_tokens
"""
	if old_global in text:
		text = text.replace(old_global, new_local, 1)
	elif new_local not in text:
		raise PatchError("missing expected block: batched marlin local expert workspace")
	return(text)


def patch_batched_prepare_finalize(text: str) -> str:
	text, _ = _replace(
		text,
		"import torch\n",
		"import os\nimport torch\n",
		"batched prepare/finalize os import",
	)
	old_standard = """        tokens_per_expert = torch.zeros(num_experts, dtype=torch.int, device=a1.device)

        num_local_experts = self.num_local_experts
"""
	new_local_counter = """        num_local_experts = self.num_local_experts
        token_counter_experts = (
            num_local_experts
            if os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
            else num_experts
        )
        tokens_per_expert = torch.zeros(
            token_counter_experts,
            dtype=torch.int,
            device=a1.device,
        )
"""
	if new_local_counter not in text:
		if old_standard in text:
			text = text.replace(old_standard, new_local_counter, 1)
		else:
			raise PatchError("missing expected block: batched prepare local token counter")
	old_reference_loop = """        for expert_id in range(first_expert, last_expert):
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
	new_graph_safe_loop = """        if (
            os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1"
            and quant_config.quant_dtype is not None
        ):
            raise NotImplementedError(
                "DS4 no-DP BatchedMarlin prototype only supports unquantized "
                "activation input for CUDA-graph-safe prepare"
            )

        for expert_id in range(first_expert, last_expert):
            idx = expert_id - first_expert
            topks = torch.any(topk_ids == expert_id, dim=1).flatten()
            topks_i32 = topks.to(torch.int32)
            rows = torch.sum(topks_i32)
            tokens_per_expert[idx] = rows
            row_indices = torch.cumsum(topks_i32, dim=0) - 1
            row_indices = torch.where(
                topks,
                row_indices,
                torch.zeros_like(row_indices),
            ).to(torch.long)
            if quant_config.quant_dtype is not None:
                rhs = a1[: topks.numel()][topks]
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
            elif os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1":
                b_a1[idx].scatter_add_(
                    0,
                    row_indices.view(num_tokens, 1).expand(num_tokens, hidden_dim),
                    a1 * topks.to(a1.dtype).view(num_tokens, 1),
                )
            else:
                rhs = a1[: topks.numel()][topks]
                b_a1[idx, :rows, :] = rhs
"""
	if new_graph_safe_loop not in text:
		if old_reference_loop in text:
			text = text.replace(old_reference_loop, new_graph_safe_loop, 1)
		else:
			raise PatchError("missing expected block: batched prepare expert loop")
	return(text)


def patch_topk_weight_and_reduce(text: str) -> str:
	text, _ = _replace(
		text,
		"import torch\n",
		"import os\nimport torch\n",
		"topk weight/reduce os import",
	)
	old_reference_loop = """        for expert_id in range(first_expert, last_expert):
            matching_tokens = topk_ids == expert_id
            topks = torch.any(matching_tokens, dim=1).flatten()
            rows = torch.count_nonzero(topks)
            rhs = fused_expert_output[expert_id - first_expert, :rows, :]
            if not apply_router_weight_on_input:
                rhs.mul_(topk_weights[matching_tokens].view(rhs.size(0), 1))
            output[topks] = output[topks] + rhs
"""
	new_graph_safe_loop = """        for expert_id in range(first_expert, last_expert):
            idx = expert_id - first_expert
            matching_tokens = topk_ids == expert_id
            topks = torch.any(matching_tokens, dim=1).flatten()
            topks_i32 = topks.to(torch.int32)
            row_indices = torch.cumsum(topks_i32, dim=0) - 1
            row_indices = torch.where(
                topks,
                row_indices,
                torch.zeros_like(row_indices),
            ).to(torch.long)
            rhs = fused_expert_output[idx].index_select(0, row_indices)
            if not apply_router_weight_on_input:
                expert_weights = (
                    topk_weights * matching_tokens.to(topk_weights.dtype)
                ).sum(dim=1, keepdim=True)
                rhs = rhs * expert_weights.to(rhs.dtype)
            if os.environ.get("DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN") == "1":
                output.add_(rhs * topks.to(rhs.dtype).view(num_tokens, 1))
            else:
                rows = torch.count_nonzero(topks)
                output[topks] = output[topks] + rhs[:rows]
"""
	if new_graph_safe_loop not in text:
		if old_reference_loop in text:
			text = text.replace(old_reference_loop, new_graph_safe_loop, 1)
		else:
			raise PatchError("missing expected block: naive batched topk reduce loop")
	return(text)


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
	targets = {
		"config": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "config.py",
			patch_config,
		),
		"all2all_utils": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "all2all_utils.py",
			patch_all2all_utils,
		),
		"marlin_moe": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "experts" / "marlin_moe.py",
			patch_marlin_moe,
		),
		"batched_prepare_finalize": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "prepare_finalize" / "batched.py",
			patch_batched_prepare_finalize,
		),
		"topk_weight_and_reduce": (
			package_dir / "model_executor" / "layers" / "fused_moe" / "topk_weight_and_reduce.py",
			patch_topk_weight_and_reduce,
		),
	}
	files: dict[str, Any] = {}
	for name, (path, fn) in targets.items():
		if not path.exists():
			raise PatchError(f"missing target file: {path}")
		original = path.read_text(encoding="utf-8")
		patched = fn(original)
		files[name] = _write(path, original, patched, backup_suffix=backup_suffix, write=write)
	return({
		"patch_id": PATCH_ID,
		"package_dir": str(package_dir),
		"env_flag": "DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1",
		"write": write,
		"changed": any(item["changed"] for item in files.values()),
		"files": files,
	})


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--runtime-root")
	parser.add_argument("--vllm-package-dir")
	parser.add_argument("--backup-suffix", default=".ds4_no_dp_batched_marlin_bak")
	parser.add_argument("--check", action="store_true", help="Show whether changes are needed without writing.")
	parser.add_argument(UNSAFE_WRITE_FLAG, action="store_true", help=argparse.SUPPRESS)
	args = parser.parse_args()
	if not args.check and not getattr(args, "unsafe_allow_spark4_wedge_profile"):
		parser.error(f"refusing to write known Spark4-wedging prototype; pass {UNSAFE_WRITE_FLAG} only for isolated recovery experiments. {UNSAFE_WRITE_DETAIL}")
	package_dir = locate_package_dir(
		Path(args.runtime_root).expanduser() if args.runtime_root else None,
		Path(args.vllm_package_dir).expanduser() if args.vllm_package_dir else None,
	)
	result = apply_patch(package_dir, backup_suffix=args.backup_suffix, write=not args.check)
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0)


if __name__ == "__main__":
	raise SystemExit(main())
