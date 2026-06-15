from __future__ import annotations

import threading
from typing import Any

from .builders import chat_template_thinking_enabled
from .env_utils import env_bool as _env_bool
from .profiles import ModelProfile


def openai_chat_input_payload(body: dict[str, Any], *, profile: ModelProfile, metadata: dict[str, Any], thinking_budget_tokens: int) -> dict[str, Any]:
    messages = _normalize_openai_messages(body.get("messages"))
    payload: dict[str, Any] = {"messages": messages, "metadata": metadata}
    if body.get("tools") is not None:
        payload["tools"] = body.get("tools")
    if body.get("tool_choice") is not None:
        payload["tool_choice"] = body.get("tool_choice")
    _attach_rendered_prompt(payload, body, profile, messages, metadata, thinking_budget_tokens)
    return payload


def anthropic_messages_input_payload(body: dict[str, Any], *, profile: ModelProfile, metadata: dict[str, Any], thinking_budget_tokens: int) -> dict[str, Any]:
    messages = _normalize_openai_messages(body.get("messages"))
    system = body.get("system")
    if isinstance(system, str) and system:
        messages = [{"role": "system", "content": system}, *messages]
    payload: dict[str, Any] = {"system": system, "messages": messages, "tools": body.get("tools"), "metadata": metadata}
    _attach_rendered_prompt(payload, body, profile, messages, metadata, thinking_budget_tokens)
    return payload


def rendered_chat_prompt_from_input(profile: ModelProfile, input_payload: dict[str, Any], *, thinking_budget_tokens: int) -> str:
    metadata = input_payload.get("metadata") if isinstance(input_payload.get("metadata"), dict) else {}
    prompt = _explicit_rendered_prompt(input_payload, metadata)
    if prompt:
        return prompt
    messages = _normalize_openai_messages(input_payload.get("messages"))
    return _render_chat_prompt(profile, messages, body=input_payload, metadata=metadata, thinking_budget_tokens=thinking_budget_tokens)


def _attach_rendered_prompt(payload: dict[str, Any], body: dict[str, Any], profile: ModelProfile, messages: list[dict[str, Any]], metadata: dict[str, Any], thinking_budget_tokens: int) -> None:
    prompt = _explicit_rendered_prompt(body, metadata)
    if not prompt and _env_bool("DS4_API_RENDER_CHAT_PROMPTS", True):
        prompt = _render_chat_prompt(profile, messages, body=body, metadata=metadata, thinking_budget_tokens=thinking_budget_tokens)
    if prompt:
        payload["prompt"] = prompt
        payload["rendered_prompt"] = prompt
        payload["estimated_prompt_tokens"] = _rough_prompt_tokens(prompt)


def _normalize_openai_messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_normalized_openai_message(item) for item in value if isinstance(item, dict)]


def _normalized_openai_message(item: dict[str, Any]) -> dict[str, Any]:
    message = {"role": str(item.get("role") or "user"), "content": _message_content_text(item.get("content"))}
    for key in ("name", "tool_call_id", "tool_calls"):
        if key in item:
            message[key] = item[key]
    return message


def _message_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_message_content_part_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    return "" if value is None else str(value)


def _message_content_part_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        text = item.get("text") or item.get("content")
        return text if isinstance(text, str) else ""
    return ""


def _explicit_rendered_prompt(body: dict[str, Any], metadata: dict[str, Any]) -> str:
    extra_body = body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}
    for container in (body, extra_body, metadata):
        if isinstance(container, dict):
            prompt = _prompt_from_container(container)
            if prompt:
                return prompt
    return ""


def _prompt_from_container(container: dict[str, Any]) -> str:
    for key in ("rendered_prompt", "prompt"):
        value = container.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _render_chat_prompt(profile: ModelProfile, messages: list[dict[str, Any]], *, body: dict[str, Any], metadata: dict[str, Any], thinking_budget_tokens: int) -> str:
    if not messages:
        return ""
    rendered = _render_chat_prompt_with_builtin(profile, messages, body=body, metadata=metadata, thinking_budget_tokens=thinking_budget_tokens)
    if rendered:
        return rendered
    rendered = _render_chat_prompt_with_tokenizer(profile, messages, body=body, metadata=metadata, thinking_budget_tokens=thinking_budget_tokens)
    if rendered:
        return rendered
    raise ValueError(f"tokenizer chat-template rendering failed for {profile.profile_id}; refuse fallback prompt")


def _render_chat_prompt_with_builtin(profile: ModelProfile, messages: list[dict[str, Any]], *, body: dict[str, Any], metadata: dict[str, Any], thinking_budget_tokens: int) -> str:
    renderer = str(profile.routing.get("chat_template_renderer") or "")
    if renderer == "deepseek_v4":
        return _deepseek_v4_chat_prompt(profile, messages, body=body, metadata=metadata, thinking_budget_tokens=thinking_budget_tokens)
    if renderer == "kimi_k2":
        return _kimi_k2_chat_prompt(profile, messages, body=body, metadata=metadata, thinking_budget_tokens=thinking_budget_tokens)
    return ""


def _deepseek_v4_chat_prompt(profile: ModelProfile, messages: list[dict[str, Any]], *, body: dict[str, Any], metadata: dict[str, Any], thinking_budget_tokens: int) -> str:
    if body.get("tools") is not None or body.get("tool_choice") is not None:
        raise ValueError("DeepSeek V4 DS API chat renderer does not support tool template rendering yet")
    parts: list[str] = ["<｜begin▁of▁sentence｜>"]
    index = 0
    if messages and messages[0].get("role") == "system":
        parts.append(str(messages[0].get("content") or ""))
        index = 1
    for message in messages[index:]:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "user":
            parts.append("<｜User｜>")
            parts.append(content)
        elif role == "assistant":
            parts.append("<｜Assistant｜>")
            parts.append(content)
            parts.append("<｜end▁of▁sentence｜>")
        else:
            raise ValueError(f"DeepSeek V4 DS API chat renderer does not support role={role!r}")
    thinking = _chat_template_kwargs_for_body(profile, body, metadata, thinking_budget_tokens).get("thinking")
    parts.append("<｜Assistant｜>")
    parts.append("<think>" if bool(thinking) else "</think>")
    return "".join(parts)


