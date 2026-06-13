#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any


EXPANDABLE_FIELDS = (
    "batch_size",
    "input_budget_tokens",
    "output_budget_tokens",
    "kv_capacity_tokens",
    "kv_resident_input_batches",
    "gpu_memory_utilization",
    "assumed_decode_tok_s",
    "accuracy_weight",
)


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


def _candidate_values(service: dict[str, Any], field: str) -> list[Any]:
    values = service.get(f"{field}_candidates")
    if values is None:
        return([service.get(field)])
    if not isinstance(values,list) or len(values) == 0:
        raise ValueError(f"{service.get('service_id','service')} has invalid {field}_candidates")
    return(values)


def expand_service_candidates(service: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [field for field in EXPANDABLE_FIELDS if f"{field}_candidates" in service]
    if len(fields) == 0:
        return([dict(service)])
    variants: list[dict[str, Any]] = []
    for choices in itertools.product(*[_candidate_values(service,field) for field in fields]):
        variant = dict(service)
        for field in fields:
            variant.pop(f"{field}_candidates",None)
        for field,value in zip(fields,choices):
            variant[field] = value
        variants.append(variant)
    return(variants)


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
            "batch_size": round(batch_size,6),
            "input_budget_tokens": round(input_tokens,6),
            "output_budget_tokens": round(output_tokens,6),
            "gpu_memory_utilization": round(_float(service.get("gpu_memory_utilization")),6),
        }
    )


def score_pipeline_candidate(services: list[dict[str, Any]], defaults: dict[str, Any], hard_constraints: dict[str, Any]) -> dict[str, Any]:
    scored = [score_service(service,defaults) for service in services]
    service_ids = [item["service_id"] for item in scored]
    total_gpu = sum(_float(service.get("gpu_memory_utilization")) for service in services)
    max_gpu = _float(hard_constraints.get("active_gpu_memory_utilization_sum_max"),1.0)
    strict_kv = bool(hard_constraints.get("strict_kv_eviction_required",False))
    violations: list[str] = []
    if total_gpu > max_gpu:
        violations.append(f"gpu_utilization_sum {total_gpu:.3f} > {max_gpu:.3f}")
    if strict_kv:
        for item in scored:
            if item["kv_status"] != "target":
                violations.append(f"{item['service_id']} kv_status={item['kv_status']}")
    eligible = len(violations) == 0
    score = sum(_float(item.get("score")) for item in scored)
    if not eligible:
        score = 0.0
    return(
        {
            "service_ids": service_ids,
            "score": round(score,6),
            "eligible": eligible,
            "violations": violations,
            "gpu_memory_utilization_sum": round(total_gpu,6),
            "services": scored,
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


def optimize_payload(payload: dict[str, Any], top_n: int = 10) -> dict[str, Any]:
    metric = payload.get("throughput_utility_metric") or payload
    defaults = dict(metric.get("defaults") or {})
    hard_constraints = dict(metric.get("hard_constraints") or {})
    service_candidates = [dict(item) for item in metric.get("service_candidates",[])]
    variants_by_service = {
        str(service.get("service_id","")): expand_service_candidates(service)
        for service in service_candidates
    }
    service_sets = metric.get("pipeline_candidates")
    if service_sets is None:
        service_sets = [
            {
                "pipeline_id": "all_services",
                "service_ids": [str(service.get("service_id","")) for service in service_candidates],
            }
        ]
    results: list[dict[str, Any]] = []
    for service_set in service_sets:
        service_ids = [str(item) for item in service_set.get("service_ids",[])]
        if len(service_ids) == 0:
            continue
        missing = [service_id for service_id in service_ids if service_id not in variants_by_service]
        if len(missing) != 0:
            results.append(
                {
                    "pipeline_id": str(service_set.get("pipeline_id","")),
                    "service_ids": service_ids,
                    "score": 0.0,
                    "eligible": False,
                    "violations": [f"missing service candidate {service_id}" for service_id in missing],
                    "gpu_memory_utilization_sum": 0.0,
                    "services": [],
                }
            )
            continue
        for services in itertools.product(*[variants_by_service[service_id] for service_id in service_ids]):
            scored = score_pipeline_candidate([dict(service) for service in services],defaults,hard_constraints)
            scored["pipeline_id"] = str(service_set.get("pipeline_id","all_services"))
            results.append(scored)
    results.sort(key=lambda item: (bool(item.get("eligible")), _float(item.get("score"))), reverse=True)
    return(
        {
            "format": "ds4-pipeline-utility-optimizer-v1",
            "top_n": top_n,
            "candidate_count": len(results),
            "eligible_count": sum(1 for item in results if item.get("eligible")),
            "candidates": results[:top_n],
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Score DSAPI resident pipeline candidates using throughput, batch, token-budget, and KV-residency factors.")
    parser.add_argument("path", type=Path, help="JSON file containing throughput_utility_metric or a direct metric payload")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument("--optimize", action="store_true", help="Rank whole-pipeline candidate sets instead of printing per-service scores")
    parser.add_argument("--top-n", type=int, default=10, help="Maximum optimizer candidates to print")
    args = parser.parse_args()
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    if args.optimize:
        scored = optimize_payload(payload,args.top_n)
    else:
        scored = score_payload(payload)
    if args.json:
        print(json.dumps(scored, indent=2, sort_keys=True))
    elif args.optimize:
        print(f"candidates={scored['candidate_count']} eligible={scored['eligible_count']}")
        for item in scored["candidates"]:
            status = "eligible" if item["eligible"] else "blocked"
            detail = ", ".join(item["violations"])
            print(f"{item['pipeline_id']:28s} {status:8s} score={item['score']:10.6f} gpu_sum={item['gpu_memory_utilization_sum']:.3f} services={','.join(item['service_ids'])} {detail}")
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
