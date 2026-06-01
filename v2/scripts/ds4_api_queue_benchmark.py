#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time
from typing import Any
from urllib import error, parse, request
import uuid


TERMINAL = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}


def main() -> int:
    args = _parse_args()
    batch_id = args.batch_id or f"bench-{uuid.uuid4().hex[:16]}"
    cache_body = _cache_body(args)
    shared_prefix = _shared_prefix(args.shared_prefix_tokens)
    prompts = [_prompt(args, idx, shared_prefix) for idx in range(args.batch_size)]
    if args.submission_mode == "prompt-array":
        return _run_prompt_array_benchmark(args, batch_id, prompts, cache_body)
    started_submit = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.submit_concurrency)) as pool:
        futures = [pool.submit(_submit_one, args, batch_id, idx, prompt, cache_body) for idx, prompt in enumerate(prompts)]
        for future in as_completed(futures):
            future.result()
    submit_s = time.time() - started_submit
    started_run = time.time()
    newest_event_id = 0
    while True:
        if args.drive_work:
            _post(args.base_url, "/ds4/queue/work", {"batch_id": batch_id, "limit": args.limit, "concurrency": args.concurrency, "timeout_s": args.timeout_s}, timeout_s=args.timeout_s)
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
        "shared_prefix_tokens_target": args.shared_prefix_tokens,
        "suffix_tokens_target": _suffix_tokens(args),
        "output_tokens_target": args.output_tokens,
        "cache_mode": _cache_mode(args),
        "external_kv": cache_body.get("external_kv"),
        "kv_cache": cache_body.get("kv_cache"),
        "submit_s": round(submit_s, 6),
        "run_s": round(run_s, 6),
        "completed": len(completed),
        "failed": failed,
        "completion_tokens": tokens,
        "aggregate_completion_tok_s": round(tokens / run_s, 6) if run_s > 0 else 0.0,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if failed == 0 else 2


