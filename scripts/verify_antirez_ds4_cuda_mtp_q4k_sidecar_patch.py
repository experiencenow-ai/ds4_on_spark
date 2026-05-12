#!/usr/bin/env python3
"""Verify that the antirez/ds4 CUDA MTP Q4_K sidecar patch is present.

This verifier is intentionally lightweight: it does not require cloning/building
`antirez/ds4`. It checks that the patch file includes the critical changes that
made the DeepSeek V4 Flash MTP sidecar usable on the Spark CUDA path:

- prevent secondary (sidecar) maps from clobbering trunk CUDA map/fd-cache state
- accept routed-MoE down experts in Q4_K and run a Q4_K dot fallback on CUDA
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
		"diff --git a/ds4.c b/ds4.c",
		"diff --git a/ds4_cuda.cu b/ds4_cuda.cu",
		"diff --git a/ds4_gpu.h b/ds4_gpu.h",
		"ds4_gpu_set_model_map_range_secondary",
		"typedef struct {",
		"} cuda_block_q4_K;",
		"__device__ __forceinline__ static void dev_get_scale_min_k4(",
		"__device__ static float dev_q4_K_dot_f32(",
		"__global__ static void moe_down_q4_f32_kernel(",
		"if (gate_type != 16u) return 0;",
		"if (down_type != 10u && down_type != 12u) return 0;",
		"if (down_type == 12u) {",
		"moe_down_q4_f32_kernel<<<dgrid, 256>>>",
	]

	for s in required_substrings:
		if s not in patch_text:
			errors.append(f"missing expected substring: {s!r}")

	# Guardrail: make sure we actually gate the trunk-only fast paths on (model_map == g_model_host_base).
	trunk_map_markers = [
		"model_map == g_model_host_base",
		"if (model_map == g_model_host_base && getenv(\"DS4_CUDA_NO_FD_CACHE\") == NULL)",
	]
	for s in trunk_map_markers:
		if s not in patch_text:
			errors.append(f"missing expected trunk-map guard marker: {s!r}")

	# Guardrail: avoid adding more uses of the old map-range function in the sidecar callsite.
	if any("ds4_gpu_set_model_map_range(e->mtp_model.map" in line for line in added_lines):
		errors.append("found ds4_gpu_set_model_map_range(...) on an added line; expected secondary map setter")

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

