#!/usr/bin/env python3
"""Verify the antirez/ds4 explicit stage preload patch."""

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
		if not line.startswith("+") or line.startswith("+++ "):
			continue
		added_lines.append(line[1:])
	added_text = "\n".join(added_lines)
	required_substrings = [
		"diff --git a/ds4_gpu.h b/ds4_gpu.h",
		"diff --git a/ds4_cuda.cu b/ds4_cuda.cu",
		"diff --git a/ds4.c b/ds4.c",
		"ds4_gpu_preload_model_range",
		"cuda_model_arena_alloc(bytes, what)",
		"cuda_model_stage_pool_alloc(stage_bytes, stage_align)",
		"cuda_model_stage_read(model_map, g_model_stage[0]",
		"cudaMemcpy(dev + copied, payload",
		"cudaDeviceSynchronize()",
		"g_model_ranges.push_back({model_map, offset, bytes, dev",
		"cuda_model_offset_key{model_map, cuda_model_fd_for_map(model_map), offset}",
		"cuda_stack_probe_preload_sleep_us()",
		"stack_stage_l%u_%s",
		"ffn_gate_exps",
		"ffn_up_exps",
		"ffn_down_exps",
	]
	for s in required_substrings:
		if s not in patch_text:
			errors.append(f"missing expected substring: {s!r}")
	required_added_substrings = [
		"int ds4_gpu_preload_model_range(",
		"const uint64_t stage_bytes = chunk_bytes + stage_align;",
		"cuda_model_drop_file_pages(model_map, offset + copied, n);",
		"cuda_model_discard_source_pages(model_map, model_size, offset + copied, n);",
		"cuda_stack_probe_tensor_entry",
		"tensors[i].name",
	]
	for s in required_added_substrings:
		if s not in added_text:
			errors.append(f"missing expected added substring: {s!r}")
	for forbidden in ["spark_count", "num_sparks", "world_size"]:
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
