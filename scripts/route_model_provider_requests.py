#!/usr/bin/env python3
"""Route a Centaur-shaped batch of LLM node requests to DS4 provider profiles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import select_model_provider


REQUEST_FORMAT = "centaur-provider-route-requests-v1"
PLAN_FORMAT = "centaur-provider-routing-plan-v1"


def as_nonempty_str(obj: dict[str, Any], field: str, errors: list[str], prefix: str) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or value.strip() == "":
        errors.append(f"{prefix}.{field} must be a non-empty string")
        return ""
    return value.strip()


def as_nonnegative_int(obj: dict[str, Any], field: str, errors: list[str], prefix: str) -> int:
    value = obj.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"{prefix}.{field} must be a non-negative integer")
        return 0
    return int(value)


def validate_request_plan(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if obj.get("format") != REQUEST_FORMAT:
        errors.append(f"format must be {REQUEST_FORMAT}")
    as_nonempty_str(obj, "run_id", errors, "plan")
    requests = obj.get("requests")
    if not isinstance(requests, list) or len(requests) == 0:
        errors.append("plan.requests must be a non-empty list")
        return errors
    seen_node_ids: set[str] = set()
    for i, request in enumerate(requests):
        prefix = f"requests[{i}]"
        if not isinstance(request, dict):
            errors.append(f"{prefix} must be an object")
            continue
        node_id = as_nonempty_str(request, "node_id", errors, prefix)
        if node_id in seen_node_ids:
            errors.append(f"{prefix}.node_id must be unique")
        seen_node_ids.add(node_id)
        tier = as_nonempty_str(request, "tier", errors, prefix)
        if tier and tier not in select_model_provider.TIER_RANK:
            errors.append(f"{prefix}.tier is unknown: {tier}")
        as_nonempty_str(request, "lane", errors, prefix)
        as_nonnegative_int(request, "batch_tokens", errors, prefix)
        if "max_wait_ms" in request and request.get("max_wait_ms") is not None:
            as_nonnegative_int(request, "max_wait_ms", errors, prefix)
        if "require_production_eligible" in request and not isinstance(request.get("require_production_eligible"), bool):
            errors.append(f"{prefix}.require_production_eligible must be boolean when present")
    return errors


def load_request_plan(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception as e:
        return None, [f"{path}: {e}"]
    if not isinstance(obj, dict):
        return None, [f"{path}: root JSON must be an object"]
    errors = validate_request_plan(obj)
    return obj, [f"{path}: {item}" for item in errors]


def compact_route(selection: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    provider = selection.get("selected_provider")
    route: dict[str, Any] = {
        "node_id": request["node_id"],
        "required_tier": request["tier"],
        "lane": request["lane"],
        "batch_tokens": request["batch_tokens"],
        "max_wait_ms": request.get("max_wait_ms"),
        "require_production_eligible": selection.get("require_production_eligible"),
        "selected": bool(selection.get("selected")),
        "blocker_kind": selection.get("blocker_kind"),
        "blocker_detail": selection.get("blocker_detail"),
    }
    if isinstance(provider, dict):
        measured_output_tps = provider.get("measured_output_tps")
        route["provider_id"] = provider.get("provider_id")
        route["provider_tier"] = provider.get("tier")
        route["runtime"] = provider.get("runtime")
        route["model_id"] = provider.get("model_id")
        route["measured_output_tps"] = measured_output_tps
        route["profile_path"] = provider.get("profile_path")
        if isinstance(measured_output_tps, (int, float)) and not isinstance(measured_output_tps, bool) and float(measured_output_tps) > 0.0:
            route["estimated_service_ms_at_measured_output_tps"] = (float(route["batch_tokens"]) / float(measured_output_tps)) * 1000.0
        else:
            route["estimated_service_ms_at_measured_output_tps"] = None
    else:
        route["provider_id"] = None
        route["rejection_summary"] = selection.get("rejection_summary", {})
    return route


def provider_load(routes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    load: dict[str, dict[str, Any]] = {}
    for route in routes:
        provider_id = route.get("provider_id")
        if not isinstance(provider_id, str) or provider_id == "":
            continue
        entry = load.setdefault(provider_id, {"request_count": 0, "batch_tokens": 0, "nodes": [], "measured_output_tps": route.get("measured_output_tps")})
        entry["request_count"] += 1
        entry["batch_tokens"] += int(route.get("batch_tokens", 0))
        entry["nodes"].append(route.get("node_id"))
        if entry.get("measured_output_tps") != route.get("measured_output_tps"):
            entry["measured_output_tps"] = None
    for entry in load.values():
        measured_output_tps = entry.get("measured_output_tps")
        if isinstance(measured_output_tps, (int, float)) and not isinstance(measured_output_tps, bool) and float(measured_output_tps) > 0.0:
            entry["estimated_service_ms_at_measured_output_tps"] = (float(entry["batch_tokens"]) / float(measured_output_tps)) * 1000.0
        else:
            entry["estimated_service_ms_at_measured_output_tps"] = None
    return dict(sorted(load.items()))


def blocker_summary(routes: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for route in routes:
        if route.get("selected") is True:
            continue
        blocker = str(route.get("blocker_kind") or "unknown")
        summary[blocker] = summary.get(blocker, 0) + 1
    return dict(sorted(summary.items()))


def capacity_summary(load: dict[str, dict[str, Any]], blocked_count: int) -> dict[str, Any]:
    selected_provider_count = len(load)
    unknown = [provider_id for provider_id, entry in load.items() if entry.get("estimated_service_ms_at_measured_output_tps") is None]
    known_ms = [
        float(entry["estimated_service_ms_at_measured_output_tps"])
        for entry in load.values()
        if entry.get("estimated_service_ms_at_measured_output_tps") is not None
    ]
    return {
        "selected_provider_count": selected_provider_count,
        "estimated_provider_count": len(known_ms),
        "unknown_capacity_provider_ids": unknown,
        "blocked_request_count": blocked_count,
        "all_selected_capacity_estimated": len(unknown) == 0,
        "all_requests_capacity_estimated": len(unknown) == 0 and blocked_count == 0,
        "estimated_parallel_service_ms_at_measured_output_tps": max(known_ms) if known_ms else None,
    }


def route_request_plan(plan: dict[str, Any], profiles: list[dict[str, Any]], default_require_production_eligible: bool = True) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for request in plan["requests"]:
        require_production = request.get("require_production_eligible", default_require_production_eligible)
        selection = select_model_provider.select_provider(
            profiles,
            required_tier=request["tier"],
            lane=request["lane"],
            batch_tokens=request["batch_tokens"],
            max_wait_ms=request.get("max_wait_ms"),
            require_production_eligible=require_production,
        )
        routes.append(compact_route(selection, request))
    selected_count = sum(1 for route in routes if route["selected"] is True)
    blocked_count = len(routes) - selected_count
    load = provider_load(routes)
    return {
        "format": PLAN_FORMAT,
        "run_id": plan["run_id"],
        "request_count": len(routes),
        "selected_count": selected_count,
        "blocked_count": blocked_count,
        "all_requests_routed": blocked_count == 0,
        "provider_load": load,
        "capacity_summary": capacity_summary(load, blocked_count),
        "blocker_summary": blocker_summary(routes),
        "routes": routes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Route a Centaur provider request plan through DS4 provider profiles.")
    parser.add_argument("request_plan", help="Request-plan JSON using centaur-provider-route-requests-v1.")
    parser.add_argument("--allow-blocked", action="store_true", help="Return exit 0 even when some requests cannot be routed.")
    parser.add_argument("--allow-non-production", action="store_true", help="Default requests to allow non-production providers unless the request overrides it.")
    parser.add_argument("--profiles", nargs="*", default=[], help="Provider profile JSON paths. Defaults to fixtures/model_providers/*.json.")
    args = parser.parse_args()
    plan, plan_errors = load_request_plan(Path(args.request_plan))
    if plan_errors or plan is None:
        print(json.dumps({"format": PLAN_FORMAT, "all_requests_routed": False, "blocker_kind": "invalid_request_plan", "errors": plan_errors}, indent=2, sort_keys=True))
        return 2
    profiles, profile_errors = select_model_provider.load_profile_records([Path(item) for item in args.profiles])
    if profile_errors:
        print(json.dumps({"format": PLAN_FORMAT, "all_requests_routed": False, "blocker_kind": "invalid_provider_inventory", "errors": profile_errors}, indent=2, sort_keys=True))
        return 2
    result = route_request_plan(plan, profiles, default_require_production_eligible=not args.allow_non_production)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["all_requests_routed"] or args.allow_blocked:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
