from __future__ import annotations

import os
from typing import Any


def coalesced_completion_token_budget() -> int:
    raw = os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET")
    if raw is None or raw == "":
        raw = os.environ.get("DS4_PIPELINE_COHORT_TOKEN_BUDGET", "262144")
    return max(0, int(raw or "0"))


def prompt_token_estimate(prompt: str) -> int:
    text = str(prompt)
    words = len(text.split())
    bytes_estimate = (len(text.encode("utf-8")) + 1) // 2
    return max(1, words, bytes_estimate)


def coalesced_failure_should_bisect(error_text: str) -> bool:
    lowered = str(error_text).lower()
    markers = (
        "http 400",
        "http 413",
        "out of memory",
        "cuda out of memory",
        "kv cache",
        "context length",
        "maximum context",
        "too many tokens",
        "exceeds",
    )
    return any(marker in lowered for marker in markers)


def mark_coalesced_split(out: dict[str, dict], *, original_batch_size: int) -> None:
    for result in out.values():
        transport: dict[str, Any] = result.setdefault("transport", {})
        transport["coalesced_completion_split_retry"] = True
        transport["original_coalesced_batch_size"] = original_batch_size
