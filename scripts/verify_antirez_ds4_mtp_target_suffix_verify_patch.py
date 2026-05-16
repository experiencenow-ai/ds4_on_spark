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
		"const bool use_target_suffix2 =",
		"draft_n == 2 && getenv(\"DS4_MTP_SERIAL_SUFFIX\") == NULL;",
		"token_vec_push(&s->checkpoint, drafts[0]);",
		"token_vec_push(&s->checkpoint, drafts[1]);",
		"metal_graph_verify_suffix_tops(&s->graph",
		"const double snapshot_done = snapshot_t0;",
		"metal_graph_read_spec_logits_row(&s->graph, 1, row_logits)",
		"ds4_gpu_matmul_q8_0_top1_tensor",
		"metal_graph_encode_output_head_suffix2_top1",
		"DS4_MTP_ROW0_TOP1_HEAD",
		"metal_graph_materialize_suffix_logits_row(&s->graph",
		"metal_graph_read_spec_logits_row(&s->graph, 0, row_logits)",
		"verifier_calls=1 target_positions=2 target_calls=1 head_calls=1",
		"row0_top1_head ? 1 : 2",
		"row0_top1_head ? 1 : 0",
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
		"spec_frontier_snapshot(&frontier, s)",
		"spec_frontier_free(&frontier)",
		"spec_frontier_restore(&frontier, s)",
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
