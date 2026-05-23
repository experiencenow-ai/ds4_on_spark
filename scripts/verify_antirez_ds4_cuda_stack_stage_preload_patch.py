#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA stack stage preload patch."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import added_patch_text
from scripts._lib.patch_verify import require_substrings
from scripts._lib.patch_verify import run_patch_verifier


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	added_text = added_patch_text(patch_text)
	require_substrings(errors, patch_text, [
		"diff --git a/ds4.c b/ds4.c",
		"DS4_CUDA_STACK_PROBE_LAYER_BEGIN",
		"DS4_CUDA_STACK_PROBE_LAYER_END",
		"DS4_CUDA_STACK_PROBE_PRELOAD_STAGE",
		"DS4_CUDA_STACK_PROBE_PRELOAD_CHUNK_MB",
		"DS4_CUDA_STACK_PROBE_PRELOAD_SLEEP_US",
		"cuda_stack_probe_layer_begin()",
		"cuda_stack_probe_layer_end()",
		"cuda_stack_probe_stage_has_head()",
		"cuda_stack_probe_preload_chunk_bytes()",
		"cuda_stack_probe_preload_pause()",
		"cuda_stack_probe_preload_layer(",
		"cuda_stack_probe_preload_stage(",
		"for (uint32_t il = begin; ok && il < end; il++)",
		"for (uint32_t il = begin; il < end; il++)",
		"includes_one_output_head",
		"including routed experts",
	])
	require_substrings(errors, added_text, [
		"layer->attn_q_a",
		"layer->attn_output_b",
		"layer->ffn_gate_inp",
		"layer->ffn_gate_exps",
		"layer->ffn_up_exps",
		"layer->ffn_down_exps",
		"weights->output_hc_base",
		"weights->output_norm",
		"weights->output",
		"if (cuda_stack_probe_preload_stage_enabled())",
		"memset(&g, 0, sizeof(g));",
		"if (ok) ok = metal_graph_alloc_raw_cap(&g, weights, &weights->layer[0], raw_cap, ctx_size, n_tokens, false);",
		"cuda_stack_probe_layer_end() - cuda_stack_probe_layer_begin()",
	], "expected added substring")
	for forbidden in ["spark_count", "num_sparks"]:
		if forbidden in patch_text:
			errors.append(f"patch should not hardcode topology field: {forbidden}")
	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
