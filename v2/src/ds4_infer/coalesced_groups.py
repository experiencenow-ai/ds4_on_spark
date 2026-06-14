from __future__ import annotations

import json
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def plan_compatible_payload_groups(
    items: list[T],
    *,
    payload_for_chunk: Callable[[list[T]], dict[str, Any] | None],
    chunk_items: Callable[[list[T]], list[list[T]]],
    minimum: int,
) -> tuple[list[list[T]], list[tuple[list[T], dict[str, Any]]]] | None:
    groups: dict[str, list[T]] = {}
    for item in items:
        payload = payload_for_chunk([item])
        if payload is None:
            return None
        comparable = dict(payload)
        comparable.pop("prompt", None)
        key = json.dumps(comparable, sort_keys=True, separators=(",", ":"), default=str)
        groups.setdefault(key, []).append(item)
    chunks: list[list[T]] = []
    payloads: list[tuple[list[T], dict[str, Any]]] = []
    for group in groups.values():
        if len(group) < minimum:
            return None
        for chunk in chunk_items(group):
            payload = payload_for_chunk(chunk)
            if payload is None:
                return None
            chunks.append(chunk)
            payloads.append((chunk, payload))
    return chunks, payloads