def _kimi_k2_chat_prompt(profile: ModelProfile, messages: list[dict[str, Any]], *, body: dict[str, Any], metadata: dict[str, Any], thinking_budget_tokens: int) -> str:
    if body.get("tools") is not None or body.get("tool_choice") is not None:
        raise ValueError("Kimi K2 DS API chat renderer does not support tool template rendering yet")
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user")
        role_name = str(message.get("name") or role)
        content = str(message.get("content") or "")
        if role == "user":
            parts.append(f"<|im_user|>{role_name}<|im_middle|>")
            parts.append(content)
        elif role == "assistant":
            if message.get("tool_calls") is not None:
                raise ValueError("Kimi K2 DS API chat renderer does not support assistant tool calls yet")
            reasoning = str(message.get("reasoning", message.get("reasoning_content", "")) or "")
            parts.append(f"<|im_assistant|>{role_name}<|im_middle|>")
            parts.append(f"<think>{reasoning}</think>")
            parts.append(content)
        elif role == "system":
            parts.append(f"<|im_system|>{role_name}<|im_middle|>")
            parts.append(content)
        elif role == "tool":
            raise ValueError("Kimi K2 DS API chat renderer does not support tool result messages yet")
        else:
            parts.append(f"<|im_system|>{role_name}<|im_middle|>")
            parts.append(content)
        parts.append("<|im_end|>")
    thinking = _chat_template_kwargs_for_body(profile, body, metadata, thinking_budget_tokens).get("thinking")
    parts.append("<|im_assistant|>assistant<|im_middle|>")
    parts.append("<think>" if bool(thinking) else "<think></think>")
    return "".join(parts)


def _render_chat_prompt_with_tokenizer(profile: ModelProfile, messages: list[dict[str, Any]], *, body: dict[str, Any], metadata: dict[str, Any], thinking_budget_tokens: int) -> str:
    if not _env_bool("DS4_API_RENDER_CHAT_WITH_TOKENIZER", True):
        return ""
    try:
        tokenizer = _tokenizer_for_chat_render(_chat_tokenizer_model_path(profile))
        kwargs = _chat_template_kwargs_for_body(profile, body, metadata, thinking_budget_tokens)
        if body.get("tools") is not None and "tools" not in kwargs:
            kwargs["tools"] = body.get("tools")
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, **kwargs)
    except Exception:
        return ""
    return rendered if isinstance(rendered, str) else ""


def _chat_tokenizer_model_path(profile: ModelProfile) -> str:
    return str(profile.routing.get("tokenizer_path") or profile.routing.get("model_path") or profile.model_id)


_TOKENIZER_CACHE: dict[str, Any] = {}
_TOKENIZER_CACHE_LOCK = threading.Lock()


def _tokenizer_for_chat_render(model_path: str) -> Any:
    with _TOKENIZER_CACHE_LOCK:
        tokenizer = _TOKENIZER_CACHE.get(model_path)
        if tokenizer is not None:
            return tokenizer
        from transformers import AutoTokenizer  # type: ignore
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        _TOKENIZER_CACHE[model_path] = tokenizer
        return tokenizer


def _chat_template_kwargs_for_body(profile: ModelProfile, body: dict[str, Any], metadata: dict[str, Any], thinking_budget_tokens: int) -> dict[str, Any]:
    merged = _merged_chat_template_kwargs(body, metadata)
    key = profile.routing.get("chat_template_thinking_key")
    if isinstance(key, str) and key and key not in merged and profile.supports_thinking:
        default_kwargs = profile.routing.get("default_chat_template_kwargs")
        default_enabled = None
        if isinstance(default_kwargs, dict) and key in default_kwargs:
            default_enabled = bool(default_kwargs[key])
        merged[key] = chat_template_thinking_enabled(
            model_id=profile.model_id,
            thinking_budget_tokens=thinking_budget_tokens,
            chat_template_thinking_key=key,
            default_thinking_enabled=default_enabled,
        )
    return merged


def _merged_chat_template_kwargs(body: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    extra_body = body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}
    merged: dict[str, Any] = {}
    for container in (extra_body.get("chat_template_kwargs"), body.get("chat_template_kwargs"), metadata.get("chat_template_kwargs")):
        if isinstance(container, dict):
            merged.update(container)
    return merged


def _fallback_render_chat_prompt(profile: ModelProfile, messages: list[dict[str, Any]]) -> str:
    if "qwen" in profile.model_id.lower():
        return _qwen_fallback_chat_prompt(messages)
    return _plain_fallback_chat_prompt(messages)


def _qwen_fallback_chat_prompt(messages: list[dict[str, Any]]) -> str:
    parts = [f"<|im_start|>{message.get('role', 'user')}\n{message.get('content', '')}<|im_end|>" for message in messages]
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def _plain_fallback_chat_prompt(messages: list[dict[str, Any]]) -> str:
    parts = [f"{message.get('role', 'user')}: {message.get('content', '')}" for message in messages]
    parts.append("assistant:")
    return "\n".join(parts)


def _rough_prompt_tokens(prompt: str) -> int:
    return max(1, len(prompt.encode("utf-8")) // 3)
