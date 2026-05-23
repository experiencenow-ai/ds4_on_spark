#!/usr/bin/env python3
"""Verify that the antirez/ds4 CUDA MTP Q4_K sidecar patch is present.

This verifier is intentionally lightweight: it does not require cloning/building
`antirez/ds4`. It checks that the patch file includes the critical changes that
made the DeepSeek V4 Flash MTP sidecar usable on the Spark CUDA path:

- prevent secondary (sidecar) maps from clobbering trunk CUDA map/fd-cache state
- accept routed-MoE gate/up/down experts in Q4_K and run a Q4_K dot fallback on CUDA
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
		"diff --git a/ds4.c b/ds4.c",
		"diff --git a/ds4_cuda.cu b/ds4_cuda.cu",
		"e->mtp_ready && getenv(\"DS4_MTP_SET_MODEL_MAP\") != NULL",
		"typedef struct {",
		"} cuda_block_q4_K;",
		"__device__ __forceinline__ static uint32_t dev_u32le_load(",
		"__device__ __forceinline__ static uint8_t dev_u32_byte(",
		"__device__ static float dev_q4_K_dot_f32(",
		"const uint32_t kmask1 = 0x3f3f3f3fu;",
		"const uint32_t kmask2 = 0x0f0f0f0fu;",
		"const uint32_t kmask3 = 0x03030303u;",
		"const uint32_t sc0 = u0 & kmask1;",
		"const uint32_t sc1 = (u2 & kmask2) | (((u0 >> 6) & kmask3) << 4);",
		"const uint32_t mn0 = u1 & kmask1;",
		"const uint32_t mn1 = ((u2 >> 4) & kmask2) | (((u1 >> 6) & kmask3) << 4);",
		"const uint32_t base = (g >> 1) * 32u;",
		"xf[g * 32u + i]",
		"__global__ static void moe_gate_up_mid_q4_f32_kernel(",
		"__global__ static void moe_down_q4_f32_kernel(",
		"const uint32_t fast_iq2_q2 = gate_type == 16u && down_type == 10u;",
		"const uint32_t slow_q4 = gate_type == 12u && down_type == 12u;",
		"if (!fast_iq2_q2 && !slow_q4) return 0;",
		"moe_gate_up_mid_q4_f32_kernel<<<mgrid, 256>>>",
		"moe_down_q4_f32_kernel<<<dgrid, 256>>>",
	])

	# Guardrail: make sure we actually gate the trunk-only fast paths on (model_map == g_model_host_base).
	trunk_map_markers = [
		"model_map == g_model_host_base",
		"if (model_map == g_model_host_base && getenv(\"DS4_CUDA_NO_FD_CACHE\") == NULL)",
	]
	for s in trunk_map_markers:
		if s not in patch_text:
			errors.append(f"missing expected trunk-map guard marker: {s!r}")

	# Guardrail: the sidecar map call may stay available for explicit debugging, but it must be gated.
	if any("ds4_gpu_set_model_map_range(e->mtp_model.map" in line for line in added_lines):
		if "DS4_MTP_SET_MODEL_MAP" not in patch_text:
			errors.append("found MTP map-range setter without the explicit DS4_MTP_SET_MODEL_MAP debug gate")

	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
