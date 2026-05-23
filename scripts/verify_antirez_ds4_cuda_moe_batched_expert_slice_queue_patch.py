#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA batched expert-slice queue patch.

This verifier checks for the first real batched path: after the existing
one-token slice-cache patch, batched MoE decode can build real expert counts,
cache only active gate/up/down slices, and route sorted expert pairs through
slice-pointer kernels.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import added_patch_text
from scripts._lib.patch_verify import require_substrings
from scripts._lib.patch_verify import run_patch_verifier


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	added_text = added_patch_text(patch_text)

	require_substrings(errors, patch_text, [
		"diff --git a/ds4_cuda.cu b/ds4_cuda.cu",
		"__global__ static void moe_gate_up_mid_sorted_qwarp32_slices_kernel(",
		"__global__ static void moe_gate_up_mid_sorted_p2_qwarp32_slices_kernel(",
		"__global__ static void moe_down_sorted_qwarp32_slices_kernel(",
		"__global__ static void moe_down_sorted_p2_qwarp32_slices_kernel(",
		"static int cuda_moe_prepare_counted_expert_slices(",
		"cudaMemcpy(host_counts, counts, (size_t)counts_bytes, cudaMemcpyDeviceToHost)",
		"cuda_model_range_ptr(model_map, gate_slice_offset, gate_expert_bytes, \"moe_gate_expert_batched\")",
		"cuda_model_range_ptr(model_map, up_slice_offset, gate_expert_bytes, \"moe_up_expert_batched\")",
		"cuda_model_range_ptr(model_map, down_slice_offset, down_expert_bytes, \"moe_down_expert_batched\")",
		"cuda_tmp_alloc(ptr_bytes, \"routed_moe batched expert slice pointers\")",
		"DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE",
		"n_tokens > 1u",
		"fast_iq2_q2",
		"use_sorted_pairs && !use_batched_expert_slices",
		"cuda_moe_prepare_counted_expert_slices(model_map, model_size,",
		"moe_gate_up_mid_sorted_p2_qwarp32_slices_kernel<<<p2_mgrid, 256>>>",
		"moe_gate_up_mid_sorted_qwarp32_slices_kernel<<<mgrid, 256>>>",
		"moe_down_sorted_p2_qwarp32_slices_kernel<<<p2_dgrid, 256>>>",
		"moe_down_sorted_qwarp32_slices_kernel<<<dgrid, 256>>>",
		"if (use_batched_expert_slices) return 0;",
	])

	for line in added_text.splitlines():
		if "DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE" in line and "getenv(" not in line:
			errors.append("batched slice-cache env marker should be read through getenv")
			break

	for marker in [
		"gate_w = cuda_model_range_ptr(model_map, gate_offset, gate_bytes, \"moe_gate\");",
		"up_w = cuda_model_range_ptr(model_map, up_offset, gate_bytes, \"moe_up\");",
		"down_w = cuda_model_range_ptr(model_map, down_offset, down_bytes, \"moe_down\");",
	]:
		if marker not in patch_text:
			errors.append(f"missing full-slab fallback marker: {marker!r}")

	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
