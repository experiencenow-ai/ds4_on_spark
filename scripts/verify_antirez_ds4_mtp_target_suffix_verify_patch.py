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
		"ds4_mtp_suffix2_result",
		"static bool target_suffix_verify_k2(",
		"int32_t draft_tokens[2];",
		"staged_kv_ready",
		"has_continuation_logits",
		"metal_graph_verify_decode2_exact(g,model,weights,draft0,draft1,start_pos",
		"out->accepted_count = (row0_top == draft1) ? 2 : 1;",
		"out->staged_kv_ready = false;",
		"ok = target_suffix_verify_k2(&s->graph,",
		"suffix2.accepted_count == 2",
	]
	for needle in required:
		if needle not in added:
			errors.append(f"missing expected added substring: {needle!r}")
	for forbidden in [
		"DS4_MTP_DRAFT=4",
		"draft_n == 4",
		"cross_spark",
		"DS4_CUDA_MOE_SLICE",
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
