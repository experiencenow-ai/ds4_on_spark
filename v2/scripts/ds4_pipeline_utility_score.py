#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return(default)
    return(float(value))


def _clamp01(value: float) -> float:
    if value < 0.0:
        return(0.0)
    if value > 1.0:
        return(1.0)
    return(value)


def _factor(actual: float, target: float) -> float:
    if target <= 0.0:
        return(1.0)
    return(_clamp01(actual / target))


def _kv_multiple(service: dict[str, Any]) -> float:
    explicit = service.get("kv_resident_input_batches")
    if explicit is not None:
        return(_float(explicit))
    capacity_tokens = _float(service.get("kv_capacity_tokens"))
    batch_size = max(1.0,_float(service.get("batch_size"),1.0))
    input_tokens = max(1.0,_float(service.get("input_budget_tokens"),1.0))
    if capacity_tokens <= 0.0:
        return(0.0)
    return(capacity_tokens / (batch_size * input_tokens))


def score_service(service: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    pp_size = max(1.0,_float(service.get("pipeline_parallel_size"),1.0))
    batch_size = _float(service.get("batch_size"))
    input_tokens = _float(service.get("input_budget_tokens"))
    output_tokens = _float(service.get("output_budget_tokens"))
    tok_s = _float(service.get("assumed_decode_tok_s"))
    lane_weight = _float(service.get("lane_weight"),1.0)
    accuracy_weight = _float(service.get("accuracy_weight"),1.0)
    target_batch_per_pp = _float(service.get("target_batch_per_pipeline_stage"),_float(defaults.get("target_batch_per_pipeline_stage"),2.0))
    min_input = _float(service.get("min_input_budget_tokens"),_float(defaults.get("min_input_budget_tokens"),8192.0))
    min_output = _float(service.get("min_output_budget_tokens"),_float(defaults.get("min_output_budget_tokens"),4096.0))
    min_kv = _float(service.get("min_kv_resident_input_batches"),_float(defaults.get("min_kv_resident_input_batches"),2.0))
    preferred_kv = _float(service.get("preferred_kv_resident_input_batches"),_float(defaults.get("preferred_kv_resident_input_batches"),3.0))
    kv_multiple = _kv_multiple(service)
    batch_factor = _factor(batch_size,target_batch_per_pp * pp_size)
    input_factor = _factor(input_tokens,min_input)
    output_factor = _factor(output_tokens,min_output)
    if kv_multiple <= 0.0:
        kv_efficiency = 0.0
        kv_status = "unknown"
    elif kv_multiple < min_kv:
        kv_efficiency = 0.0
        kv_status = "under_resident"
    elif kv_multiple <= preferred_kv:
        kv_efficiency = 1.0
        kv_status = "target"
    else:
        kv_efficiency = preferred_kv / kv_multiple
        kv_status = "over_resident"
    useful_tok_s = tok_s * lane_weight * accuracy_weight
    score = useful_tok_s * batch_factor * input_factor * output_factor * kv_efficiency
    return(
        {
            "service_id": str(service.get("service_id","")),
            "lane": str(service.get("lane","")),
            "score": round(score,6),
            "useful_tok_s": round(useful_tok_s,6),
            "batch_factor": round(batch_factor,6),
            "input_budget_factor": round(input_factor,6),
            "output_budget_factor": round(output_factor,6),
            "kv_efficiency": round(kv_efficiency,6),
            "kv_resident_input_batches": round(kv_multiple,6),
            "kv_status": kv_status,
        }
    )


def score_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metric = payload.get("throughput_utility_metric") or payload
    defaults = dict(metric.get("defaults") or {})
    services = [score_service(dict(item),defaults) for item in metric.get("service_candidates",[])]
    total = sum(_float(item.get("score")) for item in services)
    return(
        {
            "format": "ds4-pipeline-utility-score-v1",
            "score": round(total,6),
            "services": services,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Score DSAPI resident pipeline candidates using throughput, batch, token-budget, and KV-residency factors.")
    parser.add_argument("path", type=Path, help="JSON file containing throughput_utility_metric or a direct metric payload")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    scored = score_payload(payload)
    if args.json:
        print(json.dumps(scored, indent=2, sort_keys=True))
    else:
        print(f"score={scored['score']:.6f}")
        for item in scored["services"]:
            print(
                "{service_id:28s} score={score:10.6f} useful_tok_s={useful_tok_s:8.3f} batch={batch_factor:.3f} input={input_budget_factor:.3f} output={output_budget_factor:.3f} kv={kv_efficiency:.3f} kv_batches={kv_resident_input_batches:.3f} {kv_status}".format(
                    **item
                )
            )
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
