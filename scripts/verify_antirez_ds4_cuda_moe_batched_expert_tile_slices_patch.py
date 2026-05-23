#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA batched expert-tile slice patch.

This verifier checks the second real expert-queue step: batched MoE slice
caching must not fall out of the high-throughput expert-tile kernels. The patch
keeps one tiled kernel family and gives it optional per-expert pointer tables.
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
		"-        const uint32_t use_expert_tiles = use_sorted_pairs && !use_batched_expert_slices &&",
		"+        const uint32_t use_expert_tiles = use_sorted_pairs &&",
		"moe_gate_up_mid_expert_tile8_rowspan_kernel<512><<<tgrid, 256>>>",
		"moe_gate_up_mid_expert_tile8_row32_kernel<<<tgrid, 256>>>",
		"moe_gate_up_mid_expert_tile4_row32_kernel<<<tgrid, 256>>>",
		"moe_down_expert_tile16_rowspan_block16_kernel<512><<<tgrid, 256>>>",
		"moe_down_expert_tile16_row32_kernel<<<tgrid, 256>>>",
		"moe_down_expert_tile8_row32_kernel<<<tgrid, 256>>>",
		"moe_down_expert_tile4_row32_kernel<<<tgrid, 256>>>",
	], "expected patch substring")

	require_substrings(errors, added_text, [
		"const char * const *gate_ptrs,",
		"const char * const *up_ptrs,",
		"const char * const *down_ptrs,",
		"gate_ptrs != NULL ? gate_ptrs[expert] : gate_base + (uint64_t)expert * gate_expert_bytes",
		"up_ptrs != NULL ? up_ptrs[expert] : up_base + (uint64_t)expert * gate_expert_bytes",
		"down_ptrs != NULL ? down_ptrs[expert] : down_base + (uint64_t)expert * down_expert_bytes",
		"if (gate_expert_base == NULL || up_expert_base == NULL) return;",
		"if (down_expert_base == NULL) return;",
		"const uint64_t slice_ptrs_bytes = use_batched_expert_slices ? 3ull * 256ull * sizeof(const char *) : 0u;",
		"const uint64_t slice_ptrs_off = (tile16_starts_off + tile16_starts_bytes + 7ull) & ~7ull;",
		"const char **batched_slice_ptrs = use_batched_expert_slices ? (const char **)(scratch + slice_ptrs_off) : NULL;",
		"if (dev_ptrs == NULL) {",
		"batched_slice_ptrs,",
		"getenv(\"DS4_CUDA_MOE_DOWN_BLOCK16\") != NULL",
		"use_batched_expert_slices ? gate_slices : NULL",
		"use_batched_expert_slices ? up_slices : NULL",
		"use_batched_expert_slices ? down_slices : NULL",
	], "expected added substring")

	for line in added_text.splitlines():
		if "use_expert_tiles =" in line and "!use_batched_expert_slices" in line:
			errors.append("batched expert slices must not disable expert tiles")
			break

	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
