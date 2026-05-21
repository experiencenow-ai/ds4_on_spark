#!/usr/bin/env python3
"""Compare vLLM sweep and live qualification throughput evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any


FORMAT = "centaur-standard-runtime-model-benchmark-v1"


def utc_now() -> str:
	return(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def read_json(path: Path) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as f:
		obj = json.load(f)
	if not isinstance(obj, dict):
		raise ValueError(f"{path} must contain a JSON object")
	return(obj)


def sha256_file(path: Path) -> str:
	return("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())


def as_float(value: Any, default: float = 0.0) -> float:
	if isinstance(value, bool):
		return(default)
	try:
		return(float(value))
	except (TypeError, ValueError):
		return(default)


def as_int(value: Any, default: int = 0) -> int:
	if isinstance(value, bool):
		return(default)
	try:
		return(int(value))
	except (TypeError, ValueError):
		return(default)


def prompt_tokens_from_shape(shape: str, concurrency: int) -> int | None:
	match = re.search(r"(\d+)_prompt_tokens", shape)
	if match is None:
		return(None)
	return(int(match.group(1)) * concurrency)


def standard_concurrency_summary(artifact: dict[str, Any], concurrency: int) -> dict[str, Any]:
	for item in artifact.get("concurrency_summaries", []):
		if isinstance(item, dict) and as_int(item.get("concurrency")) == concurrency:
			return(item)
	raise ValueError(f"standard benchmark missing concurrency={concurrency}")


def raw_summary(artifact: dict[str, Any], concurrency: int) -> dict[str, Any]:
	for item in artifact.get("summaries", []):
		if isinstance(item, dict) and as_int(item.get("concurrency")) == concurrency:
			return(item)
	raise ValueError(f"raw fanout artifact missing concurrency={concurrency}")


def source_ref(path: Path, display_path: str = "") -> dict[str, str]:
	return({"path": display_path or path.as_posix(), "sha256": sha256_file(path)})


def canonical_hash(obj: dict[str, Any]) -> str:
	payload = dict(obj)
	payload.pop("artifact_sha256", None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
	return(hashlib.sha256(data).hexdigest())


def build_diff(args: argparse.Namespace) -> dict[str, Any]:
	concurrency = args.concurrency
	reference_path = Path(args.reference_sweep)
	qualification_path = Path(args.qualification)
	matched_path = Path(args.matched_workload)
	reference = read_json(reference_path)
	qualification = read_json(qualification_path)
	matched = read_json(matched_path)
	reference_summary = standard_concurrency_summary(reference, concurrency)
	matched_summary = raw_summary(matched, concurrency)
	reference_tps = as_float(reference_summary.get("mean_aggregate_tps"))
	qualification_tps = as_float(qualification.get("measured_aggregate_tok_s"))
	matched_tps = as_float(matched_summary.get("mean_aggregate_tps"))
	reference_prompt_shape = str(reference.get("prompt_shape") or "")
	reference_prompt_tokens = prompt_tokens_from_shape(reference_prompt_shape, concurrency)
	matched_prompt_tokens = as_int(matched_summary.get("total_prompt_tokens"))
	qualification_delta = abs(reference_tps - qualification_tps) / reference_tps if reference_tps > 0 else 0.0
	matched_delta = abs(matched_tps - qualification_tps) / qualification_tps if qualification_tps > 0 else 0.0
	output_tokens_match = (
		as_int(reference.get("request_max_tokens")) == as_int(qualification.get("max_tokens"))
		and as_int(qualification.get("max_tokens")) == as_int(matched.get("max_tokens"))
	)
	shape_explains_delta = (
		output_tokens_match
		and matched_delta <= args.matched_tolerance
		and qualification_delta >= args.regression_threshold
	)
	verdict_kind = "methodology_artifact" if shape_explains_delta else "unresolved"
	verdict = (
		f"the {reference_tps:.3f} tok/s c{concurrency} number was a methodology artifact for the "
		f"Centaur mixed/no-prefix provider lane; the production-relevant c{concurrency} number is "
		f"{qualification_tps:.3f} tok/s"
		if shape_explains_delta else
		f"the {reference_tps:.3f} -> {qualification_tps:.3f} tok/s delta is not fully explained by the matched workload evidence"
	)
	obj = {
		"format": FORMAT,
		"artifact_sha256": "",
		"benchmark_id": "ds4-vllm-throughput-regression-c64-mixed-no-prefix-20260521",
		"provider_id": str(qualification.get("provider_id") or reference.get("provider_id") or "local_vllm_pp2_tp2_c64"),
		"model_id": str(reference.get("model_id") or qualification.get("model_id") or "deepseek-ai/DeepSeek-V4-Flash"),
		"model_family": str(reference.get("model_family") or "deepseek_v4_flash"),
		"runtime": "vllm",
		"runtime_version": str(reference.get("runtime_version") or ""),
		"model_format": str(reference.get("model_format") or "safetensors"),
		"quantization": str(reference.get("quantization") or "official FP8 checkpoint with fp8 KV cache and fp4 expert path"),
		"hardware": reference.get("hardware") if isinstance(reference.get("hardware"), dict) else {},
		"launch_command": str(reference.get("launch_command") or ""),
		"api_endpoint": str(qualification.get("endpoint") or reference.get("api_endpoint") or ""),
		"context_length": as_int(reference.get("context_length")),
		"mtp_supported": bool(reference.get("mtp_supported")),
		"mtp_enabled": bool(reference.get("mtp_enabled")),
		"speculative_config": reference.get("speculative_config") if isinstance(reference.get("speculative_config"), dict) else {},
		"ngram_spec_enabled": bool(reference.get("ngram_spec_enabled")),
		"batch_size": concurrency,
		"prompt_shape": "distinct_mixed_length_no_prefix_cache_hit_64_streams_32_output_tokens",
		"output_mode": "full_vocab",
		"tokens_per_second": qualification_tps if shape_explains_delta else 0.0,
		"time_to_first_token_ms": as_float(reference.get("time_to_first_token_ms")),
		"time_to_first_token_source": str(reference.get("time_to_first_token_source") or "not separately measured by qualification"),
		"prompt_processing_tokens_per_second": as_float(reference.get("prompt_processing_tokens_per_second")),
		"prompt_processing_tokens_per_second_source": str(reference.get("prompt_processing_tokens_per_second_source") or "not separately measured by qualification"),
		"memory_used_gib": as_float(reference.get("memory_used_gib")),
		"parse_valid": bool(shape_explains_delta),
		"task_quality_score": None,
		"blocker_kind": "none" if shape_explains_delta else "unknown",
		"blocker_detail": "" if shape_explains_delta else "matched workload evidence did not reproduce the live qualification within tolerance",
		"created_utc": utc_now(),
		"issue": "experiencenow-ai/ds4_on_spark#1208",
		"concurrency": concurrency,
		"reference_sweep": {
			**source_ref(reference_path),
			"benchmark_id": reference.get("benchmark_id"),
			"prompt_shape": reference_prompt_shape,
			"request_max_tokens": reference.get("request_max_tokens"),
			"aggregate_tok_s": reference_tps,
			"per_stream_tok_s": reference_tps / float(concurrency),
			"rounds": reference_summary.get("rounds"),
			"successful_rounds": reference_summary.get("successful_rounds"),
			"total_errors": reference_summary.get("total_errors"),
			"estimated_total_prompt_tokens": reference_prompt_tokens,
			"notes": reference.get("notes", []),
		},
		"live_qualification": {
			**source_ref(qualification_path, getattr(args, "qualification_ref", "")),
			"format": qualification.get("format"),
			"provider_id": qualification.get("provider_id"),
			"api_mode": qualification.get("api_mode"),
			"endpoint": qualification.get("endpoint"),
			"stream_count": qualification.get("stream_count"),
			"max_tokens": qualification.get("max_tokens"),
			"completion_tokens": qualification.get("completion_tokens"),
			"wall_seconds": qualification.get("wall_seconds"),
			"aggregate_tok_s": qualification_tps,
			"per_stream_tok_s": as_float(qualification.get("measured_per_stream_tok_s")),
			"status": qualification.get("status"),
			"error_count": qualification.get("error_count"),
			"relative_delta_vs_reference": qualification.get("relative_delta_vs_reference"),
		},
		"matched_workload_evidence": {
			**source_ref(matched_path),
			"format": matched.get("format"),
			"prompt_mode": matched.get("prompt_mode"),
			"max_tokens": matched.get("max_tokens"),
			"aggregate_tok_s": matched_tps,
			"per_stream_tok_s": matched_tps / float(concurrency),
			"total_prompt_tokens": matched_prompt_tokens,
			"total_completion_tokens": matched_summary.get("total_completion_tokens"),
			"total_errors": matched_summary.get("total_errors"),
			"successful_rounds": matched_summary.get("successful_rounds"),
			"notes": matched.get("notes", []),
		},
		"methodology_delta": {
			"output_tokens_match": output_tokens_match,
			"reference_prompt_shape_matches_qualification": False,
			"reference_to_qualification_relative_delta": qualification_delta,
			"matched_workload_to_qualification_relative_delta": matched_delta,
			"reference_estimated_prompt_tokens": reference_prompt_tokens,
			"matched_workload_prompt_tokens": matched_prompt_tokens,
			"matched_vs_reference_prompt_token_ratio": (
				matched_prompt_tokens / float(reference_prompt_tokens)
				if reference_prompt_tokens not in (None, 0) else None
			),
		},
		"verdict_kind": verdict_kind,
		"verdict": verdict,
		"production_relevant_tok_s": qualification_tps if shape_explains_delta else 0.0,
		"should_replace_310_reference_fixture": False,
		"should_route_centaur_with_live_qualification": shape_explains_delta,
		"throughput_regression_format": "ds4-vllm-throughput-regression-diff-v1",
	}
	obj["artifact_sha256"] = canonical_hash(obj)
	return(obj)


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--reference-sweep", required=True)
	p.add_argument("--qualification", required=True)
	p.add_argument("--qualification-ref", default="")
	p.add_argument("--matched-workload", required=True)
	p.add_argument("--concurrency", type=int, default=64)
	p.add_argument("--matched-tolerance", type=float, default=0.05)
	p.add_argument("--regression-threshold", type=float, default=0.25)
	p.add_argument("--output", required=True)
	return(p.parse_args())


def main() -> int:
	args = parse_args()
	obj = build_diff(args)
	output_path = Path(args.output)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with output_path.open("w", encoding="utf-8") as f:
		json.dump(obj, f, indent=2, sort_keys=True)
		f.write("\n")
	print(json.dumps({
		"output": output_path.as_posix(),
		"verdict_kind": obj["verdict_kind"],
		"verdict": obj["verdict"],
		"production_relevant_tok_s": obj["production_relevant_tok_s"],
	}, indent=2, sort_keys=True))
	return(0)


if __name__ == "__main__":
	raise SystemExit(main())
