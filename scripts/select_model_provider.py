#!/usr/bin/env python3
"""Select a Centaur model provider from validated DS4 provider profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import validate_model_provider_profiles as profile_validator


TIER_RANK = {
    "deterministic": 0,
    "local_small": 1,
    "local_coder": 2,
    "near_frontier_local": 3,
    "frontier_api": 4,
}


def load_profile_records(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    selected_paths = paths if paths else profile_validator.default_profile_paths()
    validation = profile_validator.validate_paths(selected_paths)
    if not validation["ok"]:
        return [], list(validation["errors"])
    records: list[dict[str, Any]] = []
    root = profile_validator.repo_root()
    for path in selected_paths:
        profile = profile_validator.load_profile(path)
        try:
            profile["_profile_path"] = str(path.resolve().relative_to(root))
        except ValueError:
            profile["_profile_path"] = str(path)
        records.append(profile)
    return records, []


def profile_rejections(profile: dict[str, Any], required_tier: str, lane: str, batch_tokens: int, max_wait_ms: int | None, require_production_eligible: bool) -> list[str]:
    reasons: list[str] = []
    tier = str(profile.get("tier", ""))
    if TIER_RANK.get(tier, -1) < TIER_RANK[required_tier]:
        reasons.append("tier_below_required")
    if lane not in profile.get("supported_lanes", []):
        reasons.append("lane_not_supported")
    minimum_batch = profile.get("minimum_batch_tokens")
    if isinstance(minimum_batch, int) and batch_tokens < minimum_batch:
        reasons.append("batch_tokens_below_minimum")
    if max_wait_ms is not None:
        provider_wait = profile.get("maximum_wait_ms")
        if isinstance(provider_wait, int) and provider_wait > max_wait_ms:
            reasons.append("maximum_wait_ms_exceeds_budget")
    if require_production_eligible is True and profile.get("production_eligible") is not True:
        reasons.append("not_production_eligible")
    if require_production_eligible is True:
        output_tps = profile.get("measured_output_tps")
        if not isinstance(output_tps, (int, float)) or isinstance(output_tps, bool) or float(output_tps) <= 0.0:
            reasons.append("missing_measured_output_tps")
    return reasons


def rejection_summary(rejections: dict[str, list[str]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for reasons in rejections.values():
        for reason in reasons:
            summary[reason] = summary.get(reason, 0) + 1
    return dict(sorted(summary.items()))


def provider_sort_key(profile: dict[str, Any], batch_tokens: int) -> tuple[int, float, int, int, str]:
    tier = str(profile.get("tier", ""))
    output_tps = profile.get("measured_output_tps")
    preferred_batch = profile.get("preferred_batch_tokens")
    maximum_wait = profile.get("maximum_wait_ms")
    tps = float(output_tps) if isinstance(output_tps, (int, float)) and not isinstance(output_tps, bool) else 0.0
    preferred = int(preferred_batch) if isinstance(preferred_batch, int) else 0
    wait = int(maximum_wait) if isinstance(maximum_wait, int) else 0
    batch_distance = abs(preferred - batch_tokens)
    return (TIER_RANK[tier], -tps, wait, batch_distance, str(profile.get("provider_id", "")))


def summarize_provider(profile: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "provider_id",
        "tier",
        "model_id",
        "runtime",
        "provider_kind",
        "node_ids",
        "supported_lanes",
        "preferred_batch_tokens",
        "minimum_batch_tokens",
        "maximum_wait_ms",
        "measured_output_tps",
        "last_probe_artifact",
        "production_eligible",
        "_profile_path",
    )
    return {field.removeprefix("_"): profile.get(field) for field in fields}


def select_provider(profiles: list[dict[str, Any]], required_tier: str, lane: str, batch_tokens: int, max_wait_ms: int | None = None, require_production_eligible: bool = True) -> dict[str, Any]:
    if required_tier not in TIER_RANK:
        return {
            "format": "centaur-provider-selection-v1",
            "selected": False,
            "blocker_kind": "invalid_required_tier",
            "blocker_detail": f"unknown required tier: {required_tier}",
            "required_tier": required_tier,
            "lane": lane,
            "batch_tokens": batch_tokens,
        }
    rejections: dict[str, list[str]] = {}
    eligible: list[dict[str, Any]] = []
    for profile in profiles:
        reasons = profile_rejections(profile, required_tier, lane, batch_tokens, max_wait_ms, require_production_eligible)
        provider_id = str(profile.get("provider_id", "unknown"))
        if reasons:
            rejections[provider_id] = reasons
        else:
            eligible.append(profile)
    eligible.sort(key=lambda profile: provider_sort_key(profile, batch_tokens))
    selected = eligible[0] if eligible else None
    result: dict[str, Any] = {
        "format": "centaur-provider-selection-v1",
        "selected": selected is not None,
        "required_tier": required_tier,
        "lane": lane,
        "batch_tokens": batch_tokens,
        "max_wait_ms": max_wait_ms,
        "require_production_eligible": require_production_eligible,
        "candidate_count": len(profiles),
        "eligible_provider_count": len(eligible),
        "rejection_summary": rejection_summary(rejections),
        "rejections_by_provider": rejections,
    }
    if selected is None:
        result["blocker_kind"] = "no_eligible_provider"
        result["blocker_detail"] = "no provider satisfied tier, lane, batch, wait, and eligibility requirements"
        result["selected_provider"] = None
    else:
        result["blocker_kind"] = None
        result["blocker_detail"] = ""
        result["selected_provider"] = summarize_provider(selected)
        result["selection_reason"] = "lowest sufficient tier, then highest measured output tps, then wait/batch fit"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Select a Centaur model provider from DS4 provider profiles.")
    parser.add_argument("--tier", required=True, choices=sorted(TIER_RANK), help="Minimum required capability tier.")
    parser.add_argument("--lane", required=True, help="Required supported lane, e.g. hard_reasoning or batch_judge.")
    parser.add_argument("--batch-tokens", required=True, type=int, help="Admission batch token budget for this request.")
    parser.add_argument("--max-wait-ms", type=int, default=None, help="Optional maximum queue wait budget.")
    parser.add_argument("--allow-non-production", action="store_true", help="Allow profiles without production_eligible=true for dry-run planning.")
    parser.add_argument("profiles", nargs="*", help="Provider profile JSON paths. Defaults to fixtures/model_providers/*.json.")
    args = parser.parse_args()
    profile_paths = [Path(item) for item in args.profiles]
    profiles, errors = load_profile_records(profile_paths)
    if errors:
        result = {
            "format": "centaur-provider-selection-v1",
            "selected": False,
            "blocker_kind": "invalid_provider_inventory",
            "blocker_detail": "provider profile validation failed",
            "errors": errors,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    result = select_provider(
        profiles,
        required_tier=args.tier,
        lane=args.lane,
        batch_tokens=args.batch_tokens,
        max_wait_ms=args.max_wait_ms,
        require_production_eligible=not args.allow_non_production,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["selected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
