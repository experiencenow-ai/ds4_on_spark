#!/usr/bin/env python3
"""Verify that the antirez/ds4 CUDA multi-model cache patch is complete.

This verifier is intentionally lightweight: it does not require cloning/building
`antirez/ds4`. It just checks that the patch file includes the critical cache
keying changes needed to avoid trunk/sidecar aliasing under CUDA weight caching.
"""

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

	required_substrings = [
		"diff --git a/ds4_cuda.cu b/ds4_cuda.cu",
		"struct cuda_model_file_state {",
		"static std::unordered_map<const void *, cuda_model_file_state> g_model_file_state_by_base;",
		"static cuda_model_file_state *cuda_model_file_state_mut(const void *model_map);",
		"static int cuda_model_fd_for_map(const void *model_map);",
		"static uint64_t cuda_model_direct_align_for_map(const void *model_map);",
		"extern \"C\" int ds4_gpu_set_model_fd_for_map(const void *model_map, int fd) {",
		"struct cuda_model_offset_key {",
		"const void *host_base;",
		"int fd;",
		"uint64_t offset;",
		"struct cuda_model_offset_key_hash {",
		"static std::unordered_map<cuda_model_offset_key, size_t, cuda_model_offset_key_hash> g_model_range_by_key;",
		"static std::unordered_map<cuda_model_offset_key, size_t, cuda_model_offset_key_hash> g_q8_f16_by_key;",
		"static std::unordered_map<cuda_model_offset_key, size_t, cuda_model_offset_key_hash> g_q8_f32_by_key;",
		"static void cuda_model_drop_file_pages(const void *model_map, uint64_t offset, uint64_t bytes) {",
		"static int cuda_model_stage_pool_alloc(uint64_t bytes, uint64_t align) {",
		"static int cuda_model_stage_read(const void *model_map, void *stage, uint64_t stage_bytes,",
		"g_model_stage_align",
		"g_model_range_by_key.clear();",
		"g_q8_f16_by_key.clear();",
		"g_q8_f32_by_key.clear();",
		"Keep the largest cached range per (map,fd,offset) to avoid thrashing.",
		"g_model_ranges[it->second].bytes < bytes",
		"diff --git a/ds4.c b/ds4.c",
		"ds4_gpu_set_model_fd_for_map(e->mtp_model.map, e->mtp_model.fd)",
		"diff --git a/ds4_gpu.h b/ds4_gpu.h",
		"int ds4_gpu_set_model_fd_for_map(const void *model_map, int fd);",
		"if (getenv(\"DS4_CUDA_NO_FD_CACHE\") == NULL) {",
	]

	for s in required_substrings:
		if s not in patch_text:
			errors.append(f"missing expected substring: {s!r}")

	# The patch must show at least one callsite constructing a key with (model_map, fd_for_map(model_map), offset).
	key_ctor_markers = [
		"cuda_model_offset_key k{model_map, cuda_model_fd_for_map(model_map), offset};",
		"cuda_model_offset_key{model_map, cuda_model_fd_for_map(model_map), offset}",
	]
	if not any(m in patch_text for m in key_ctor_markers):
		errors.append("missing expected (model_map, cuda_model_fd_for_map(model_map), offset) key construction marker")

	# Guardrail: the legacy maps should not remain in the patch in the obvious form.
	legacy_markers = [
		"g_model_range_by_offset",
		"g_q8_f16_by_offset",
		"g_q8_f32_by_offset",
	]
	for s in legacy_markers:
		if any(s in line for line in added_lines):
			errors.append(f"found legacy offset-only cache symbol on an added line: {s!r}")

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
