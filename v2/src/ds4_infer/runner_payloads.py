from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .builders import apply_thinking_fields
from .profiles import ModelProfile
from .schemas import InferenceRequest

AUTO_KV_BATCH_SUPPRESSED_KEY = "_ds4_auto_kv_suppressed_for_cohort"
AUTO_KV_PRESTAGE_PLAN_KEY = "_ds4_auto_kv_prestage_plan"
VLLM_CHAT_TOP_LEVEL_EXTRA_FIELDS = {
    "chat_template_kwargs",
    "thinking",
    "thinking_budget_tokens",
    "thinking_token_budget",
}
_AUTO_KV_STRICT_BATCH_POLICIES = {"strict", "strict-cache", "strict_cache", "prefer_cache", "cache"}


def requests_need_client_stream(requests: list[InferenceRequest]) -> bool:
    return bool(requests and all(bool(item.input.get("ds4_client_stream")) for item in requests))


def merge_request_extra_body(payload: dict[str, Any], request: InferenceRequest, profile: ModelProfile) -> None:
    extra_body: dict[str, Any] = {}
    raw_extra = request.input.get("openai_extra_body")
    if isinstance(raw_extra, dict):
        extra_body.update(raw_extra)
    apply_thinking_fields(extra_body, profile, chat=request.chat, thinking_budget_tokens=request.thinking_budget_tokens)
    if request.thinking_budget_tokens <= 0 and not (isinstance(raw_extra, dict) and "thinking" in raw_extra):
        extra_body.pop("thinking", None)
    if extra_body:
        merge_payload_extra_body(payload, extra_body)


def merge_payload_extra_body(payload: dict[str, Any], extra_body: dict[str, Any]) -> None:
    if not extra_body:
        return
    incoming = dict(extra_body)
    if isinstance(payload.get("messages"), list):
        for key in VLLM_CHAT_TOP_LEVEL_EXTRA_FIELDS:
            if key in incoming:
                payload[key] = incoming.pop(key)
    if incoming:
        payload["extra_body"] = {**dict(payload.get("extra_body") or {}), **incoming}


def maybe_suppress_generated_auto_kv_for_cohort(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    policy = os.environ.get("DS4_PIPELINE_AUTO_KV_BATCH_POLICY", "prefer_batch").strip().lower()
    if policy in _AUTO_KV_STRICT_BATCH_POLICIES:
        return payload, False
    extra_body = payload.get("extra_body")
    plan = extra_body.get("ds4_kv_cache") if isinstance(extra_body, dict) else None
    transfer = payload.get("kv_transfer_params")
    transfer_plan = transfer.get("ds4_kv_cache") if isinstance(transfer, dict) else None
    cache_id = plan.get("cache_id") if isinstance(plan, dict) else None
    transfer_cache_id = transfer_plan.get("cache_id") if isinstance(transfer_plan, dict) else None
    if not (isinstance(cache_id, str) and cache_id.startswith("ds4-auto:")):
        return payload, False
    if not (isinstance(transfer_cache_id, str) and transfer_cache_id.startswith("ds4-auto:")):
        return payload, False
    cleaned = dict(payload)
    cleaned.pop("kv_transfer_params", None)
    cleaned_extra_body = dict(extra_body or {})
    cleaned_extra_body.pop("ds4_kv_cache", None)
    if cleaned_extra_body:
        cleaned["extra_body"] = cleaned_extra_body
    else:
        cleaned.pop("extra_body", None)
    return cleaned, True


def coalesced_auto_kv_prestage_material(requests: list[InferenceRequest], payload: dict[str, Any], profile: ModelProfile, *, prefix: str, service_id: str | None) -> dict[str, Any]:
    return {
        "format": "ds4-auto-kv-cache-key-v1",
        "chat": False,
        "messages": None,
        "prompt": prefix,
        "model": payload.get("model"),
        "profile_id": profile.profile_id,
        "runtime_contract_id": profile.runtime_contract_id,
        "service_id": service_id,
        "thinking_budget_tokens": requests[0].thinking_budget_tokens,
        "extra_body": dict(payload.get("extra_body") or {}),
    }


def auto_kv_cache_plan_from_material(material: dict[str, Any], payload: dict[str, Any], profile: ModelProfile, *, service_id: str | None, backend: str, cache_kind: str = "") -> dict[str, Any]:
    digest = hashlib.sha256(_json_dumps_canonical(material).encode("utf-8")).hexdigest()
    cache_scope = service_id or profile.profile_id
    kind = f"{cache_kind}:" if cache_kind else ""
    cache_id = f"ds4-auto:{kind}{cache_scope}:{digest[:32]}"
    plan = {
        "format": "ds4-kv-cache-plan-v1",
        "backend": backend,
        "cache_id": cache_id,
        "prefix_hash": "sha256:" + digest,
        "load": {"mode": "prefer", "transport": "local_store", "cache_key": cache_id},
        "store": {"mode": "write_back", "transport": "local_store", "cache_key": cache_id, "on_error": "warn"},
        "miss_policy": "compute_and_store",
        "route_affinity": "preferred",
        "model_fingerprint": {
            "model_id": str(payload.get("model") or profile.model_id),
            "profile_id": profile.profile_id,
            "runtime_contract_id": profile.runtime_contract_id,
            "service_id": service_id,
        },
        "operation": "load_store",
    }
    plan["batch_key_hash"] = "sha256:" + hashlib.sha256(_json_dumps_canonical(_auto_kv_batch_key_material(plan)).encode("utf-8")).hexdigest()
    return plan


def kv_plan_has_strict_load(plan: dict[str, Any] | None) -> bool:
    if plan is None:
        return False
    load = plan.get("load")
    if not isinstance(load, dict):
        return False
    if str(load.get("mode") or "skip") not in {"prefer", "require"}:
        return False
    miss_policy = str(plan.get("miss_policy") or "")
    return str(load.get("mode") or "") == "require" or miss_policy == "fail"


def kv_plan_is_prestageable_auto(plan: dict[str, Any] | None) -> bool:
    if plan is None:
        return False
    cache_id = plan.get("cache_id")
    load = plan.get("load")
    store = plan.get("store")
    if not isinstance(cache_id, str) or not cache_id.startswith("ds4-auto:"):
        return False
    if not isinstance(load, dict) or str(load.get("mode") or "") != "prefer":
        return False
    if not isinstance(store, dict) or str(store.get("mode") or "") != "write_back":
        return False
    return str(plan.get("miss_policy") or "") == "compute_and_store"


def _auto_kv_batch_key_material(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": plan["backend"],
        "cache_id": plan["cache_id"],
        "prefix_hash": plan["prefix_hash"],
        "load": plan["load"],
        "store": plan["store"],
        "miss_policy": plan["miss_policy"],
        "route_affinity": plan["route_affinity"],
        "model_fingerprint": plan["model_fingerprint"],
    }


def _json_dumps_canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
