#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA stage handoff patch."""

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
		"DS4_CUDA_STACK_PROBE_INPUT_HC_FILE",
		"DS4_CUDA_STACK_PROBE_OUTPUT_HC_FILE",
		"DS4_CUDA_STACK_PROBE_EMBED_INPUT",
		"cuda_batch_stack_probe_seed_input",
		"read_f32_binary_file(input_file, host_hc, hc_floats)",
		"write_f32_binary_file(output_file, (const float *)host_out",
		"metal_graph_upload_prompt_embeddings_hc",
		"boundary_layout",
		"boundary_dtype",
		"boundary_bytes",
		"boundary_input_file",
		"boundary_output_file",
		"embedding_input",
	]
	for needle in required:
		if needle not in patch_text:
			errors.append(f"missing expected substring: {needle!r}")
	for forbidden in ["spark_count", "num_sparks", "world_size"]:
		if forbidden in patch_text:
			errors.append(f"patch should not hardcode topology field: {forbidden}")
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
