#!/usr/bin/env python3
"""Verify the antirez/ds4 MTP decode2 output-head fusion patch."""

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
	added = "\n".join(
		line[1:]
		for line in patch_text.splitlines()
		if line.startswith("+") and not line.startswith("+++ ")
	)
	removed = "\n".join(
		line[1:]
		for line in patch_text.splitlines()
		if line.startswith("-") and not line.startswith("--- ")
	)
	required_added = [
		"static bool metal_graph_decode2_fused_output_head(",
		"ds4_gpu_tensor_copy(g->batch_cur_hc,",
		"metal_graph_encode_output_head_batch(g, model, weights, 2, weights->output->dim[1])",
		"ds4_gpu_indexer_topk_tensor(g->comp_selected,",
		"g->spec_logits",
		"DS4_N_VOCAB",
		"1,\n                                             1) != 0",
		"stats->output_head_call_count++;",
		"stats->output_head_rows += 2;",
		"stats->full_vocab_logits_rows++;",
		"stats->top1_only_rows++;",
		"head_rows=%d full_vocab_rows=%d top1_rows=%d",
		"decode2_stats.output_head_rows",
		"decode2_stats.full_vocab_logits_rows",
		"decode2_stats.top1_only_rows",
	]
	for needle in required_added:
		if needle not in added:
			errors.append(f"missing expected added substring: {needle!r}")
	for needle in [
		"g->cur_hc = cur0;",
		"g->cur_hc = cur1;",
	]:
		if needle not in removed:
			errors.append(f"missing expected removed substring: {needle!r}")
	return errors


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	errors = validate_patch_text(_read_text(args.patch))
	if errors:
		for error in errors:
			print(f"error: {error}", file=sys.stderr)
		raise SystemExit(2)
	print("ok=true")


if __name__ == "__main__":
	main()
