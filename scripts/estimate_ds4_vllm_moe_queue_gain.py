#!/usr/bin/env python3
"""Estimate the B=512 gain from a vLLM MXFP4 batched expert queue."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-moe-queue-gain-poc-v1"
HASH_FIELDS = {"artifact_sha256"}
REQUIRED_SCENARIOS = {
	"weak_1p25x_moe",
	"conservative_1p5x_moe",
	"two_x_moe",
	"three_x_moe",
	"ds4_slice_tile8_stage_implied",
	"gate_up_only_upper_bound",
}


def default_paths() -> list[Path]:
	root = Path(__file__).resolve().parents[1]
	return(sorted((root / "fixtures" / "vllm_moe_gain_poc").glob("*.example.json")))


def canonical_hash(obj: dict[str, Any]) -> str:
	payload = copy.deepcopy(obj)
	for field in HASH_FIELDS:
		payload.pop(field, None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
	return(hashlib.sha256(data).hexdigest())


def overall_speedup(moe_fraction: float, moe_speedup: float) -> float:
	return(1.0 / ((1.0 - moe_fraction) + (moe_fraction / moe_speedup)))


def implied_moe_speedup(moe_fraction: float, end_to_end_speedup: float) -> float:
	denom = ((1.0 / end_to_end_speedup) - (1.0 - moe_fraction))
	if denom <= 0.0:
		raise ValueError("end_to_end_speedup is impossible for the given MoE fraction")
	return(moe_fraction / denom)


def scenario(name: str, moe_fraction: float, baseline_tps: float, moe_speedup: float, note: str) -> dict[str, Any]:
	speedup = overall_speedup(moe_fraction, moe_speedup)
	tps = (baseline_tps * speedup)
	return({
		"id": name,
		"moe_component_speedup": moe_speedup,
		"estimated_end_to_end_speedup": speedup,
		"estimated_c512_aggregate_tps": tps,
		"delta_c512_aggregate_tps": (tps - baseline_tps),
		"note": note,
	})


def build_default_artifact() -> dict[str, Any]:
	baseline_tps = 174.19031762627782
	moe_fraction = 0.92
	before_rows_s = 209.0
	after_rows_s = 631.6720652969875
	stage_speedup = (after_rows_s / before_rows_s)
	implied = implied_moe_speedup(moe_fraction, stage_speedup)
	gate_up_speedup = (116.993 / 18.784)
	scenarios = [
		scenario("weak_1p25x_moe", moe_fraction, baseline_tps, 1.25, "Small improvement from queueing alone; useful only as a sanity threshold."),
		scenario("conservative_1p5x_moe", moe_fraction, baseline_tps, 1.5, "Conservative win if batched MXFP4 expert work reduces launch/layout overhead but not math cost."),
		scenario("two_x_moe", moe_fraction, baseline_tps, 2.0, "Moderate win if the queue materially improves expert tile occupancy."),
		scenario("three_x_moe", moe_fraction, baseline_tps, 3.0, "Strong win if MXFP4 batched expert tiles recover most of the DS4 custom utilization gap."),
		scenario("ds4_slice_tile8_stage_implied", moe_fraction, baseline_tps, implied, "MoE component speedup implied by the DS4 stage rows/s gain when MoE is 92% of time."),
		scenario("gate_up_only_upper_bound", moe_fraction, baseline_tps, gate_up_speedup, "Upper-bound style case using the measured DS4 gate/up timing cut; not an expected whole-MoE outcome."),
	]
	return({
		"format": FORMAT,
		"artifact_sha256": "",
		"poc_id": "ds4-vllm-b512-mxfp4-batched-expert-queue-gain-20260521",
		"created_utc": "2026-05-21T10:40:00Z",
		"model_id": "deepseek-ai/DeepSeek-V4-Flash",
		"runtime": "vllm",
		"runtime_version": "0.1.dev16581+gdda4668b5.d20260521",
		"runtime_commit": "dda4668b59567416f86956cfe7bbc1eab371a61e",
		"batch_size": 512,
		"baseline_c512_aggregate_tps": baseline_tps,
		"baseline_source_fixture": "fixtures/vllm_config_tuning/vllm_deepseek_v4_flash_tp2_custom_transfer_tuning_20260521.example.json",
		"moe_time_fraction": moe_fraction,
		"moe_fraction_source": "user-provided antirez profile summary: MoE was 92% of time",
		"custom_ds4_slice_tile8_reference": {
			"before_rows_per_s": before_rows_s,
			"after_rows_per_s": after_rows_s,
			"end_to_end_rows_speedup": stage_speedup,
			"implied_moe_component_speedup": implied,
			"gate_up_ms_before": 116.993,
			"gate_up_ms_after": 18.784,
			"gate_up_component_speedup": gate_up_speedup,
		},
		"current_vllm_code_audit": "fixtures/vllm_moe_code_audit/vllm_deepseek_v4_mxfp4_moe_code_audit_20260521.example.json",
		"assumption": "If vLLM B=512 spends a similar 92% of decode time in routed MoE, then adding an effective no-DP batched expert queue has large end-to-end leverage. This is an estimate, not a measured speedup claim.",
		"scenarios": scenarios,
		"likely_band": {
			"low_c512_aggregate_tps": scenarios[2]["estimated_c512_aggregate_tps"],
			"high_c512_aggregate_tps": scenarios[4]["estimated_c512_aggregate_tps"],
			"low_speedup": scenarios[2]["estimated_end_to_end_speedup"],
			"high_speedup": scenarios[4]["estimated_end_to_end_speedup"],
			"interpretation": "If the missing vLLM expert queue gives 2.0x MoE speedup, expect about 323 tok/s; matching the DS4 stage-level implied MoE gain would be about 526 tok/s."
		},
		"decision_rule": "Prototype no-DP BatchedExperts/BATCHED_MARLIN only if the implementation can preserve correctness and show MoE/backend timing evidence; a c512 result below 250 tok/s implies the queue is not addressing the dominant bottleneck.",
		"next_code_probe": "Capture explicit DeepGEMM/FlashInfer rejection reasons, then add an opt-in no-DP MXFP4 batched expert activation path and compare c512 aggregate TPS against 174.190.",
	})


def err(path: Path, msg: str) -> str:
	return(f"{path}: {msg}")


def load(path: Path) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as f:
		obj = json.load(f)
	if not isinstance(obj, dict):
		raise ValueError("root JSON must be an object")
	return(obj)


def close(a: float, b: float, tol: float = 1e-9) -> bool:
	return(abs(a - b) <= tol)


def validate(obj: dict[str, Any], path: Path) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(err(path, f"format must be {FORMAT}"))
	if obj.get("artifact_sha256") != canonical_hash(obj):
		errors.append(err(path, "artifact_sha256 does not match canonical hash"))
	baseline = obj.get("baseline_c512_aggregate_tps")
	moe_fraction = obj.get("moe_time_fraction")
	if not isinstance(baseline, (int, float)) or isinstance(baseline, bool) or baseline <= 0.0:
		errors.append(err(path, "baseline_c512_aggregate_tps must be positive"))
		baseline = 0.0
	if not isinstance(moe_fraction, (int, float)) or isinstance(moe_fraction, bool) or moe_fraction <= 0.0 or moe_fraction >= 1.0:
		errors.append(err(path, "moe_time_fraction must be between 0 and 1"))
		moe_fraction = 0.0
	scenarios = obj.get("scenarios")
	if not isinstance(scenarios, list) or len(scenarios) == 0:
		errors.append(err(path, "scenarios must be a non-empty list"))
		return(errors)
	ids = {item.get("id") for item in scenarios if isinstance(item, dict)}
	missing = sorted(REQUIRED_SCENARIOS - ids)
	if missing:
		errors.append(err(path, "missing scenario ids: " + ",".join(missing)))
	for item in scenarios:
		if not isinstance(item, dict):
			errors.append(err(path, "each scenario must be an object"))
			continue
		item_id = item.get("id")
		moe_speedup = item.get("moe_component_speedup")
		speedup = item.get("estimated_end_to_end_speedup")
		tps = item.get("estimated_c512_aggregate_tps")
		if not isinstance(item_id, str):
			errors.append(err(path, "scenario id must be a string"))
			continue
		if not isinstance(moe_speedup, (int, float)) or isinstance(moe_speedup, bool) or moe_speedup <= 1.0:
			errors.append(err(path, f"scenario {item_id} must have moe_component_speedup > 1"))
			continue
		expected_speedup = overall_speedup(float(moe_fraction), float(moe_speedup))
		expected_tps = (float(baseline) * expected_speedup)
		if not isinstance(speedup, (int, float)) or not close(float(speedup), expected_speedup, 1e-9):
			errors.append(err(path, f"scenario {item_id} estimated_end_to_end_speedup is inconsistent"))
		if not isinstance(tps, (int, float)) or not close(float(tps), expected_tps, 1e-6):
			errors.append(err(path, f"scenario {item_id} estimated_c512_aggregate_tps is inconsistent"))
	return(errors)


def validate_paths(paths: list[Path]) -> dict[str, Any]:
	all_errors: list[str] = []
	for path in paths:
		try:
			all_errors.extend(validate(load(path), path))
		except Exception as e:
			all_errors.append(err(path, str(e)))
	return({"ok": len(all_errors) == 0, "errors": all_errors})


def main() -> int:
	p = argparse.ArgumentParser(description=__doc__)
	sub = p.add_subparsers(dest="command")
	emit_p = sub.add_parser("emit", help="emit the default estimate artifact to stdout")
	emit_p.add_argument("--with-hash", action="store_true")
	validate_p = sub.add_parser("validate", help="validate estimate artifacts")
	validate_p.add_argument("paths", nargs="*", type=Path)
	args = p.parse_args()
	if args.command == "emit":
		obj = build_default_artifact()
		if args.with_hash:
			obj["artifact_sha256"] = canonical_hash(obj)
		print(json.dumps(obj, indent=2, sort_keys=False))
		return(0)
	paths = args.paths if args.command == "validate" and args.paths else default_paths()
	result = validate_paths(paths)
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0 if result["ok"] else 1)


if __name__ == "__main__":
	raise SystemExit(main())
