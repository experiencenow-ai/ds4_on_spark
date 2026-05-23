#!/usr/bin/env python3
"""Verify the antirez ds4_cuda.cu direct sum6 down patch artifact."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import read_text_or_die
from scripts._lib.patch_verify import run_json_patch_report


REQUIRED_SNIPPETS = [
	"moe_down_sum6_batch_qwarp32_slices_kernel",
	"DS4_CUDA_MOE_DIRECT_SUM6_DOWN",
	"DS4_CUDA_MOE_NO_DIRECT_SUM6_DOWN",
	"use_batch_direct_sum6_down",
	"selected[(uint64_t)tok * n_expert + slot]",
	"down_ptrs[(uint32_t)expert_i]",
	"out[(uint64_t)tok * out_dim + row]",
	"use_batch_direct_sum6_down\\\":%u",
]


def verify_patch(path: Path) -> dict[str, object]:
	text = read_text_or_die(str(path))
	missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
	return {
		"format": "ds4-antirez-direct-sum6-down-patch-check-v1",
		"patch": str(path),
		"ok": len(missing) == 0,
		"missing": missing,
	}


def main() -> int:
	return run_json_patch_report(verify_patch)


if __name__ == "__main__":
	raise SystemExit(main())
