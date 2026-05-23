#!/usr/bin/env python3
"""Verify that the antirez/ds4 CUDA multi-model cache patch is complete.

This verifier is intentionally lightweight: it does not require cloning/building
`antirez/ds4`. It just checks that the patch file includes the critical cache
keying changes needed to avoid trunk/sidecar aliasing under CUDA weight caching,
and that MTP no longer disables the trunk startup cache preparation.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import added_patch_lines
from scripts._lib.patch_verify import require_substrings
from scripts._lib.patch_verify import run_patch_verifier


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	added_lines = added_patch_lines(patch_text)
	require_substrings(errors, patch_text, [
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
		"-        if (!e->mtp_ready && !accelerator_cache_model_tensors(e->backend, &e->model)) {",
		"DS4_CUDA_MTP_CACHE_AUTO_LIMIT",
		"DS4_CUDA_WEIGHT_ARENA_CHUNK_MB",
		"setenv(\"DS4_CUDA_WEIGHT_ARENA_CHUNK_MB\", \"512\", 0)",
		"ds4: accelerator stopped startup model cache after %.2f GiB at tensor span",
		"const bool cache_best_effort =",
		"+        if (!accelerator_cache_model_tensors(e->backend, &e->model, cache_best_effort)) {",
		"diff --git a/ds4_gpu.h b/ds4_gpu.h",
		"int ds4_gpu_set_model_fd_for_map(const void *model_map, int fd);",
		"DS4_CUDA_WEIGHT_CACHE_SYNC",
	])

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

	legacy_mtp_cache_skip = "if (!e->mtp_ready && !accelerator_cache_model_tensors(e->backend, &e->model)) {"
	if any(legacy_mtp_cache_skip in line for line in added_lines):
		errors.append("found legacy MTP startup-cache skip on an added line")

	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
