from __future__ import annotations

import uuid
from typing import Any

from .kv_cache import kv_cache_extra_body
from .profiles import ModelProfile, ProfileRegistry
from .schemas import InferenceRequest

MODEL_ALIASES = {
    "deepseek-ai/DeepSeek-V4-Flash": "dsv4_vllm_mtp_pp8_smartest_v1",
    "ds4v": "dsv4_vllm_mtp_pp8_smartest_v1",
    "dsv4": "dsv4_vllm_mtp_pp8_smartest_v1",
    "gemma": "gemma4_26b_a4b_it_pp8_peer_v1",
    "gemma4": "gemma4_26b_a4b_it_pp8_peer_v1",
    "gemma12": "gemma4_12b_it_pp8_peer_v1",
    "gemma4-12b": "gemma4_12b_it_pp8_peer_v1",
    "gemma-e2b": "gemma4_e2b_it_pp8_peer_v1",
    "gemma-e4b": "gemma4_e4b_it_pp8_peer_v1",
    "gemma26": "gemma4_26b_a4b_it_pp8_peer_v1",
    "gemma-a4b": "gemma4_26b_a4b_it_pp8_peer_v1",
    "gemma-pp13": "gemma4_26b_a4b_it_pp13_peer_v1",
    "gemma26-pp13": "gemma4_26b_a4b_it_pp13_peer_v1",
    "gemma-a4b-pp13": "gemma4_26b_a4b_it_pp13_peer_v1",
    "gemma31": "gemma4_31b_it_pp8_peer_v1",
    "kimi": "kimi27_code_pp13_smart_v1",
    "kimi26": "kimi26_pp13_smart_v1",
    "kimi-k2.6": "kimi26_pp13_smart_v1",
    "kimi2.6": "kimi26_pp13_smart_v1",
    "moonshotai/Kimi-K2.6": "kimi26_pp13_smart_v1",
    "kimi27": "kimi27_code_pp13_smart_v1",
    "kimi-k2.7-code": "kimi27_code_pp13_smart_v1",
    "kimi2.7": "kimi27_code_pp13_smart_v1",
    "moonshotai/Kimi-K2.7-Code": "kimi27_code_pp13_smart_v1",
    "qwen": "qwen3_6_27b_bf16_pp8_efficient_v1",
    "qwen16": "qwen3_6_27b_bf16_pp8_efficient_v1",
    "qwen27": "qwen3_6_27b_bf16_pp8_efficient_v1",
    "qwen-bf16": "qwen3_6_27b_bf16_pp8_efficient_v1",
    "qwen27-bf16": "qwen3_6_27b_bf16_pp8_efficient_v1",
    "qwen-pp13": "qwen3_6_27b_bf16_pp13_efficient_v1",
    "qwen27-pp13": "qwen3_6_27b_bf16_pp13_efficient_v1",
    "qwen-bf16-pp13": "qwen3_6_27b_bf16_pp13_efficient_v1",
    "fast": "qwen3_6_35b_a3b_fp8_fastest_v1",
}


def resolve_model_alias(model: str) -> str:
    return MODEL_ALIASES.get(model, model)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def safe_request_id(value: str, index: int, seen: set[str] | None = None) -> str:
    base = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value).strip(".-_")
    base = base or f"request-{index}"
    candidate = base
    if seen is not None:
        suffix = 1
        while candidate in seen:
            candidate = f"{base}-{index}-{suffix}"
            suffix += 1
        seen.add(candidate)
    return candidate


def request_prompt(request: InferenceRequest) -> str:
    data = request.input
    if isinstance(data.get("prompt"), str):
        return str(data["prompt"])
    parts: list[str] = []
    for key in ("shared_prefix", "suffix", "target", "instruction"):
        value = data.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if not parts and isinstance(data.get("messages"), list):
        parts.extend(str(message.get("content", "")) for message in data["messages"] if isinstance(message, dict))
    return "\n\n".join(parts)