def _run_prompt_array_benchmark(args: argparse.Namespace, batch_id: str, prompts: list[str], cache_body: dict[str, Any]) -> int:
    body = {
        "model": args.model,
        "prompt": prompts,
        "max_tokens": args.output_tokens,
        "temperature": args.temperature,
        "batch_id": batch_id,
        "request_id": batch_id,
        "ds4_job_class": args.job_class,
    }
    body.update(cache_body)
    started = time.time()
    response = _post(args.base_url, "/v1/completions", body, timeout_s=args.timeout_s)
    run_s = time.time() - started
    choices = response.get("choices") if isinstance(response, dict) else []
    completed = len(choices) if isinstance(choices, list) else 0
    failed = max(0, args.batch_size - completed)
    usage = response.get("usage") if isinstance(response, dict) else {}
    tokens = int(usage.get("completion_tokens") or 0) if isinstance(usage, dict) else 0
    if tokens <= 0 and isinstance(choices, list):
        tokens = sum(max(0, len(str(choice.get("text", "")).encode("utf-8")) // 4) for choice in choices if isinstance(choice, dict))
    summary = {
        "format": "ds4-api-queue-benchmark-v1",
        "base_url": args.base_url,
        "batch_id": batch_id,
        "model": args.model,
        "submission_mode": "prompt-array",
        "batch_size": args.batch_size,
        "concurrency": args.concurrency,
        "limit": args.limit,
        "input_tokens_target": args.input_tokens,
        "shared_prefix_tokens_target": args.shared_prefix_tokens,
        "suffix_tokens_target": _suffix_tokens(args),
        "output_tokens_target": args.output_tokens,
        "cache_mode": _cache_mode(args),
        "external_kv": cache_body.get("external_kv"),
        "kv_cache": cache_body.get("kv_cache"),
        "submit_s": 0.0,
        "run_s": round(run_s, 6),
        "completed": completed,
        "failed": failed,
        "completion_tokens": tokens,
        "aggregate_completion_tok_s": round(tokens / run_s, 6) if run_s > 0 else 0.0,
        "api_response_id": response.get("id") if isinstance(response, dict) else None,
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
    parser.add_argument("--submission-mode", choices=("prompt-array", "async-requests"), default="prompt-array")
    parser.add_argument("--drive-work", action="store_true", help="Legacy mode: call /ds4/queue/work while polling async requests. Production benchmarks should leave this off.")
    parser.add_argument("--input-tokens", type=int, default=512)
    parser.add_argument("--shared-prefix-tokens", type=int, default=0, help="Approximate token count for a token-identical prefix placed before each unique suffix.")
    parser.add_argument("--suffix-tokens", type=int, help="Approximate token count for the per-request suffix when --shared-prefix-tokens is used. Defaults to input_tokens - shared_prefix_tokens.")
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument("--timeout-s", type=int, default=1800)
    parser.add_argument("--poll-s", type=float, default=0.02)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--job-class", default="analysis")
    parser.add_argument("--external-kv-key", help="Attach DS4 external_kv shorthand to each API request.")
    parser.add_argument("--external-kv-namespace", default="bench")
    parser.add_argument("--external-kv-service-id")
    parser.add_argument("--external-kv-backend", default="auto")
    parser.add_argument("--external-kv-mode", default="prefer", choices=("prefer", "require", "skip"))
    parser.add_argument("--external-kv-miss-policy", default="compute", choices=("compute", "fail", "compute_and_store"))
    parser.add_argument("--external-kv-route-affinity", default="required", choices=("none", "preferred", "required"))
    parser.add_argument("--external-kv-prefix-hash")
    parser.add_argument("--kv-cache-directive-json", help="Attach an exact input.kv_cache directive JSON object to each API request.")
    parser.add_argument("--kv-cache-directive-file", help="Read an exact input.kv_cache directive JSON object from this file.")
    return parser.parse_args()


def _submit_one(args: argparse.Namespace, batch_id: str, idx: int, prompt: str, cache_body: dict[str, Any]) -> dict[str, Any]:
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
    body.update(cache_body)
    return _post(args.base_url, "/v1/completions", body)


def _cache_body(args: argparse.Namespace) -> dict[str, Any]:
    directive = _kv_cache_directive(args)
    has_external = bool(args.external_kv_key)
    if directive is not None and has_external:
        raise ValueError("provide only one of --kv-cache-directive-* or --external-kv-key")
    if directive is not None:
        return {"kv_cache": directive}
    if not has_external:
        return {}
    external_kv: dict[str, Any] = {
        "namespace": args.external_kv_namespace,
        "kv_key": args.external_kv_key,
        "backend": args.external_kv_backend,
        "mode": args.external_kv_mode,
        "miss_policy": args.external_kv_miss_policy,
        "route_affinity": args.external_kv_route_affinity,
    }
    if args.external_kv_service_id:
        external_kv["service_id"] = args.external_kv_service_id
    if args.external_kv_prefix_hash:
        external_kv["prefix_hash"] = args.external_kv_prefix_hash
    return {"external_kv": external_kv}


def _kv_cache_directive(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.kv_cache_directive_json and args.kv_cache_directive_file:
        raise ValueError("provide only one of --kv-cache-directive-json or --kv-cache-directive-file")
    if args.kv_cache_directive_json:
        data = json.loads(args.kv_cache_directive_json)
    elif args.kv_cache_directive_file:
        data = json.loads(Path(args.kv_cache_directive_file).read_text(encoding="utf-8"))
    else:
        return None
    if not isinstance(data, dict):
        raise ValueError("KV cache directive must be a JSON object")
    return data


def _post(base_url: str, endpoint: str, body: dict[str, Any], *, timeout_s: int = 60) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(base_url.rstrip("/") + endpoint, data=data, headers={"content-type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=max(1, int(timeout_s))) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"POST {endpoint} HTTP {exc.code}: {detail}") from exc


def _get(base_url: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    query = parse.urlencode({key: value for key, value in params.items() if value is not None})
    with request.urlopen(base_url.rstrip("/") + endpoint + ("?" + query if query else ""), timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _shared_prefix(tokens: int) -> str:
    if tokens <= 0:
        return ""
    return " ".join("shared-prefix-benchmark" for _ in range(tokens))


def _suffix_tokens(args: argparse.Namespace) -> int:
    if args.shared_prefix_tokens <= 0:
        return max(1, args.input_tokens)
    if args.suffix_tokens is not None:
        return max(1, int(args.suffix_tokens))
    return max(1, int(args.input_tokens) - int(args.shared_prefix_tokens))


def _prompt(args: argparse.Namespace, idx: int, shared_prefix: str) -> str:
    if shared_prefix:
        suffix = " ".join("request-specific-detail" for _ in range(_suffix_tokens(args)))
        return f"{shared_prefix}\n\nRequest {idx}. Continue with useful, non-repetitive details until the token budget is used. {suffix}"
    filler = " ".join("benchmark" for _ in range(max(1, args.input_tokens)))
    return f"Request {idx}. Continue with useful, non-repetitive details until the token budget is used. {filler}"


def _cache_mode(args: argparse.Namespace) -> str:
    if args.kv_cache_directive_json or args.kv_cache_directive_file:
        return "kv_cache_directive"
    if args.external_kv_key:
        return "external_kv"
    if args.shared_prefix_tokens > 0:
        return "vllm_prefix_cache_candidate"
    return "cold_unique_prefix"


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
