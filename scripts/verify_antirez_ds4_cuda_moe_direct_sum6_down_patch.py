#!/usr/bin/env python3
"""Verify the antirez ds4_cuda.cu direct sum6 down patch artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


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
	text = path.read_text(encoding="utf-8")
	missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
	return {
		"format": "ds4-antirez-direct-sum6-down-patch-check-v1",
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