def request_messages(request: InferenceRequest) -> list[dict[str, str]]:
    raw_messages = request.input.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        messages: list[dict[str, str]] = []
        for message in raw_messages:
            if isinstance(message, dict):
                messages.append({"role": str(message.get("role", "user")), "content": str(message.get("content", ""))})
        if messages:
            return messages
    messages = []
    system = request.input.get("system")
    if isinstance(system, str) and system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": request_prompt(request)})
    return messages


def json_safe_messages(messages: list[dict]) -> list[dict]:
    safe: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        safe_message: dict[str, Any] = {
            "role": str(message.get("role", "user")),
            "content": str(message.get("content", "")),
        }
        for key in ("tool_call_id", "name", "tool_calls"):
            if key in message:
                safe_message[key] = message[key] if key == "tool_calls" else str(message[key])
        safe.append(safe_message)
    return safe


def transcript(messages: list[dict]) -> str:
    return "\n".join(f"{message.get('role','user')}: {message.get('content','')}" for message in messages)


def preferred_job_class(supported: tuple[str, ...], chat: bool) -> str:
    preferred = (
        ("tool_chat", "analysis", "summary", "atom_edit")
        if chat
        else ("atom_edit", "analysis", "summary", "triage")
    )
    for job_class in preferred:
        if job_class in supported:
            return job_class
    return supported[0]


def sparkrunner_request(
    record: dict[str, Any],
    model: str,
    registry: ProfileRegistry,
    index: int,
    seen: set[str] | None = None,
) -> InferenceRequest:
    profile = registry.get(resolve_model_alias(model))
    custom_id = str(record.get("custom_id") or record.get("request_id") or f"request-{index}")
    messages = record.get("messages")
    raw_messages = messages if isinstance(messages, list) else []
    chat = bool(profile.supports_chat and raw_messages)
    prompt = str(
        record.get("prompt")
        or "\n".join(str(message.get("content", "")) for message in raw_messages if isinstance(message, dict))
    )
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": safe_request_id(custom_id, index, seen),
            "capability": None,
            "chat": chat,
            "immediate": bool(record.get("immediate", False)),
            "job_class": str(record.get("job_class") or preferred_job_class(profile.supported_job_classes, chat)),
            "max_output_tokens": int(record.get("max_tokens") or record.get("max_completion_tokens") or 1024),
            "thinking_budget_tokens": int(record.get("thinking_budget_tokens") or 0),
            "temperature": float(record.get("temperature", 0.0)),
            "input": {"messages": raw_messages, "prompt": prompt, "suffix": prompt},
            "output_contract": dict(record.get("output_contract") or {"format": "text"}),
            "model_pin": {"profile_id": profile.profile_id},
        }
    )


def chat_request(
    messages: list[dict],
    registry: ProfileRegistry,
    model_alias: str,
    max_tokens: int,
    temperature: float,
) -> InferenceRequest:
    profile = registry.get(resolve_model_alias(model_alias))
    safe = json_safe_messages(messages)
    chat = bool(profile.supports_chat)
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": new_id("chat"),
            "capability": None,
            "chat": chat,
            "immediate": True,
            "job_class": preferred_job_class(profile.supported_job_classes, chat),
            "max_output_tokens": max_tokens,
            "thinking_budget_tokens": 0,
            "temperature": temperature,
            "input": {"messages": safe, "prompt": transcript(safe)},
            "output_contract": {"format": "text"},
            "model_pin": {"profile_id": profile.profile_id},
        }
    )


def apply_thinking_fields(
    item: dict[str, Any],
    profile: ModelProfile,
    *,
    chat: bool,
    thinking_budget_tokens: int,
) -> None:
    key = profile.routing.get("chat_template_thinking_key")
    default_kwargs = profile.routing.get("default_chat_template_kwargs")
    default_enabled = None
    if isinstance(default_kwargs, dict) and isinstance(key, str) and key in default_kwargs:
        default_enabled = bool(default_kwargs[key])
    apply_thinking_fields_for_model(
        item,
        model_id=profile.model_id,
        supports_thinking=profile.supports_thinking,
        chat=chat,
        thinking_budget_tokens=thinking_budget_tokens,
        chat_template_thinking_key=str(key) if key else None,
        default_thinking_enabled=default_enabled,
    )


