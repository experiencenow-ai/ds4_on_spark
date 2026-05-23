#!/usr/bin/env python3
"""Build provider profiles from executed Spark2 small-model qualifications."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ADDENDUM = Path("fixtures/small_model_qualification/throughput_addendum_20260523.json")
OUTPUT_DIR = Path("fixtures/model_providers")
MIN_PASS_RATE = 1.0
RUNTIME_BY_BACKEND = {
    "llama.cpp": "llama_cpp",
    "transformers": "transformers_cli",
}
LANES_BY_TIER = {
    "local_small": [
        "classification",
        "schema_cleanup",
        "candidate_prefilter",
        "structured_classification",
        "dry_route_id",
    ],
    "local_coder": [
        "routine_code_patch",
        "test_interpretation",
        "schema_repair",
        "routine_code_explanation",
        "small_code_patch_plan",
    ],
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: root JSON must be an object")
    return obj


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-+", "-", text)


def eligible_records(addendum: dict[str, Any], min_pass_rate: float = MIN_PASS_RATE) -> list[dict[str, Any]]:
    records = addendum.get("records")
    if not isinstance(records, list):
        raise ValueError("addendum.records must be a list")
    eligible: list[dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "passed" or row.get("derivation_status") != "derived":
            continue
        if not isinstance(row.get("mean_tok_s"), (int, float)) or float(row["mean_tok_s"]) <= 0.0:
            continue
        if not isinstance(row.get("pass_rate"), (int, float)) or float(row["pass_rate"]) < min_pass_rate:
            continue
        if str(row.get("serve_backend", "")) not in RUNTIME_BY_BACKEND:
            continue
        source = Path(str(row.get("source_record", "")))
        if not source.is_file():
            continue
        eligible.append(row)
    return eligible


def is_coder_candidate(row: dict[str, Any]) -> bool:
    model_id = str(row.get("model_id", "")).lower()
    source = load_json(Path(str(row["source_record"])))
    task_kinds = {
        str(item.get("task_kind", ""))
        for item in source.get("per_prompt_results", [])
        if isinstance(item, dict) and item.get("passed") is True
    }
    return "simple_code" in task_kinds and any(token in model_id for token in ("qwen", "coder", "swe", "devstral", "code"))


def sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda row: (
            -float(row.get("pass_rate", 0.0)),
            -float(row.get("mean_tok_s", 0.0)),
            float(row.get("cost_proxy", 1e12) or 1e12),
            str(row.get("model_id", "")),
        ),
    )


def select_records(addendum: dict[str, Any]) -> dict[str, dict[str, Any]]:
    eligible = eligible_records(addendum)
    local_small = sort_records(eligible)
    local_coder = sort_records([row for row in eligible if is_coder_candidate(row)])
    if not local_small:
        raise ValueError("no local_small-eligible records found")
    if not local_coder:
        raise ValueError("no local_coder-eligible records found")
    return {
        "local_small": local_small[0],
        "local_coder": local_coder[0],
    }


def quality_scores(tier: str, pass_rate: float) -> dict[str, float | None]:
    score = pass_rate * 100.0
    if tier == "local_small":
        return {
            "classification": score,
            "schema_cleanup": score,
            "candidate_prefilter": score,
        }
    return {
        "coding": score,
        "routine_code_patch": score,
        "test_interpretation": score,
        "schema_repair": score,
    }


def profile_from_row(tier: str, row: dict[str, Any], addendum_path: Path = ADDENDUM) -> dict[str, Any]:
    source_path = Path(str(row["source_record"]))
    source = load_json(source_path)
    model_id = str(row["model_id"])
    serve_backend = str(row["serve_backend"])
    pass_rate = float(row["pass_rate"])
    p95_latency = float(row.get("p95_latency_ms", source.get("aggregate_metrics", {}).get("p95_latency_ms", 0.0)) or 0.0)
    provider_id = f"spark2-{slug(model_id)}-{tier}-measured"
    return {
        "format": "centaur-model-provider-profile-v1",
        "provider_id": provider_id,
        "tier": tier,
        "model_id": model_id,
        "runtime": RUNTIME_BY_BACKEND[serve_backend],
        "endpoint": {
            "kind": "ssh_cli",
            "status": "measured_cli_available",
            "host": source.get("hardware_node", "spark2"),
            "model_path": source.get("model_path", ""),
            "serve_backend": serve_backend,
        },
        "node_ids": [str(source.get("hardware_node", "spark2"))],
        "provider_kind": "independent_lane",
        "supported_lanes": LANES_BY_TIER[tier],
        "preferred_batch_tokens": 32,
        "minimum_batch_tokens": 1,
        "maximum_wait_ms": max(1, int(round(p95_latency))),
        "measured_input_tps": None,
        "measured_output_tps": float(row["mean_tok_s"]),
        "quality_scores": quality_scores(tier, pass_rate),
        "last_probe_artifact": str(source_path),
        "benchmark_refs": [str(addendum_path), str(source_path)],
        "source_refs": [
            "docs/model-provider-tiers.md",
            "docs/spark-ring.md",
        ],
        "production_eligible": True,
        "selection_evidence": {
            "addendum": str(addendum_path),
            "min_pass_rate": MIN_PASS_RATE,
            "pass_rate": pass_rate,
            "mean_tok_s": float(row["mean_tok_s"]),
            "median_tok_s": row.get("median_tok_s"),
            "cost_proxy": row.get("cost_proxy"),
            "cost_proxy_basis": row.get("cost_proxy_basis"),
        },
        "notes": "Generated from executed Spark2 small-model qualification evidence; no live provider call is made by this profile generator.",
    }


def write_profiles(output_dir: Path, profiles: dict[str, dict[str, Any]]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for tier, profile in profiles.items():
        path = output_dir / f"{profile['provider_id']}.example.json"
        path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DS4 provider profiles from Spark2 small-model throughput evidence.")
    parser.add_argument("--addendum", default=str(ADDENDUM), help="small-model-throughput-addendum-v1 JSON path.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Directory for generated provider profiles.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected profiles instead of writing files.")
    args = parser.parse_args()
    addendum_path = Path(args.addendum)
    selected = select_records(load_json(addendum_path))
    profiles = {tier: profile_from_row(tier, row, addendum_path) for tier, row in selected.items()}
    if args.dry_run:
        print(json.dumps(profiles, indent=2, sort_keys=True))
        return 0
    for path in write_profiles(Path(args.output_dir), profiles):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
