#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA batched expert-tile slice patch.

This verifier checks the second real expert-queue step: batched MoE slice
caching must not fall out of the high-throughput expert-tile kernels. The patch
keeps one tiled kernel family and gives it optional per-expert pointer tables.
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

	added_text = "\n".join(added_lines)
	required_patch_substrings = [
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
	]
	for s in required_patch_substrings:
		if s not in patch_text:
			errors.append(f"missing expected patch substring: {s!r}")

	required_added_substrings = [
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
	]
	for s in required_added_substrings:
		if s not in added_text:
			errors.append(f"missing expected added substring: {s!r}")

	for line in added_lines:
		if "use_expert_tiles =" in line and "!use_batched_expert_slices" in line:
			errors.append("batched expert slices must not disable expert tiles")
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
