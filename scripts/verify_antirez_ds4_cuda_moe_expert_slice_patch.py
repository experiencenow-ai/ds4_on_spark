#!/usr/bin/env python3
"""Verify that the antirez/ds4 CUDA MoE expert-slice cache patch is complete.

The verifier is intentionally lightweight: it checks the patch text for the
decode-only expert-slice path that avoids caching whole 256-expert MoE slabs.
"""

from __future__ import annotations

import argparse
import sys


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _read_text(path: str) -> str:
	try:
		with open(path, "r", encoding="utf-8") as f:
			return f.read()
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	return ""


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	added_lines: list[str] = []
	for line in patch_text.splitlines():
		if not line.startswith("+"):
			continue
		if line.startswith("+++ "):
			continue
		added_lines.append(line[1:])

	required_substrings = [
		"diff --git a/ds4_cuda.cu b/ds4_cuda.cu",
		"__global__ static void moe_gate_up_mid_qwarp32_slices_kernel(",
		"__global__ static void moe_gate_up_mid_decode_lut_qwarp32_slices_kernel(",
		"__global__ static void moe_down_sum6_qwarp32_slices_kernel(",
		"__global__ static void moe_gate_up_mid_q4_f32_slices_kernel(",
		"__global__ static void moe_down_q4_f32_slices_kernel(",
		"static int cuda_moe_prepare_decode_expert_slices(",
		"cudaMemcpy(expert_ids, selected->ptr, (size_t)n_expert * sizeof(int32_t), cudaMemcpyDeviceToHost)",
		"host_ptrs[slot] = cuda_model_range_ptr(model_map, gate_slice_offset, gate_expert_bytes, \"moe_gate_expert\");",
		"host_ptrs[n_expert + slot] = cuda_model_range_ptr(model_map, up_slice_offset, gate_expert_bytes, \"moe_up_expert\");",
		"host_ptrs[2u * n_expert + slot] = cuda_model_range_ptr(model_map, down_slice_offset, down_expert_bytes, \"moe_down_expert\");",
		"cuda_tmp_alloc(ptr_bytes, \"routed_moe expert slice pointers\")",
		"DS4_CUDA_MOE_EXPERT_SLICE_CACHE",
		"DS4_CUDA_MOE_EXPERT_SLICE_STRICT",
		"DS4_CUDA_MOE_EXPERT_SLICE_VERBOSE",
		"n_tokens == 1u",
		"n_expert == 6u",
		"if (!use_expert_slices) {",
		"moe_gate_up_mid_decode_lut_qwarp32_slices_kernel<<<qgrid, 256>>>",
		"moe_gate_up_mid_qwarp32_slices_kernel<<<qgrid, 256>>>",
		"moe_down_sum6_qwarp32_slices_kernel<<<sgrid, 256>>>",
		"moe_gate_up_mid_q4_f32_slices_kernel<<<mgrid, 256>>>",
		"moe_down_q4_f32_slices_kernel<<<dgrid, 256>>>",
	]
	for s in required_substrings:
		if s not in patch_text:
			errors.append(f"missing expected substring: {s!r}")

	full_slab_markers = [
		"cuda_model_range_ptr(model_map, gate_offset, gate_bytes, \"moe_gate\")",
		"cuda_model_range_ptr(model_map, up_offset, gate_bytes, \"moe_up\")",
		"cuda_model_range_ptr(model_map, down_offset, down_bytes, \"moe_down\")",
	]
	for s in full_slab_markers:
		if s not in patch_text:
			errors.append(f"missing full-slab fallback marker: {s!r}")

	for line in added_lines:
		if "DS4_CUDA_MOE_EXPERT_SLICE_CACHE" in line and "getenv(" not in line:
			errors.append("slice-cache env marker should be read through getenv")
			break

	return errors


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()

	patch_text = _read_text(args.patch)
	errors = validate_patch_text(patch_text)
	if errors:
		for e in errors[:64]:
			print(f"error: {e}", file=sys.stderr)
		raise SystemExit(2)

	print("ok=true")


if __name__ == "__main__":
	main()
