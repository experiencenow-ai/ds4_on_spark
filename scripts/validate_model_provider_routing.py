#!/usr/bin/env python3
"""Validate Centaur provider route request and routing-plan artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import route_model_provider_requests as router
from scripts import select_model_provider
from scripts._lib.json_utils import check_bool_field
from scripts._lib.json_utils import check_non_empty_string_field


def default_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted((root / "fixtures" / "model_provider_routes").glob("*.json"))


def err(path: Path, msg: str) -> str:
    return f"{path}: {msg}"


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception as e:
        return None, [err(path, str(e))]
    if not isinstance(obj, dict):
        return None, [err(path, "root JSON must be an object")]
    return obj, []


def check_int(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> int:
    value = obj.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(err(path, f"{field} must be a non-negative integer"))
        return 0
    return int(value)


def check_bool(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> bool:
    return check_bool_field(obj, field, path, errors)


def check_string(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> str:
    return check_non_empty_string_field(obj, field, path, errors)


def check_number_or_null(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> None:
    value = obj.get(field)
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(err(path, f"{field} must be a number or null"))


def validate_route(route: dict[str, Any], path: Path, index: int) -> list[str]:
    errors: list[str] = []
    prefix = f"routes[{index}]"
    check_string(route, "node_id", path, errors)
    required_tier = check_string(route, "required_tier", path, errors)
    if required_tier and required_tier not in select_model_provider.TIER_RANK:
        errors.append(err(path, f"{prefix}.required_tier is unknown: {required_tier}"))
    check_string(route, "lane", path, errors)
    check_int(route, "batch_tokens", path, errors)
    selected = check_bool(route, "selected", path, errors)
    check_number_or_null(route, "estimated_service_ms_at_measured_output_tps", path, errors)
    if selected:
        provider_id = route.get("provider_id")
        if not isinstance(provider_id, str) or provider_id.strip() == "":
            errors.append(err(path, f"{prefix}.provider_id must be present when selected"))
        if route.get("blocker_kind") is not None:
            errors.append(err(path, f"{prefix}.blocker_kind must be null when selected"))
    else:
        if route.get("provider_id") is not None:
            errors.append(err(path, f"{prefix}.provider_id must be null when blocked"))
        blocker = route.get("blocker_kind")
        if not isinstance(blocker, str) or blocker.strip() == "":
            errors.append(err(path, f"{prefix}.blocker_kind must be present when blocked"))
        if not isinstance(route.get("rejection_summary"), dict):
            errors.append(err(path, f"{prefix}.rejection_summary must be present when blocked"))
    return errors


def validate_routing_plan(obj: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    if obj.get("format") != router.PLAN_FORMAT:
        errors.append(err(path, f"format must be {router.PLAN_FORMAT}"))
    check_string(obj, "run_id", path, errors)
    request_count = check_int(obj, "request_count", path, errors)
    selected_count = check_int(obj, "selected_count", path, errors)
    blocked_count = check_int(obj, "blocked_count", path, errors)
    all_requests_routed = check_bool(obj, "all_requests_routed", path, errors)
    routes = obj.get("routes")
    if not isinstance(routes, list):
        errors.append(err(path, "routes must be a list"))
        routes = []
    for i, route in enumerate(routes):
        if not isinstance(route, dict):
            errors.append(err(path, f"routes[{i}] must be an object"))
            continue
        errors.extend(validate_route(route, path, i))
    actual_selected = sum(1 for route in routes if isinstance(route, dict) and route.get("selected") is True)
    actual_blocked = len(routes) - actual_selected
    if request_count != len(routes):
        errors.append(err(path, "request_count must equal len(routes)"))
    if selected_count != actual_selected:
        errors.append(err(path, "selected_count must match selected routes"))
    if blocked_count != actual_blocked:
        errors.append(err(path, "blocked_count must match blocked routes"))
    if all_requests_routed != (actual_blocked == 0):
        errors.append(err(path, "all_requests_routed must match blocked_count == 0"))
    expected_load = router.provider_load([route for route in routes if isinstance(route, dict)])
    expected_blockers = router.blocker_summary([route for route in routes if isinstance(route, dict)])
    expected_capacity = router.capacity_summary(expected_load, actual_blocked)
    if obj.get("provider_load") != expected_load:
        errors.append(err(path, "provider_load does not match routes"))
    if obj.get("blocker_summary") != expected_blockers:
        errors.append(err(path, "blocker_summary does not match routes"))
    if obj.get("capacity_summary") != expected_capacity:
        errors.append(err(path, "capacity_summary does not match provider_load/routes"))
    return errors


def validate_artifact(obj: dict[str, Any], path: Path) -> list[str]:
    fmt = obj.get("format")
    if fmt == router.REQUEST_FORMAT:
        return [err(path, item) for item in router.validate_request_plan(obj)]
    if fmt == router.PLAN_FORMAT:
        return validate_routing_plan(obj, path)
    return [err(path, f"format must be {router.REQUEST_FORMAT} or {router.PLAN_FORMAT}")]


def validate_paths(paths: list[Path]) -> dict[str, Any]:
    errors: list[str] = []
    for path in paths:
        obj, load_errors = load_json(path)
        if load_errors:
            errors.extend(load_errors)
            continue
        assert obj is not None
        errors.extend(validate_artifact(obj, path))
    return {"ok": len(errors) == 0, "artifact_count": len(paths), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Centaur provider routing request/plan artifacts.")
    parser.add_argument("artifacts", nargs="*", help="JSON artifacts. Defaults to fixtures/model_provider_routes/*.json.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    paths = [Path(item) for item in args.artifacts] if args.artifacts else default_paths()
    result = validate_paths(paths)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"ok: validated {result['artifact_count']} provider routing artifact(s)")
    else:
        for item in result["errors"]:
            print(item)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
