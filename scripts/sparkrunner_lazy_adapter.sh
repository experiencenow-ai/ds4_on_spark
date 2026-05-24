#!/usr/bin/env bash
# Centaur DGX SparkRunner adapter for the ds4_on_spark lazy vLLM proxy.
#
# Contract:
#   sparkrunner_lazy_adapter.sh --input requests.jsonl --output responses.jsonl --model MODEL
#
# The adapter preserves each request custom_id and writes one JSON object per
# line. It intentionally does not verify or promote candidates; Centaur owns
# deterministic verification after this proposal step.
set -euo pipefail

python3 - "$@" <<'PY'
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Centaur JSONL to lazy vLLM chat adapter")
    parser.add_argument("--input", "--input-jsonl", "--requests", "--requests-jsonl", dest="input", required=True)
    parser.add_argument("--output", "--output-jsonl", "--responses", "--responses-jsonl", dest="output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("SPARKRUNNER_LAZY_BASE_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--workers", type=_positive_int, default=int(os.environ.get("SPARKRUNNER_LAZY_WORKERS", "8")))
    parser.add_argument("--timeout-s", type=float, default=float(os.environ.get("SPARKRUNNER_LAZY_TIMEOUT_S", "600")))
    parser.add_argument("--max-tokens-cap", type=int, default=int(os.environ.get("SPARKRUNNER_LAZY_MAX_TOKENS_CAP", "0")))
    return parser.parse_args()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if line.strip():
                record = json.loads(line)
                record["_line_number"] = line_number
                records.append(record)
    return records


def _messages(record: dict[str, Any]) -> list[dict[str, str]]:
    messages = record.get("messages")
    if isinstance(messages, list) and messages:
        cleaned: list[dict[str, str]] = []
        for message in messages:
            if isinstance(message, dict):
                cleaned.append({
                    "role": str(message.get("role", "user")),
                    "content": str(message.get("content", "")),
                })
        if cleaned:
            return cleaned
    return [{"role": "user", "content": str(record.get("prompt", ""))}]


def _int_from(record: dict[str, Any], keys: tuple[str, ...], default: int) -> int:
    for key in keys:
        value = record.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return default


def _float_from(record: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(record.get(key, default))
    except (TypeError, ValueError):
        return default


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/chat/completions"


def _choice_texts(response: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for choice in response.get("choices", []):
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        text = message.get("content")
        if text is None:
            text = message.get("reasoning_content")
        texts.append("" if text is None else str(text))
    return texts or [""]


def _call_one(index: int, record: dict[str, Any], args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    custom_id = str(record.get("custom_id") or record.get("request_id") or f"request-{index}")
    max_tokens = _int_from(record, ("max_tokens", "max_completion_tokens"), 1024)
    if args.max_tokens_cap > 0:
        max_tokens = min(max_tokens, args.max_tokens_cap)
    payload: dict[str, Any] = {
        "model": args.model,
        "messages": _messages(record),
        "max_tokens": max_tokens,
        "temperature": _float_from(record, "temperature", 0.2),
    }
    n = _int_from(record, ("n", "num_candidates"), 1)
    if n > 1:
        payload["n"] = n
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _endpoint(args.base_url),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=args.timeout_s) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{custom_id}: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"{custom_id}: {type(exc).__name__}: {exc}") from exc
    data = json.loads(raw)
    texts = _choice_texts(data)
    output = {
        "custom_id": custom_id,
        "model": args.model,
        "text": texts[0],
        "candidates": [{"text": text} for text in texts],
        "usage": data.get("usage", {}),
        "latency_ms": int((time.time() - started) * 1000),
    }
    return index, output


def main() -> int:
    args = _parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    records = _read_jsonl(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any] | None] = [None] * len(records)
    workers = min(args.workers, max(1, len(records)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_call_one, index, record, args) for index, record in enumerate(records)]
        for future in concurrent.futures.as_completed(futures):
            index, output = future.result()
            results[index] = output
    with output_path.open("w", encoding="utf-8") as output:
        for result in results:
            if result is not None:
                output.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