def thinking_request_fields(profile: ModelProfile, *, chat: bool, thinking_budget_tokens: int) -> dict[str, Any]:
    item: dict[str, Any] = {}
    apply_thinking_fields(item, profile, chat=chat, thinking_budget_tokens=thinking_budget_tokens)
    return item


def apply_thinking_fields_for_model(
    item: dict[str, Any],
    *,
    model_id: str,
    supports_thinking: bool,
    chat: bool,
    thinking_budget_tokens: int,
    chat_template_thinking_key: str | None = None,
    default_thinking_enabled: bool | None = None,
) -> None:
    if not supports_thinking:
        return
    thinking_enabled = chat_template_thinking_enabled(
        model_id=model_id,
        thinking_budget_tokens=thinking_budget_tokens,
        chat_template_thinking_key=chat_template_thinking_key,
        default_thinking_enabled=default_thinking_enabled,
    )
    if thinking_budget_tokens > 0:
        item["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget_tokens}
        item["thinking_budget_tokens"] = thinking_budget_tokens
        item["thinking_token_budget"] = thinking_budget_tokens
    elif thinking_enabled:
        item["thinking"] = {"type": "enabled"}
    elif not omit_disabled_thinking_field(model_id=model_id, chat_template_thinking_key=chat_template_thinking_key):
        item["thinking"] = {"type": "disabled"}
    if chat:
        key = chat_template_thinking_key or default_chat_template_thinking_key(model_id)
        if key:
            item["chat_template_kwargs"] = {key: thinking_enabled}


def chat_template_thinking_enabled(
    *,
    model_id: str,
    thinking_budget_tokens: int,
    chat_template_thinking_key: str | None = None,
    default_thinking_enabled: bool | None = None,
) -> bool:
    if thinking_budget_tokens > 0:
        return True
    if default_thinking_enabled is not None:
        return bool(default_thinking_enabled)
    return False


def default_chat_template_thinking_key(model_id: str) -> str | None:
    return "enable_thinking" if "qwen" in model_id.lower() else None


def omit_disabled_thinking_field(*, model_id: str, chat_template_thinking_key: str | None = None) -> bool:
    lowered = model_id.lower()
    return "deepseek-v4" in lowered or "deepseek_v4" in lowered or chat_template_thinking_key == "thinking"


def model_batch_item(request: InferenceRequest, profile: ModelProfile) -> dict[str, Any]:
    max_tokens = request.max_output_tokens + request.thinking_budget_tokens
    item: dict[str, Any] = {
        "custom_id": request.request_id,
        "max_tokens": max_tokens,
        "temperature": request.temperature,
    }
    apply_thinking_fields(item, profile, chat=request.chat, thinking_budget_tokens=request.thinking_budget_tokens)
    if request.chat:
        item["messages"] = request_messages(request)
    else:
        item["prompt"] = request_prompt(request)
    extra_body = kv_cache_extra_body(request.input)
    if extra_body:
        item["kv_cache"] = extra_body["ds4_kv_cache"]
        item["extra_body"] = {**dict(item.get("extra_body") or {}), **extra_body}
    return item


def model_batch_payload(
    requests: list[InferenceRequest],
    profile: ModelProfile,
    *,
    timeout_s: int,
    concurrency: int,
) -> dict[str, Any]:
    if not requests:
        raise ValueError("model batch requires at least one request")
    items = [model_batch_item(request, profile) for request in requests]
    max_tokens = max(int(item.get("max_tokens", 1)) for item in items)
    return {
        "model": profile.model_id,
        "items": items,
        "concurrency": max(1, concurrency),
        "timeout_s": timeout_s,
        "max_tokens": max_tokens,
    }
