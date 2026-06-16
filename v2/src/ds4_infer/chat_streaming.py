from __future__ import annotations

import time
from threading import Event
from typing import Any, Callable, Iterator

from .cohort_safety import prompt_token_estimate
from .profiles import ModelProfile
from .schemas import InferenceRequest, make_result


TransportFailure = Callable[[InferenceRequest, ModelProfile, float, str], dict]


def run_parallel_chat_stream(
    *,
    post_sse_json: Callable[..., Iterator[dict[str, Any]]],
    transport_failure: Callable[..., dict],
    request: InferenceRequest,
    profile: ModelProfile,
    payload: dict[str, Any],
    base_url: str,
    endpoint: str,
    started: float,
    batch_size: int,
    cancel_event: Event,
) -> dict:
    text_parts: list[str] = []
    usage: dict[str, Any] = {}
    stream_payload = dict(payload)
    stream_payload["stream"] = True
    try:
        for event in post_sse_json(endpoint, stream_payload, cancel_event=cancel_event):
            _merge_usage(usage, event)
            for choice in _event_choices(event):
                delta = _choice_text(choice)
                if delta:
                    text_parts.append(delta)
                if choice.get("finish_reason") is not None:
                    return _stream_result(request, profile, "".join(text_parts), base_url, endpoint, started, batch_size, usage)
            if cancel_event.is_set():
                break
    except Exception as exc:
        return transport_failure(request, profile, started, str(exc), endpoint=endpoint, coalesced_batch_size=batch_size)
    if cancel_event.is_set():
        return transport_failure(request, profile, started, "parallel chat stream cancelled", endpoint=endpoint, coalesced_batch_size=batch_size)
    text = "".join(text_parts)
    if text:
        return _stream_result(request, profile, text, base_url, endpoint, started, batch_size, usage)
    return transport_failure(request, profile, started, "parallel chat stream ended before completion", endpoint=endpoint, coalesced_batch_size=batch_size)


def _event_choices(event: dict[str, Any]) -> list[dict[str, Any]]:
    choices = event.get("choices")
    if not isinstance(choices, list):
        return []
    return [choice for choice in choices if isinstance(choice, dict)]


def _choice_text(choice: dict[str, Any]) -> str:
    for container_name, keys in (
        ("delta", ("content", "reasoning_content", "reasoning", "text")),
        ("message", ("content", "reasoning_content", "reasoning")),
    ):
        container = choice.get(container_name)
        if isinstance(container, dict):
            for key in keys:
                value = container.get(key)
                if isinstance(value, str):
                    return _strip_visible_thinking(value)
    text = choice.get("text")
    return _strip_visible_thinking(text) if isinstance(text, str) else ""


def _stream_result(request: InferenceRequest, profile: ModelProfile, text: str, base_url: str, endpoint: str, started: float, batch_size: int, usage: dict[str, Any]) -> dict:
    result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=_strip_visible_thinking(text))
    result["usage"].update(_stream_usage(request, text, usage))
    result["transport"] = {"base_url": base_url, "endpoint": endpoint, "duration_s": round(time.time() - started, 6), "coalesced_chat_parallel": True, "coalesced_chat_parallel_streaming": True, "coalesced_batch_size": batch_size, "batch_size": batch_size}
    return result


def _merge_usage(usage: dict[str, Any], event: dict[str, Any]) -> None:
    event_usage = event.get("usage")
    if isinstance(event_usage, dict):
        usage.update(event_usage)


def _strip_visible_thinking(text: str) -> str:
    marker = "</think>"
    return text.split(marker, 1)[1].lstrip() if marker in text else text


def _stream_usage(request: InferenceRequest, text: str, usage: dict[str, Any]) -> dict[str, Any]:
    out = dict(usage) if usage else {}
    prompt_text = _request_prompt_text(request)
    if "completion_tokens" not in out:
        out["completion_tokens"] = _estimate_text_tokens(text)
        out["completion_tokens_estimated"] = True
    if "prompt_tokens" not in out and prompt_text:
        out["prompt_tokens"] = prompt_token_estimate(prompt_text)
        out["prompt_tokens_estimated"] = True
    if "total_tokens" not in out:
        total = 0
        for key in ("prompt_tokens", "completion_tokens"):
            value = out.get(key)
            if isinstance(value, int):
                total += value
        if total > 0:
            out["total_tokens"] = total
    return out


def _request_prompt_text(request: InferenceRequest) -> str:
    raw_input = request.raw.get("input") if isinstance(request.raw, dict) else None
    if not isinstance(raw_input, dict):
        return ""
    for key in ("rendered_prompt", "prompt"):
        value = raw_input.get(key)
        if isinstance(value, str):
            return value
    messages = raw_input.get("messages")
    if isinstance(messages, list):
        return "\n".join(_message_content_text(message) for message in messages if isinstance(message, dict))
    shared_prefix = raw_input.get("shared_prefix")
    suffix = raw_input.get("suffix")
    parts = [part for part in (shared_prefix, suffix) if isinstance(part, str)]
    return "\n".join(parts)


def _message_content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for key in ("text", "content"):
                value = item.get(key)
                if isinstance(value, str):
                    parts.append(value)
                    break
    return "\n".join(parts)


def _estimate_text_tokens(text: str) -> int:
    if text == "":
        return 0
    return max(1, (len(text.encode("utf-8")) + 3) // 4)
