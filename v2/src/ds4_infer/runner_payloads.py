from __future__ import annotations

from typing import Any

from .builders import apply_thinking_fields
from .profiles import ModelProfile
from .schemas import InferenceRequest

VLLM_CHAT_TOP_LEVEL_EXTRA_FIELDS = {
    "chat_template_kwargs",
    "thinking",
    "thinking_budget_tokens",
    "thinking_token_budget",
}


def requests_need_client_stream(requests: list[InferenceRequest]) -> bool:
    return bool(requests and all(bool(item.input.get("ds4_client_stream")) for item in requests))


def merge_request_extra_body(payload: dict[str, Any], request: InferenceRequest, profile: ModelProfile) -> None:
    extra_body: dict[str, Any] = {}
    raw_extra = request.input.get("openai_extra_body")
    if isinstance(raw_extra, dict):
        extra_body.update(raw_extra)
    apply_thinking_fields(extra_body, profile, chat=request.chat, thinking_budget_tokens=request.thinking_budget_tokens)
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
