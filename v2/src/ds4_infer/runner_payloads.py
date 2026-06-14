from __future__ import annotations

import os
from typing import Any

from .builders import apply_thinking_fields
from .profiles import ModelProfile
from .schemas import InferenceRequest

AUTO_KV_BATCH_SUPPRESSED_KEY = "_ds4_auto_kv_suppressed_for_cohort"
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
