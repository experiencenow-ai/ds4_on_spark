#!/usr/bin/env python3
"""Preflight DS4 Flash vLLM memory pressure before starting the server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0,str(REPO_ROOT))

from scripts import vllm_ds4_flash_launch_guard as launch_guard


FORMAT = "ds4-vllm-memory-safety-preflight-v1"
BAD = "blocked"
OK = "passed"
WARN = "warn"
DS4_FLASH_KV_GIB_PER_200K_REQUEST = 13.83
DS4_FLASH_REFERENCE_TOKENS = 200000
DS4_FLASH_SAFE_MAX_BATCHED_TOKENS = 8192
EVIDENCE_REF = "fixtures/vllm_config_tuning/vllm_deepseek_v4_flash_tp2_custom_transfer_tuning_20260521.example.json"


def estimate_kv_gib(max_model_len: int) -> float:
	return((float(max_model_len) / float(DS4_FLASH_REFERENCE_TOKENS)) * DS4_FLASH_KV_GIB_PER_200K_REQUEST)


def optional_float(value: str | None) -> float | None:
	if value is None:
		return(None)
	return(float(value))


def choose_free_gib(gpu_free_gib: float | None, gpu_total_gib: float | None, gpu_used_gib: float | None) -> float | None:
	if gpu_free_gib is not None:
		return(gpu_free_gib)
	if gpu_total_gib is not None and gpu_used_gib is not None:
		return(max(0.0,(gpu_total_gib - gpu_used_gib)))
	return(None)


def issue(kind: str, detail: str) -> dict[str, str]:
	return({"kind": kind, "detail": detail})


def status_from(issues: list[dict[str, str]], warnings: list[dict[str, str]]) -> str:
	if issues:
		return(BAD)
	if warnings:
		return(WARN)
	return(OK)


def recommended_action(status: str, issues: list[dict[str, str]]) -> str:
	kinds = {item["kind"] for item in issues}
	if "kv_request_exceeds_available" in kinds:
		return("do not start vLLM; reduce max_model_len, reduce concurrency profile, or free enough KV headroom before launch")
	if "runtime_gpu_memory_hard_floor" in kinds:
		return("drain/refuse new work and terminate the vLLM worker before CUDA reaches driver-level OOM")
	if "launch_guard_blocked" in kinds:
		return("fix the launch profile rejected by scripts/vllm_ds4_flash_launch_guard.py before memory preflight")
	if status == WARN:
		return("launch only with a measured memory sample or an operator-accepted dry run")
	return("launch profile passed memory preflight")


def evaluate_preflight(
	launch_result: dict[str, Any],
	available_kv_gib: float | None = None,
	gpu_total_gib: float | None = None,
	gpu_used_gib: float | None = None,
	gpu_free_gib: float | None = None,
	min_free_gib: float = 8.0,
	kv_headroom_ratio: float = 0.10,
	require_memory_sample: bool = False,
	runtime_free_gib: float | None = None,
	runtime_soft_min_free_gib: float = 10.0,
	runtime_hard_min_free_gib: float = 6.0,
) -> dict[str, Any]:
	effective = launch_result.get("effective", {})
	max_model_len = int(effective.get("max_model_len") or 0)
	max_num_batched_tokens = int(effective.get("max_num_batched_tokens") or 0)
	max_num_seqs = int(effective.get("max_num_seqs") or 0)
	model = str(launch_result.get("model_family_detected") or "unknown")
	estimated_kv_gib = estimate_kv_gib(max_model_len) if max_model_len > 0 else 0.0
	required_kv_with_headroom = (estimated_kv_gib * (1.0 + kv_headroom_ratio))
	free_gib = choose_free_gib(gpu_free_gib,gpu_total_gib,gpu_used_gib)
	issues: list[dict[str, str]] = []
	warnings: list[dict[str, str]] = []
	if launch_result.get("status") == launch_guard.BAD:
		issues.append(issue("launch_guard_blocked","base launch guard rejected the profile before memory preflight"))
	if require_memory_sample and available_kv_gib is None and free_gib is None:
		issues.append(issue("memory_sample_required","no available KV or GPU free-memory sample was provided"))
	elif available_kv_gib is None and free_gib is None:
		warnings.append(issue("memory_sample_missing","preflight could not compare estimate against live available memory"))
	if available_kv_gib is not None and required_kv_with_headroom > available_kv_gib:
		issues.append(issue("kv_request_exceeds_available",f"estimated one max-length request needs {required_kv_with_headroom:.2f} GiB KV with headroom, available KV is {available_kv_gib:.2f} GiB"))
	if free_gib is not None and free_gib < min_free_gib:
		issues.append(issue("gpu_free_memory_below_floor",f"GPU free memory {free_gib:.2f} GiB is below launch floor {min_free_gib:.2f} GiB"))
	if runtime_free_gib is not None:
		if runtime_free_gib < runtime_hard_min_free_gib:
			issues.append(issue("runtime_gpu_memory_hard_floor",f"runtime GPU free memory {runtime_free_gib:.2f} GiB is below hard floor {runtime_hard_min_free_gib:.2f} GiB"))
		elif runtime_free_gib < runtime_soft_min_free_gib:
			warnings.append(issue("runtime_gpu_memory_soft_floor",f"runtime GPU free memory {runtime_free_gib:.2f} GiB is below soft floor {runtime_soft_min_free_gib:.2f} GiB"))
	if model == "deepseek_v4_flash" and max_model_len >= 200000 and max_num_seqs >= 512 and max_num_batched_tokens > DS4_FLASH_SAFE_MAX_BATCHED_TOKENS:
		issues.append(issue("scheduler_token_cap_above_measured_safe_limit",f"DS4 Flash 200k/c512 should not exceed {DS4_FLASH_SAFE_MAX_BATCHED_TOKENS} max batched tokens without new evidence"))
	status = status_from(issues,warnings)
	return({
		"format": FORMAT,
		"status": status,
		"model_family_detected": model,
		"evidence_ref": EVIDENCE_REF,
		"effective": effective,
		"memory_sample": {
			"available_kv_gib": available_kv_gib,
			"gpu_total_gib": gpu_total_gib,
			"gpu_used_gib": gpu_used_gib,
			"gpu_free_gib": free_gib,
			"runtime_free_gib": runtime_free_gib,
		},
		"estimates": {
			"kv_gib_per_200k_request": DS4_FLASH_KV_GIB_PER_200K_REQUEST,
			"estimated_one_request_kv_gib": round(estimated_kv_gib,3),
			"required_kv_gib_with_headroom": round(required_kv_with_headroom,3),
			"estimated_full_context_concurrency": None if available_kv_gib is None or estimated_kv_gib <= 0 else round((available_kv_gib / estimated_kv_gib),3),
		},
		"issues": issues,
		"warnings": warnings,
		"recommended_action": recommended_action(status,issues),
	})


def evaluate_path(path: Path, **kwargs: Any) -> dict[str, Any]:
	launch_result = launch_guard.validate_path(path)
	result = evaluate_preflight(launch_result, **kwargs)
	result["path"] = str(path)
	result["launch_guard_status"] = launch_result.get("status")
	result["launch_guard_issues"] = launch_result.get("issues", [])
	return(result)


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("path", type=Path)
	p.add_argument("--available-kv-gib", type=float)
	p.add_argument("--gpu-total-gib", type=float)
	p.add_argument("--gpu-used-gib", type=float)
	p.add_argument("--gpu-free-gib", type=float)
	p.add_argument("--min-free-gib", type=float, default=8.0)
	p.add_argument("--kv-headroom-ratio", type=float, default=0.10)
	p.add_argument("--require-memory-sample", action="store_true")
	p.add_argument("--runtime-free-gib", type=float)
	p.add_argument("--runtime-soft-min-free-gib", type=float, default=10.0)
	p.add_argument("--runtime-hard-min-free-gib", type=float, default=6.0)
	return(p.parse_args())


def main() -> int:
	args = parse_args()
	result = evaluate_path(
		args.path,
		available_kv_gib=args.available_kv_gib,
		gpu_total_gib=args.gpu_total_gib,
		gpu_used_gib=args.gpu_used_gib,
		gpu_free_gib=args.gpu_free_gib,
		min_free_gib=args.min_free_gib,
		kv_headroom_ratio=args.kv_headroom_ratio,
		require_memory_sample=args.require_memory_sample,
		runtime_free_gib=args.runtime_free_gib,
		runtime_soft_min_free_gib=args.runtime_soft_min_free_gib,
		runtime_hard_min_free_gib=args.runtime_hard_min_free_gib,
	)
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0 if result["status"] != BAD else 2)


if __name__ == "__main__":
	raise SystemExit(main())
