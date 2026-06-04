from __future__ import annotations

from typing import Any

from .builders import apply_thinking_fields
from .profiles import ModelProfile
from .schemas import InferenceRequest


def requests_need_client_stream(requests: list[InferenceRequest]) -> bool:
    return bool(requests and all(bool(item.input.get("ds4_client_stream")) for item in requests))


def merge_request_extra_body(payload: dict[str, Any], request: InferenceRequest, profile: ModelProfile) -> None:
    extra_body: dict[str, Any] = {}
    raw_extra = request.input.get("openai_extra_body")
    if isinstance(raw_extra, dict):
        extra_body.update(raw_extra)
    apply_thinking_fields(extra_body, profile, chat=request.chat, thinking_budget_tokens=request.thinking_budget_tokens)
    if extra_body:
        payload["extra_body"] = {**dict(payload.get("extra_body") or {}), **extra_body}
