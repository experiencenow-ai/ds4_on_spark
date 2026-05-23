#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA routed-MoE P2 inner profile patch."""

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
		"DS4_CUDA_MOE_P2_INNER_PROFILE",
		"uint32_t write_aux,",
		"if (write_aux) {",
		"write_gate_up,",
		"cudaEvent_t prof_ev[8]",
		"cudaEventElapsedTime(&ms_queue, prof_ev[1], prof_ev[2])",
		"cudaEventElapsedTime(&ms_ptr, prof_ev[2], prof_ev[3])",
		"cudaEventElapsedTime(&ms_gate, prof_ev[3], prof_ev[4])",
		"cudaEventElapsedTime(&ms_midq, prof_ev[4], prof_ev[5])",
		"cudaEventElapsedTime(&ms_down, prof_ev[5], prof_ev[6])",
		"cudaEventElapsedTime(&ms_sum, prof_ev[6], prof_ev[7])",
		"ds4: CUDA MoE P2 inner profile",
		"\\\"format\\\":\\\"ds4-moe-p2-inner-event-v1\\\"",
		"\\\"queue_build_ms\\\":%.3f",
		"\\\"pointer_table_or_descriptor_ms\\\":%.3f",
		"\\\"gate_up_ms\\\":%.3f",
		"\\\"activation_or_quantize_ms\\\":%.3f",
		"\\\"down_ms\\\":%.3f",
		"\\\"accumulate_or_scatter_ms\\\":%.3f",
		"\\\"total_routed_moe_ms\\\":%.3f",
	], "expected patch substring")
	if "profile_moe = getenv(\"DS4_CUDA_MOE_PROFILE\") != NULL || profile_moe_inner" not in patch_text:
		errors.append("inner profile must enable the existing CUDA event path")
	return errors


def main() -> None:
	run_patch_verifier(validate_patch_text)


if __name__ == "__main__":
	main()
