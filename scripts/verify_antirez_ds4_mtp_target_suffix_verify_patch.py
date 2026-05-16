#!/usr/bin/env python3
"""Verify the antirez/ds4 MTP target-suffix verifier architecture patch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def validate_patch_text(text: str) -> list[str]:
	errors: list[str] = []
	added = "\n".join(
		line[1:]
		for line in text.splitlines()
		if line.startswith("+") and not line.startswith("+++ ")
	)
	required = [
		"typedef struct",
		"ds4_mtp_decode2_stats",
		"target_verifier_invocation_count",
		"target_positions_verified",
		"static bool metal_graph_decode2_fused_output_head(",
		"metal_graph_encode_output_head_batch(g, model, weights, 2, weights->output->dim[1])",
		"stats->target_verifier_invocation_count++;",
		"stats->target_eval_call_count++;",
		"stats->target_positions_verified += 2;",
		"metal_graph_decode2_fused_output_head(g, model, weights, cur0, cur1, top0, logits1, stats)",
		"NULL,\n                                                  row_logits,\n                                                  &decode2_stats);",
		"verifier_calls=%d target_positions=%d target_calls=%d",
	]
	for needle in required:
		if needle not in added:
			errors.append(f"missing expected added substring: {needle!r}")
	for forbidden in [
		"DS4_MTP_DRAFT=4",
		"draft_n == 4",
		"cross_spark",
		"DS4_CUDA_MOE_SLICE",
		"metal_graph_verify_decode2_exact(g,model,weights,draft0,draft1,start_pos",
		"out->staged_kv_ready = false;",
		"row0_logits = xmalloc",
	]:
		if forbidden in added:
			errors.append(f"forbidden architecture creep in patch: {forbidden!r}")
	return errors


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	errors = validate_patch_text(Path(args.patch).read_text(encoding="utf-8"))
	if errors:
		for error in errors:
			print(f"error: {error}", file=sys.stderr)
		return 2
	print("ok=true")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
