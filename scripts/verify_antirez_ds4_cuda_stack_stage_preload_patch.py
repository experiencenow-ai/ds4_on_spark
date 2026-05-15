#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA stack stage preload patch."""

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
	added_lines: list[str] = []
	for line in patch_text.splitlines():
		if not line.startswith("+"):
			continue
		if line.startswith("+++ "):
			continue
		added_lines.append(line[1:])
	added_text = "\n".join(added_lines)
	required_substrings = [
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
	]
	for s in required_substrings:
		if s not in patch_text:
			errors.append(f"missing expected substring: {s!r}")
	required_added_substrings = [
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
	]
	for s in required_added_substrings:
		if s not in added_text:
			errors.append(f"missing expected added substring: {s!r}")
	for forbidden in ["spark_count", "num_sparks"]:
		if forbidden in patch_text:
			errors.append(f"patch should not hardcode topology field: {forbidden}")
	return errors


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	patch_text = _read_text(args.patch)
	errors = validate_patch_text(patch_text)
	if errors:
		for e in errors[:64]:
			print(f"error: {e}", file=sys.stderr)
		raise SystemExit(2)
	print("ok=true")


if __name__ == "__main__":
	main()
