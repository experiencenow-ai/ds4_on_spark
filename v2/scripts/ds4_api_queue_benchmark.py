#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from typing import Any
from urllib import error, parse, request
import uuid


TERMINAL = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}


def main() -> int:
    args = _parse_args()
    batch_id = args.batch_id or f"bench-{uuid.uuid4().hex[:16]}"
    prompts = [_prompt(args.input_tokens, idx) for idx in range(args.batch_size)]
    started_submit = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.submit_concurrency)) as pool:
        futures = [pool.submit(_submit_one, args, batch_id, idx, prompt) for idx, prompt in enumerate(prompts)]
        for future in as_completed(futures):
            future.result()
    submit_s = time.time() - started_submit
    started_run = time.time()
    newest_event_id = 0
    while True:
        _post(args.base_url, "/ds4/queue/work", {"batch_id": batch_id, "limit": args.limit, "concurrency": args.concurrency, "timeout_s": args.timeout_s})
        status = _get(args.base_url, "/ds4/queue/status", {"batch_id": batch_id})
        if str(status.get("state")) in TERMINAL:
            break
        poll = _get(args.base_url, "/ds4/queue/poll", {"after_event_id": newest_event_id, "limit": 100})
        newest_event_id = int(poll.get("newest_event_id") or newest_event_id)
        time.sleep(args.poll_s)
        if time.time() - started_run > args.timeout_s:
            raise TimeoutError(f"batch {batch_id} did not finish in {args.timeout_s}s")
    run_s = time.time() - started_run
    collected = _get(args.base_url, "/ds4/queue/collect", {"batch_id": batch_id})
    results = collected.get("results", [])
    completed = [row for row in results if isinstance(row, dict) and (row.get("result") or {}).get("status") == "completed"]
    failed = len(results) - len(completed)
    tokens = sum(_completion_tokens(row.get("result") or {}) for row in completed)
    summary = {
        "format": "ds4-api-queue-benchmark-v1",
        "base_url": args.base_url,
        "batch_id": batch_id,
        "model": args.model,
        "batch_size": args.batch_size,
        "concurrency": args.concurrency,
        "limit": args.limit,
        "input_tokens_target": args.input_tokens,
        "output_tokens_target": args.output_tokens,
        "submit_s": round(submit_s, 6),
        "run_s": round(run_s, 6),
        "completed": len(completed),
        "failed": failed,
        "completion_tokens": tokens,
        "aggregate_completion_tok_s": round(tokens / run_s, 6) if run_s > 0 else 0.0,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if failed == 0 else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the DS4 deployment path through the spark0 coordinator API.")
    parser.add_argument("--base-url", default="http://10.20.0.10:8700")
    parser.add_argument("--model", default="dsv4")
    parser.add_argument("--batch-id")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--limit", type=int, default=32)
    parser.add_argument("--submit-concurrency", type=int, default=32)
    parser.add_argument("--input-tokens", type=int, default=512)
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument("--timeout-s", type=int, default=1800)
    parser.add_argument("--poll-s", type=float, default=0.02)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--job-class", default="analysis")
    return parser.parse_args()


def _submit_one(args: argparse.Namespace, batch_id: str, idx: int, prompt: str) -> dict[str, Any]:
    body = {
        "model": args.model,
        "prompt": prompt,
        "max_tokens": args.output_tokens,
        "temperature": args.temperature,
        "ds4_async": True,
        "batch_id": batch_id,
        "request_id": f"{batch_id}-{idx:06d}",
        "ds4_job_class": args.job_class,
    }
    return _post(args.base_url, "/v1/completions", body)


def _post(base_url: str, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(base_url.rstrip("/") + endpoint, data=data, headers={"content-type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"POST {endpoint} HTTP {exc.code}: {detail}") from exc


def _get(base_url: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    query = parse.urlencode({key: value for key, value in params.items() if value is not None})
    with request.urlopen(base_url.rstrip("/") + endpoint + ("?" + query if query else ""), timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _prompt(tokens: int, idx: int) -> str:
    filler = " ".join("benchmark" for _ in range(max(1, tokens)))
    return f"Request {idx}. Continue with useful, non-repetitive details until the token budget is used. {filler}"


def _completion_tokens(result: dict[str, Any]) -> int:
    usage = result.get("usage")
    if isinstance(usage, dict):
        value = usage.get("completion_tokens")
        if isinstance(value, (int, float)):
            return max(0, int(value))
    text = json.dumps(result.get("output", {}), sort_keys=True)
    return max(0, len(text.encode("utf-8")) // 4)


if __name__ == "__main__":
    raise SystemExit(main())
