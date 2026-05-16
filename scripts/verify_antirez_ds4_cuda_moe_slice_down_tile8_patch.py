#!/usr/bin/env python3
"""Verify the antirez ds4_cuda.cu slice-down-tile8 patch artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_SNIPPETS = [
	"moe_down_expert_tile8_row32_slices_kernel",
	"DS4_CUDA_MOE_SLICE_DOWN_TILE8",
	"DS4_CUDA_MOE_NO_SLICE_DOWN_TILE8",
	"use_down_slice_tiles",
	"down_ptrs[expert]",
	"dev_dot_q2_K_q8_K_block8",
	"moe_build_expert_tile_offsets_kernel<<<1, 1>>>(tile_offsets, tile_total, counts, expert_tile_m)",
	"moe_build_expert_tiles_kernel<<<1, 256>>>(tile_experts, tile_starts, tile_offsets, counts, expert_tile_m)",
	"use_down_slice_tiles\\\":%u",
]


def verify_patch(path: Path) -> dict[str, object]:
	text = path.read_text(encoding="utf-8")
	missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
	return {
		"format": "ds4-antirez-slice-down-tile8-patch-check-v1",
		"patch": str(path),
		"ok": len(missing) == 0,
		"missing": missing,
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	result = verify_patch(Path(args.patch))
	print(json.dumps(result, indent=2, sort_keys=True))
	return 0 if result["ok"] else 1


if __name__ == "__main__":
	raise SystemExit(main())
