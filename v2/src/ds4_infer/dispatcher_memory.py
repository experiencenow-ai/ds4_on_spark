from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import urlencode
import urllib.request

from .dispatcher_resident import pending_claim_count
from .topology import SparkTopology, pipeline_service_client_base_url


def topology_coordinator_defaults(topology: SparkTopology) -> dict[str, Any]:
    routing = topology.routing_policy if isinstance(topology.routing_policy, dict) else {}
    raw = routing.get("resident_coordinator_defaults")
    return dict(raw) if isinstance(raw, dict) else {}


def dict_bool(values: dict[str, Any], key: str, default: bool) -> bool:
    if key not in values or values.get(key) is None:
        return bool(default)
    value = values[key]
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def dict_float(values: dict[str, Any], key: str, default: float) -> float:
    if key not in values or values.get(key) is None:
        return float(default)
    return float(values[key])


def dispatcher_runtime_options(topology: SparkTopology, environ: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    defaults = topology_coordinator_defaults(topology)
    return {
        "dispatcher_resident_prefer_cohort_batch": _env_bool(env, "DS4_API_RESIDENT_PREFER_COHORT_BATCH", dict_bool(defaults, "prefer_cohort_batch", False)),
        "dispatcher_trim_on_host_memory": _env_bool(env, "DS4_API_TRIM_ON_HOST_MEMORY_THROTTLE", dict_bool(defaults, "trim_on_host_memory_pressure", False)),
        "dispatcher_trim_cooldown_s": max(0.0, _env_float(env, "DS4_API_TRIM_MEMORY_COOLDOWN_S", dict_float(defaults, "trim_memory_cooldown_s", 120.0))),
        "dispatcher_trim_timeout_s": max(1.0, _env_float(env, "DS4_API_TRIM_MEMORY_TIMEOUT_S", dict_float(defaults, "trim_memory_timeout_s", 120.0))),
        "dispatcher_trim_mode": str(env.get("DS4_API_TRIM_MEMORY_MODE") or defaults.get("trim_memory_mode") or "wait"),
        "_last_host_memory_trim_at": 0.0,
    }


def try_trim_host_memory(
    *,
    status: dict[str, Any],
    pending: dict[Any, Any],
    enabled: bool,
    cooldown_s: float,
    last_trim_at: float,
    mode: str,
    timeout_s: float,
    topology: SparkTopology,
) -> tuple[dict[str, Any], float]:
    reasons = [str(item) for item in status.get("throttle_reasons") or []]
    now = time.time()
    if not enabled:
        return ({"attempted": False, "reason": "disabled"}, last_trim_at)
    if not any(reason.startswith("host_memory") for reason in reasons):
        return ({"attempted": False, "reason": "not_host_memory", "throttle_reasons": reasons}, last_trim_at)
    pending_count = pending_claim_count(pending)
    if pending_count > 0:
        return ({"attempted": False, "reason": "active_work_present", "pending": pending_count, "throttle_reasons": reasons}, last_trim_at)
    cooldown_remaining = float(cooldown_s) - (now - float(last_trim_at))
    if cooldown_remaining > 0.0:
        return ({"attempted": False, "reason": "cooldown", "cooldown_remaining_s": round(cooldown_remaining, 3), "throttle_reasons": reasons}, last_trim_at)
    services = active_pipeline_services(topology)
    results = [trim_pipeline_service_memory(service, mode=mode, timeout_s=timeout_s) for service in services]
    ok = bool(results) and all(bool(item.get("ok")) for item in results)
    return (_trim_result_payload(status=status, reasons=reasons, mode=mode, results=results, ok=ok), now)


def active_pipeline_services(topology: SparkTopology) -> list[Any]:
    active = _active_resident_service_ids(topology)
    return [
        service
        for service in topology.pipeline_services.values()
        if active is None or service.service_id in active
    ]


def trim_pipeline_service_memory(service: Any, *, mode: str, timeout_s: float) -> dict[str, Any]:
    base_url = pipeline_service_client_base_url(service)
    url = f"{base_url.rstrip('/')}/v1/trim_memory?{_trim_query(mode)}"
    started = time.time()
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s))) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", 200)
    except Exception as exc:
        return {"service_id": service.service_id, "api_base_url": base_url, "ok": False, "duration_s": round(time.time() - started, 6), "error": str(exc)}
    return {"service_id": service.service_id, "api_base_url": base_url, "ok": 200 <= int(status_code) < 300, "status": int(status_code), "duration_s": round(time.time() - started, 6), "response": _parse_body(body)}


def _trim_query(mode: str) -> str:
    return urlencode({"mode": mode, "reset_external": "true", "release_offload_memory": "true", "malloc_trim": "true", "resume": "true"})


def _parse_body(body: str) -> Any:
    try:
        return json.loads(body) if body.strip() else None
    except json.JSONDecodeError:
        return body[-1000:]


def _trim_result_payload(*, status: dict[str, Any], reasons: list[str], mode: str, results: list[dict[str, Any]], ok: bool) -> dict[str, Any]:
    return {"attempted": True, "ok": ok, "mode": mode, "throttle_reasons": reasons, "max_host_memory_node": status.get("max_host_memory_node"), "max_host_memory_used_pct": status.get("max_host_memory_used_pct"), "services": results}


def _active_resident_service_ids(topology: SparkTopology) -> set[str] | None:
    raw = topology.routing_policy.get("active_resident_service_ids")
    if raw is None:
        return None
    if isinstance(raw, str):
        return {item.strip() for item in raw.replace(";", ",").split(",") if item.strip()}
    if isinstance(raw, list):
        return {str(item) for item in raw if str(item)}
    return None


def _env_bool(environ: dict[str, str], name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None or value == "":
        return bool(default)
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _env_float(environ: dict[str, str], name: str, default: float) -> float:
    value = environ.get(name)
    if value is None or value == "":
        return float(default)
    return float(value)
