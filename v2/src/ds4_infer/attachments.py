from __future__ import annotations

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any

from .profiles import ModelProfile

ATTACHMENT_CONTEXT_FORMAT = "ds4-attachment-context-v1"
DEFAULT_CHUNK_TOKENS = 8192
DEFAULT_CONTEXT_RESERVE_TOKENS = 2048
ROUGH_BYTES_PER_TOKEN = 3


@dataclass(frozen=True)
class AttachmentChunk:
    attachment_index: int
    chunk_index: int
    name: str
    mime_type: str
    text: str
    byte_count: int
    estimated_tokens: int
    content_sha256: str


def attach_request_files_to_messages(body: dict[str, Any], profile: ModelProfile, messages: list[dict[str, Any]], *, max_output_tokens: int, thinking_budget_tokens: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    attachments = _request_attachments(body)
    if not attachments:
        return messages, None
    chunk_tokens = _positive_int(_setting(body, "ds4_attachment_chunk_tokens"), _positive_env("DS4_API_ATTACHMENT_CHUNK_TOKENS", DEFAULT_CHUNK_TOKENS))
    chunks = _chunks_for_attachments(attachments, chunk_tokens=chunk_tokens)
    budget = _attachment_context_budget(body, profile, max_output_tokens=max_output_tokens, thinking_budget_tokens=thinking_budget_tokens)
    selected = _select_chunks(chunks, budget_tokens=budget, query=_last_user_text(messages))
    manifest = _manifest(attachments, chunks, selected, budget_tokens=budget, chunk_tokens=chunk_tokens)
    if manifest["omitted_chunk_count"] > 0 and _truthy(_setting(body, "ds4_attachment_require_all")):
        raise ValueError(
            f"attachments need about {manifest['estimated_tokens']} prompt tokens, but budget is {budget}; "
            "raise the model context, lower requested output/thinking tokens, or unset ds4_attachment_require_all"
        )
    message = _attachment_message(manifest, selected)
    if not message:
        return messages, manifest
    return _insert_before_final_user(messages, message), manifest


def _request_attachments(body: dict[str, Any]) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    extra_body = body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    for container in (body, extra_body, metadata):
        for key in ("attachments", "files", "input_attachments"):
            raw = container.get(key) if isinstance(container, dict) else None
            if isinstance(raw, list):
                attachments.extend(item for item in raw if isinstance(item, dict))
    return [_normalized_attachment(item, index) for index, item in enumerate(attachments)]


def _normalized_attachment(item: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(item.get("name") or item.get("filename") or item.get("path") or item.get("id") or f"attachment-{index + 1}")
    mime_type = str(item.get("mime_type") or item.get("media_type") or item.get("content_type") or item.get("type") or "text/plain")
    text = _attachment_text(item)
    content_bytes = text.encode("utf-8")
    return {
        "name": name,
        "mime_type": mime_type,
        "content": text,
        "byte_count": len(content_bytes),
        "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
    }


def _attachment_text(item: dict[str, Any]) -> str:
    for key in ("content", "text", "data"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    value = item.get("content_base64")
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True).decode("utf-8", "replace")
        except Exception as exc:
            raise ValueError("attachment content_base64 must decode as UTF-8 text") from exc
    return ""


def _chunks_for_attachments(attachments: list[dict[str, Any]], *, chunk_tokens: int) -> list[AttachmentChunk]:
    chunks: list[AttachmentChunk] = []
    max_bytes = max(1, int(chunk_tokens)) * ROUGH_BYTES_PER_TOKEN
    for attachment_index, attachment in enumerate(attachments):
        text = str(attachment.get("content") or "")
        for chunk_index, chunk_text in enumerate(_split_text_by_bytes(text, max_bytes=max_bytes)):
            encoded = chunk_text.encode("utf-8")
            chunks.append(
                AttachmentChunk(
                    attachment_index=attachment_index,
                    chunk_index=chunk_index,
                    name=str(attachment["name"]),
                    mime_type=str(attachment["mime_type"]),
                    text=chunk_text,
                    byte_count=len(encoded),
                    estimated_tokens=_rough_tokens(chunk_text),
                    content_sha256=hashlib.sha256(encoded).hexdigest(),
                )
            )
    return chunks


def _split_text_by_bytes(text: str, *, max_bytes: int) -> list[str]:
    if len(text.encode("utf-8")) <= max_bytes:
        return [text] if text else []
    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for line in text.splitlines(keepends=True):
        line_bytes = len(line.encode("utf-8"))
        if line_bytes > max_bytes:
            if current:
                chunks.append("".join(current))
                current = []
                current_bytes = 0
            chunks.extend(_split_long_line(line, max_bytes=max_bytes))
            continue
        if current and (current_bytes + line_bytes) > max_bytes:
            chunks.append("".join(current))
            current = []
            current_bytes = 0
        current.append(line)
        current_bytes += line_bytes
    if current:
        chunks.append("".join(current))
    return chunks


def _split_long_line(line: str, *, max_bytes: int) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for char in line:
        char_bytes = len(char.encode("utf-8"))
        if current and (current_bytes + char_bytes) > max_bytes:
            out.append("".join(current))
            current = []
            current_bytes = 0
        current.append(char)
        current_bytes += char_bytes
    if current:
        out.append("".join(current))
    return out


def _attachment_context_budget(body: dict[str, Any], profile: ModelProfile, *, max_output_tokens: int, thinking_budget_tokens: int) -> int:
    override = _setting(body, "ds4_attachment_context_budget_tokens")
    if override is not None:
        return max(1, int(override))
    max_model_len = _profile_max_model_len(profile)
    reserve = _positive_env("DS4_API_ATTACHMENT_CONTEXT_RESERVE_TOKENS", DEFAULT_CONTEXT_RESERVE_TOKENS)
    reserve += max(0, int(max_output_tokens)) + max(0, int(thinking_budget_tokens))
    return max(1, max_model_len - reserve)


def _profile_max_model_len(profile: ModelProfile) -> int:
    for container in (profile.performance, profile.routing):
        value = container.get("max_model_len") if isinstance(container, dict) else None
        if value is not None:
            return max(1, int(value))
    return 32768


def _select_chunks(chunks: list[AttachmentChunk], *, budget_tokens: int, query: str) -> list[AttachmentChunk]:
    if sum(chunk.estimated_tokens for chunk in chunks) <= budget_tokens:
        return chunks
    scored = [(_chunk_score(chunk, query), index, chunk) for index, chunk in enumerate(chunks)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[tuple[int, AttachmentChunk]] = []
    used = 0
    for _score, index, chunk in scored:
        if selected and (used + chunk.estimated_tokens) > budget_tokens:
            continue
        if chunk.estimated_tokens > budget_tokens and not selected:
            selected.append((index, chunk))
            break
        selected.append((index, chunk))
        used += chunk.estimated_tokens
    selected.sort(key=lambda item: item[0])
    return [chunk for _index, chunk in selected]


def _chunk_score(chunk: AttachmentChunk, query: str) -> int:
    terms = set(_query_terms(query))
    if not terms:
        return 0
    text = chunk.text.lower()
    return sum(1 for term in terms if term in text)


def _query_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-zA-Z0-9_]{3,}", query.lower()) if term not in _STOP_TERMS]


_STOP_TERMS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "what", "when", "where", "which", "should", "would",
}


def _manifest(attachments: list[dict[str, Any]], chunks: list[AttachmentChunk], selected: list[AttachmentChunk], *, budget_tokens: int, chunk_tokens: int) -> dict[str, Any]:
    selected_keys = {(chunk.attachment_index, chunk.chunk_index) for chunk in selected}
    files = []
    for index, attachment in enumerate(attachments):
        file_chunks = [chunk for chunk in chunks if chunk.attachment_index == index]
        included = [chunk for chunk in file_chunks if (chunk.attachment_index, chunk.chunk_index) in selected_keys]
        files.append(
            {
                "name": attachment["name"],
                "mime_type": attachment["mime_type"],
                "bytes": attachment["byte_count"],
                "content_sha256": attachment["content_sha256"],
                "chunk_count": len(file_chunks),
                "included_chunk_count": len(included),
                "estimated_tokens": sum(chunk.estimated_tokens for chunk in file_chunks),
            }
        )
    return {
        "format": ATTACHMENT_CONTEXT_FORMAT,
        "attachment_count": len(attachments),
        "chunk_count": len(chunks),
        "included_chunk_count": len(selected),
        "omitted_chunk_count": max(0, len(chunks) - len(selected)),
        "bytes": sum(int(item["byte_count"]) for item in attachments),
        "estimated_tokens": sum(chunk.estimated_tokens for chunk in chunks),
        "included_estimated_tokens": sum(chunk.estimated_tokens for chunk in selected),
        "budget_tokens": int(budget_tokens),
        "chunk_target_tokens": int(chunk_tokens),
        "selection": "all" if len(selected) == len(chunks) else "query_relevant",
        "files": files,
    }


def _attachment_message(manifest: dict[str, Any], selected: list[AttachmentChunk]) -> dict[str, str]:
    if not selected:
        return {}
    lines = [
        "Attached file context follows. Use these file contents as source material for the next user request.",
        f"Attachment manifest: {manifest['attachment_count']} file(s), {manifest['bytes']} bytes, about {manifest['estimated_tokens']} tokens, {manifest['included_chunk_count']}/{manifest['chunk_count']} chunk(s) included.",
    ]
    if manifest["omitted_chunk_count"]:
        lines.append(f"Only query-relevant chunks fit this context window; {manifest['omitted_chunk_count']} chunk(s) are omitted.")
    for chunk in selected:
        lines.append(f"\n<ds4_attachment name=\"{_xml_escape(chunk.name)}\" chunk=\"{chunk.chunk_index + 1}\" sha256=\"{chunk.content_sha256}\">")
        lines.append(chunk.text)
        lines.append("</ds4_attachment>")
    return {"role": "user", "content": "\n".join(lines)}


def _insert_before_final_user(messages: list[dict[str, Any]], message: dict[str, str]) -> list[dict[str, Any]]:
    out = list(messages)
    for index in range(len(out) - 1, -1, -1):
        if out[index].get("role") == "user":
            out.insert(index, message)
            return out
    out.append(message)
    return out


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _setting(body: dict[str, Any], key: str) -> Any:
    extra_body = body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    for container in (body, extra_body, metadata):
        if key in container:
            return container[key]
    return None


def _positive_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except ValueError:
        return default


def _positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return max(1, int(value))


def _rough_tokens(text: str) -> int:
    return max(1, len(text.encode("utf-8")) // ROUGH_BYTES_PER_TOKEN)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("\"", "&quot;").replace("<", "&lt;").replace(">", "&gt;")
