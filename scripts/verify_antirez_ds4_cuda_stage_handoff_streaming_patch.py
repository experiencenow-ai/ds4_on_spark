#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA stage handoff streaming patch."""

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
		"DS4_CUDA_STACK_PROBE_INPUT_WAIT_MS",
		"cuda_stack_probe_format_boundary_path",
		"cuda_batch_stack_probe_write_output",
		"iter_ms",
		"out_fnv64s",
		"out_nonfinites",
		"logits_fnv64s",
		"logits_nonfinites",
		"stat(path, &st)",
		"read_f32_binary_file(path, host_hc, hc_floats)",
		"write_f32_binary_file(path, host_out, hc_floats)",
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
