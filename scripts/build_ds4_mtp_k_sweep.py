#!/usr/bin/env python3
"""Build ds4-mtp-k-sweep-v1 artifacts for choosing MTP draft length K."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Optional


FORMAT = "ds4-mtp-k-sweep-v1"
DEFAULT_K_VALUES = "3,4,5"
DEFAULT_IDLE_SLOTS = "0,1,2,3,4,6,8,16,64,128,256,511"


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	tmp.pop("artifact_hash", None)
	return sha256_obj(tmp)


def parse_int_csv(text: str) -> list[int]:
	out: list[int] = []
	for raw in text.split(","):
		item = raw.strip()
		if item == "":
			continue
		value = int(item)
		if value < 0:
			raise ValueError("values must be non-negative")
		out.append(value)
	return sorted(dict.fromkeys(out))


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def is_power_of_two(value: int) -> bool:
	return value > 0 and (value & (value - 1)) == 0


def infer_k_from_economics(obj: dict[str, Any]) -> Optional[int]:
	per = obj.get("target_positions_per_invocation")
	try:
		value = int(round(float(per))) - 1
	except (TypeError, ValueError):
		return None
	return value if value > 0 else None


def expected_emitted_tokens(k: int, accept_prob: float) -> float:
	if k <= 0:
		return 1.0
	total = 0.0
	for i in range(k + 1):
		total += accept_prob ** i
	return total


def fit_map(k: int, idle_slots: list[int]) -> dict[str, bool]:
	return {str(slots): slots >= k for slots in idle_slots}


def row_for_k(
	k: int,
	*,
	accept_prob: float,
	idle_slots: list[int],
	supported_k: set[int],
	measured: dict[int, dict[str, Any]],
) -> dict[str, Any]:
	obj = measured.get(k)
	expected = expected_emitted_tokens(k, accept_prob)
	total_rows = k + 1
	extra_rows = k
	row: dict[str, Any] = {
		"k": k,
		"k_power_of_two": is_power_of_two(k),
		"runtime_supported": k in supported_k,
		"measurement_status": "projected_unsupported_runtime",
		"expected_accept_prob_per_draft_token": accept_prob,
		"expected_emitted_tokens_per_group": expected,
		"total_target_verifier_rows_per_group": total_rows,
		"extra_idle_rows_required_per_promoted_sequence": extra_rows,
		"expected_target_rows_per_output_token": total_rows / expected,
		"expected_draft_calls_per_output_token": k / expected if expected > 0.0 else 0.0,
		"expected_bonus_tokens_per_extra_idle_row": (expected - 1.0) / extra_rows if extra_rows > 0 else 0.0,
		"fits_idle_extra_rows": fit_map(k, idle_slots),
		"blocker_kind": "runtime_suffix_k_not_implemented",
		"blocker_detail": f"K={k} needs target_suffix_verify over {k + 1} positions plus staged KV prefix commit; current runtime support set is {sorted(supported_k)}",
	}
	if k in supported_k:
		row["measurement_status"] = "supported_unmeasured"
		row["blocker_kind"] = "needs_spark_measurement"
		row["blocker_detail"] = f"K={k} is supported by the runtime contract but has no measured economics artifact in this sweep"
	if obj is not None:
		row.update(
			{
				"measurement_status": "measured",
				"source_artifact": str(obj.get("_source_path", "")),
				"baseline_tps": float(obj["baseline_tps"]),
				"mtp_tps": float(obj["mtp_tps"]),
				"speedup_vs_baseline": float(obj["speedup_vs_baseline"]),
				"accept_rate": float(obj["accept_rate"]),
				"accepted_draft_tokens": int(obj["accepted_draft_tokens"]),
				"attempted_draft_tokens": int(obj["attempted_draft_tokens"]),
				"emitted_tokens": int(obj["emitted_tokens"]),
				"target_verifier_invocation_count": int(obj["target_verifier_invocation_count"]),
				"target_positions_verified": int(obj["target_positions_verified"]),
				"target_positions_per_invocation": float(obj["target_positions_per_invocation"]),
				"output_head_invocation_count": int(obj["output_head_invocation_count"]),
				"full_vocab_logits_rows": int(obj["full_vocab_logits_rows"]),
				"top1_only_rows": int(obj["top1_only_rows"]),
				"timing_coverage_rate": float(obj.get("timing_coverage_rate", 0.0)),
				"slowest_component": str(obj.get("slowest_component", "")),
				"blocker_kind": str(obj.get("blocker_kind", "none")),
				"blocker_detail": str(obj.get("blocker_detail", "")),
			}
		)
	return row


def reference_row(k: int, obj: dict[str, Any]) -> dict[str, Any]:
	return {
		"k": k,
		"source_artifact": str(obj.get("_source_path", "")),
		"baseline_tps": float(obj["baseline_tps"]),
		"mtp_tps": float(obj["mtp_tps"]),
		"speedup_vs_baseline": float(obj["speedup_vs_baseline"]),
		"accept_rate": float(obj["accept_rate"]),
		"accepted_draft_tokens": int(obj["accepted_draft_tokens"]),
		"attempted_draft_tokens": int(obj["attempted_draft_tokens"]),
		"emitted_tokens": int(obj["emitted_tokens"]),
		"target_verifier_invocation_count": int(obj["target_verifier_invocation_count"]),
		"target_positions_verified": int(obj["target_positions_verified"]),
		"target_positions_per_invocation": float(obj["target_positions_per_invocation"]),
		"output_head_invocation_count": int(obj["output_head_invocation_count"]),
		"full_vocab_logits_rows": int(obj["full_vocab_logits_rows"]),
		"top1_only_rows": int(obj["top1_only_rows"]),
		"slowest_component": str(obj.get("slowest_component", "")),
	}


def best_by_idle(rows: list[dict[str, Any]], idle_slots: list[int], *, runtime_only: bool) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for slots in idle_slots:
		candidates = [r for r in rows if bool(r["fits_idle_extra_rows"][str(slots)])]
		if runtime_only:
			candidates = [r for r in candidates if bool(r["runtime_supported"])]
		if not candidates:
			out.append({"idle_extra_rows": slots, "best_k": None, "reason": "no K fits"})
			continue
		latency_best = max(candidates, key=lambda r: (float(r["expected_emitted_tokens_per_group"]), int(r["k"])))
		row_best = max(candidates, key=lambda r: (float(r["expected_bonus_tokens_per_extra_idle_row"]), -int(r["k"])))
		out.append(
			{
				"idle_extra_rows": slots,
				"best_k_for_sequence_latency": int(latency_best["k"]),
				"best_k_for_idle_row_efficiency": int(row_best["k"]),
			}
		)
	return out


def build_sweep(
	*,
	run_id: str,
	model_id: str,
	runtime_id: str,
	prompt_hash: str,
	k_values: list[int],
	supported_k: set[int],
	idle_slots: list[int],
	accept_prob: Optional[float],
	measured_paths: list[Path],
) -> dict[str, Any]:
	measured: dict[int, dict[str, Any]] = {}
	for path in measured_paths:
		obj = load_json(path)
		k = infer_k_from_economics(obj)
		if k is None:
			raise ValueError(f"{path}: cannot infer K from target_positions_per_invocation")
		obj["_source_path"] = str(path)
		measured[k] = obj
	if accept_prob is None:
		measured_rates = [float(obj["accept_rate"]) for obj in measured.values() if obj.get("accept_rate") is not None]
		accept_prob = measured_rates[0] if measured_rates else 0.9
	if accept_prob < 0.0 or accept_prob > 1.0:
		raise ValueError("accept probability must be between 0 and 1")
	rows = [
		row_for_k(
			k,
			accept_prob=accept_prob,
			idle_slots=idle_slots,
			supported_k=supported_k,
			measured=measured,
		)
		for k in k_values
	]
	references = [reference_row(k, obj) for k, obj in sorted(measured.items()) if k not in set(k_values)]
	if any(r.get("measurement_status") == "measured" for r in rows):
		blocker_kind = "none"
		blocker_detail = ""
	elif any(r.get("measurement_status") == "supported_unmeasured" for r in rows):
		blocker_kind = "candidate_k_needs_spark_measurement"
		blocker_detail = f"candidate K values {[r['k'] for r in rows if r.get('measurement_status') == 'supported_unmeasured']} are runtime-supported but not measured in this artifact"
	elif references:
		blocker_kind = "candidate_k_runtime_not_implemented"
		blocker_detail = f"candidate K values {k_values} are projected/classified only; measured reference K values are {[r['k'] for r in references]}"
	else:
		blocker_kind = "no_measured_k"
		blocker_detail = "no measured verifier economics artifact was provided"
	out: dict[str, Any] = {
		"format": FORMAT,
		"run_id": run_id,
		"model_id": model_id,
		"runtime_id": runtime_id,
		"prompt_hash": prompt_hash,
		"k_power_of_two_required": False,
		"k_values_tested_or_classified": k_values,
		"runtime_supported_k": sorted(supported_k),
		"idle_extra_rows_swept": idle_slots,
		"accept_prob_used_for_projection": accept_prob,
		"reference_measurements": references,
		"k_results": rows,
		"best_supported_k_by_idle_rows": best_by_idle(rows, idle_slots, runtime_only=True),
		"best_projected_k_by_idle_rows": best_by_idle(rows, idle_slots, runtime_only=False),
		"integration_rule": "K consumes K extra verifier rows beyond the normal target row; use MTP only when those rows are idle or when measured scheduler-level output tokens/s improves.",
		"blocker_kind": blocker_kind,
		"blocker_detail": blocker_detail,
	}
	out["artifact_sha256"] = artifact_sha256(out)
	return out


def main(argv: Optional[list[str]] = None) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--run-id", required=True)
	ap.add_argument("--model-id", default="DeepSeek-V4-Flash-IQ2XXS-chat-v2")
	ap.add_argument("--runtime-id", default="antirez/ds4@3630e64+cuda-mtp")
	ap.add_argument("--prompt-hash", default="")
	ap.add_argument("--k-values", default=DEFAULT_K_VALUES)
	ap.add_argument("--supported-k", default="2")
	ap.add_argument("--idle-extra-rows", default=DEFAULT_IDLE_SLOTS)
	ap.add_argument("--accept-prob", type=float, default=None)
	ap.add_argument("--measured-economics", action="append", default=[])
	ap.add_argument("--out-json", default="")
	args = ap.parse_args(argv)
	obj = build_sweep(
		run_id=args.run_id,
		model_id=args.model_id,
		runtime_id=args.runtime_id,
		prompt_hash=args.prompt_hash,
		k_values=parse_int_csv(args.k_values),
		supported_k=set(parse_int_csv(args.supported_k)),
		idle_slots=parse_int_csv(args.idle_extra_rows),
		accept_prob=args.accept_prob,
		measured_paths=[Path(p) for p in args.measured_economics],
	)
	text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
	if args.out_json:
		Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
		Path(args.out_json).write_text(text, encoding="utf-8")
	print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
