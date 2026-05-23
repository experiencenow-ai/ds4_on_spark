#!/usr/bin/env python3
"""Verify the antirez ds4_cuda.cu slice-tile8 gate/up patch artifact."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import read_text_or_die
from scripts._lib.patch_verify import run_json_patch_report


REQUIRED_SNIPPETS = [
	"moe_gate_up_mid_expert_tile8_row32_slices_kernel",
	"DS4_CUDA_MOE_SLICE_TILE8",
	"DS4_CUDA_MOE_NO_SLICE_TILE8",
	"use_gate_slice_tiles",
	"gate_ptrs[expert]",
	"up_ptrs[expert]",
	"moe_build_expert_tile_offsets_kernel<<<1, 1>>>(tile_offsets, tile_total, counts, expert_tile_m)",
	"moe_build_expert_tiles_kernel<<<1, 256>>>(tile_experts, tile_starts, tile_offsets, counts, expert_tile_m)",
	"dev_dot_iq2_xxs_q8_K_block8_deq_lut",
	"use_gate_slice_tiles\\\":%u",
]


def verify_patch(path: Path) -> dict[str, object]:
	text = read_text_or_die(str(path))
	missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
	return {
		"format": "ds4-antirez-slice-tile8-gateup-patch-check-v1",
		"patch": str(path),
		"ok": len(missing) == 0,
		"missing": missing,
	}


def main() -> int:
	return run_json_patch_report(verify_patch)


if __name__ == "__main__":
	raise SystemExit(main())
