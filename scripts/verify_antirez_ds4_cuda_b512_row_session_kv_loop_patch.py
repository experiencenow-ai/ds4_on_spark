#!/usr/bin/env python3
"""Verify the antirez/ds4 B=512 row-session KV loop patch."""

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
	required = [
		"diff --git a/ds4.c b/ds4.c",
		"DS4_CUDA_STACK_PROBE_ROW_SESSIONS",
		"DS4_CUDA_STACK_PROBE_PREFIX_TOKENS_FILE",
		"DS4_CUDA_STACK_PROBE_SUFFIX_TOKENS_FILE",
		"DS4_CUDA_STACK_PROBE_DECODE_STEPS",
		"batch_layer_raw_cache",
		"cuda_batch_stack_probe_row_sessions",
		"cuda_batch_stack_probe_alloc_row_session_kv",
		"cuda_batch_stack_probe_row_raw_cache_view",
		"cuda_batch_stack_probe_prefill_shared_prefix",
		"cuda_batch_stack_probe_append_suffix_rows",
		"cuda_batch_stack_probe_decode_rows",
		"metal_graph_encode_decode_layer",
		"metal_graph_encode_output_head_batch",
		"committed_token_ids_by_step",
		"token_hashes_by_step",
		"per_step_decode_ms",
		"prefix_prepare_ms",
		"prefix_load_or_fork_ms",
		"suffix_prefill_ms",
		"end_to_end_output_tokens_per_s",
		"kv_update_mode\\\":\\\"present",
		"prompt_pattern\\\":\\\"shared_prefix_compact_suffix",
	]
	for needle in required:
		if needle not in patch_text:
			errors.append(f"missing expected substring: {needle!r}")
	forbidden = [
		"single_sequence_rows",
		"DS4_CUDA_STACK_PROBE_ROW_SESSIONS_DISABLED",
		"production_generation_eligible\":true",
	]
	for needle in forbidden:
		if needle in patch_text:
			errors.append(f"forbidden substring in row-session patch: {needle!r}")
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
