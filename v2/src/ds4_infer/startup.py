from __future__ import annotations

import json
from typing import Any, Callable
from urllib import request as urlrequest

from .profiles import ModelProfile, ProfileRegistry
from .topology import SparkTopology

Poster = Callable[[str, dict[str, Any], int], dict[str, Any]]


EXECUTABLE_STARTUP_ACTIONS = {"warm", "group_primary_warm", "pipeline_ingress_warm"}


def startup_plan(*, topology: SparkTopology, registry: ProfileRegistry, node_id: str) -> dict[str, Any]:
    node = next((item for item in topology.nodes if item.node_id == node_id), None)
    if node is None:
        raise ValueError(f"unknown spark node: {node_id}")
    items: list[dict[str, Any]] = []
    pipeline_profile_ids = {service.profile_id for service in topology.pipeline_services.values()}
    for service in topology.pipeline_services.values():
        if node_id not in service.node_ids:
            continue
        profile = registry.get(service.profile_id)
        if bool(profile.routing.get("requires_profile_pin", False)) or not profile.production_eligible:
            continue
        stage = service.stage_for_node(node_id)
        if node_id == service.entry_node_id:
            item = _warm_item(profile, "pipeline_ingress_warm")
        else:
            item = {"profile_id": profile.profile_id, "model_id": profile.model_id, "backend": profile.backend, "action": "pipeline_stage"}
        item.update(
            {
                "service_id": service.service_id,
                "entry_node_id": service.entry_node_id,
                "api_base_url": service.api_base_url,
                "compute_domain": service.compute_domain,
                "stage_index": stage.stage_index,
                "stage_count": stage.stage_count,
                "layer_start": stage.layer_start,
                "layer_end": stage.layer_end,
                "layer_count": stage.layer_count,
            }
        )
        items.append(item)
    for profile_id in node.resident_profiles:
        if profile_id in pipeline_profile_ids:
            continue
        profile = registry.get(profile_id)
        if bool(profile.routing.get("requires_profile_pin", False)) or not profile.production_eligible:
            continue
        group = topology.profile_node_groups.get(profile_id, ())
        if group and group[0] != node_id:
            items.append({"profile_id": profile_id, "action": "group_secondary", "primary_node": group[0]})
            continue
        items.append(_warm_item(profile, "group_primary_warm" if group else "warm"))
    return {
        "format": "ds4-startup-model-plan-v1",
        "node_id": node_id,
        "dynamic_load": node.dynamic_load,
        "items": [] if node.dynamic_load else items,
    }


def warm_startup_models(*, plan: dict[str, Any], base_url: str, timeout_s: int, poster: Poster | None = None) -> dict[str, Any]:
    poster = poster or post_json
    results: list[dict[str, Any]] = []
    for item in plan.get("items", []):
        if item.get("action") not in EXECUTABLE_STARTUP_ACTIONS:
            results.append({"profile_id": item.get("profile_id"), "service_id": item.get("service_id"), "action": item.get("action"), "status": "skipped"})
            continue
        payload = dict(item["payload"])
        endpoints = [str(item["endpoint"])]
        endpoints.extend(str(endpoint) for endpoint in item.get("fallback_endpoints", []) if endpoint not in endpoints)
        try:
            response = None
            last_exc: Exception | None = None
            item_base_url = str(item.get("api_base_url") or base_url).rstrip("/")
            for endpoint in endpoints:
                try:
                    response = poster(item_base_url + endpoint, payload, timeout_s)
                    break
                except Exception as exc:
                    last_exc = exc
            if response is None:
                assert last_exc is not None
                raise last_exc
            results.append({"profile_id": item["profile_id"], "service_id": item.get("service_id"), "action": item["action"], "status": "completed", "response_keys": sorted(response)[:8]})
        except Exception as exc:
            results.append({"profile_id": item["profile_id"], "service_id": item.get("service_id"), "action": item["action"], "status": "failed", "error": str(exc)[-1000:]})
    failed = sum(1 for item in results if item.get("status") == "failed")
    return {
        "format": "ds4-startup-model-warmup-v1",
        "node_id": plan.get("node_id"),
        "base_url": base_url.rstrip("/"),
        "warm_count": sum(1 for item in results if item.get("status") == "completed"),
        "failed_count": failed,
        "status": "completed" if failed == 0 else "failed",
        "results": results,
    }


def post_json(url: str, payload: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=body, headers={"content-type": "application/json"}, method="POST")
    with urlrequest.urlopen(req, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _warm_item(profile: ModelProfile, action: str) -> dict[str, Any]:
    endpoint, payload = _warm_request(profile)
    payload = dict(payload)
    fallback_endpoints = payload.pop("fallback_endpoints", [])
    item = {
        "profile_id": profile.profile_id,
        "model_id": profile.model_id,
        "backend": profile.backend,
        "action": action,
        "endpoint": endpoint,
        "payload": payload,
    }
    if fallback_endpoints:
        item["fallback_endpoints"] = fallback_endpoints
    return item


def _warm_request(profile: ModelProfile) -> tuple[str, dict[str, Any]]:
    if profile.backend == "antirez":
        return "/v1/completions", {"model": profile.model_id, "prompt": "warmup", "n_predict": 1, "max_tokens": 1, "stream": False, "fallback_endpoints": ["/completion"]}
    if profile.supports_chat:
        return "/v1/chat/completions", {"model": profile.model_id, "messages": [{"role": "user", "content": "warmup"}], "max_tokens": 1, "temperature": 0}
    return "/v1/completions", {"model": profile.model_id, "prompt": "warmup", "max_tokens": 1, "temperature": 0}
