#!/usr/bin/env python3
"""Verify the antirez/ds4 CUDA routed-MoE P2 inner profile patch."""

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
	]
	for s in required:
		if s not in patch_text:
			errors.append(f"missing expected patch substring: {s!r}")
	if "profile_moe = getenv(\"DS4_CUDA_MOE_PROFILE\") != NULL || profile_moe_inner" not in patch_text:
		errors.append("inner profile must enable the existing CUDA event path")
	return errors


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	errors = validate_patch_text(_read_text(args.patch))
	if errors:
		for e in errors:
			print(f"error: {e}", file=sys.stderr)
		raise SystemExit(2)
	print("ok=true")


if __name__ == "__main__":
	main()
