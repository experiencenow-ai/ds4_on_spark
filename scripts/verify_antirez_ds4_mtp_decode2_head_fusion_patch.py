#!/usr/bin/env python3
"""Verify the antirez/ds4 MTP decode2 output-head fusion patch."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import added_patch_text
from scripts._lib.patch_verify import removed_patch_text
from scripts._lib.patch_verify import require_substrings
from scripts._lib.patch_verify import run_patch_verifier


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	added = added_patch_text(patch_text)
	removed = removed_patch_text(patch_text)
	require_substrings(errors, added, [
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
	], "expected added substring")
	for needle in [
		"g->cur_hc = cur0;",
		"g->cur_hc = cur1;",
	]:
		if needle not in removed:
			errors.append(f"missing expected removed substring: {needle!r}")
	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
