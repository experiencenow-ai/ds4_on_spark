#!/usr/bin/env python3
"""Verify the antirez/ds4 explicit stage preload patch."""

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
		"diff --git a/ds4_gpu.h b/ds4_gpu.h",
		"diff --git a/ds4_cuda.cu b/ds4_cuda.cu",
		"diff --git a/ds4.c b/ds4.c",
		"ds4_gpu_preload_model_range",
		"cuda_model_arena_alloc(bytes, what)",
		"cuda_model_stage_pool_alloc(stage_bytes, stage_align)",
		"cuda_model_stage_read(model_map, g_model_stage[0]",
		"cudaMemcpy(dev + copied, payload",
		"cudaDeviceSynchronize()",
		"g_model_ranges.push_back({model_map, offset, bytes, dev",
		"cuda_model_offset_key{model_map, cuda_model_fd_for_map(model_map), offset}",
		"cuda_stack_probe_preload_sleep_us()",
		"stack_stage_l%u_%s",
		"ffn_gate_exps",
		"ffn_up_exps",
		"ffn_down_exps",
	])
	require_substrings(errors, added_text, [
		"int ds4_gpu_preload_model_range(",
		"const uint64_t stage_bytes = chunk_bytes + stage_align;",
		"cuda_model_drop_file_pages(model_map, offset + copied, n);",
		"cuda_model_discard_source_pages(model_map, model_size, offset + copied, n);",
		"cuda_stack_probe_tensor_entry",
		"tensors[i].name",
	], "expected added substring")
	for forbidden in ["spark_count", "num_sparks", "world_size"]:
		if forbidden in patch_text:
			errors.append(f"patch should not hardcode topology field: {forbidden}")
	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
