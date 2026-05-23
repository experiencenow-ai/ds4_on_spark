#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA stage handoff patch."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import require_substrings
from scripts._lib.patch_verify import run_patch_verifier


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	require_substrings(errors, patch_text, [
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
	])
	for forbidden in ["spark_count", "num_sparks", "world_size"]:
		if forbidden in patch_text:
			errors.append(f"patch should not hardcode topology field: {forbidden}")
	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
