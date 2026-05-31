#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib import error, parse, request
import uuid


TERMINAL = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}


def main() -> int:
    args = _parse_args()
    batch_id = args.batch_id or f"bench-{uuid.uuid4().hex[:16]}"
    profile_id = _profile_id_for_model(args.base_url, args.model)
    started_submit = time.time()
    _post(
        args.base_url,
        "/ds4/queue/submit",
        {
            "batch_id": batch_id,
            "priority": args.priority,
            "requests": [_request_json(args, batch_id, profile_id, idx) for idx in range(args.batch_size)],
        },
    )
    submit_s = time.time() - started_submit
    started_run = time.time()
    newest_event_id = 0
    while True:
        if args.drive_worker:
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
    aggregate_tok_s = tokens / run_s if run_s > 0 else 0.0
    perf = _performance_score(
        aggregate_tok_s=aggregate_tok_s,
        concurrency=args.concurrency,
        pipeline_stages=args.pipeline_stages,
        equivalent_sparks=args.equivalent_sparks,
        reference_tok_s=args.reference_tok_s,
    )
    target_tokens = args.batch_size * args.output_tokens
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
        "worker_mode": "api_sync_work" if args.drive_worker else "external_worker",
        "ignore_eos": bool(args.ignore_eos),
        "min_tokens": args.output_tokens if args.ignore_eos else 0,
        "submit_s": round(submit_s, 6),
        "run_s": round(run_s, 6),
        "completed": len(completed),
        "failed": failed,
        "completion_tokens": tokens,
        "completion_tokens_target": target_tokens,
        "completion_tokens_target_ratio": round(tokens / target_tokens, 6) if target_tokens > 0 else 0.0,
        "aggregate_completion_tok_s": round(aggregate_tok_s, 6),
        "performance_target": perf,
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
    parser.add_argument("--input-tokens", type=int, default=512)
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument("--timeout-s", type=int, default=1800)
    parser.add_argument("--poll-s", type=float, default=0.02)
    parser.add_argument("--drive-worker", action="store_true", help="Also call the synchronous /ds4/queue/work endpoint. Production benchmarks should leave this off and run ds4_pipeline_queue_worker.sh separately.")
    parser.add_argument("--ignore-eos", dest="ignore_eos", action="store_true", default=True, help="Force benchmark decode to the requested output token count by passing ignore_eos/min_tokens through to vLLM.")
    parser.add_argument("--allow-eos", dest="ignore_eos", action="store_false", help="Let EOS stop generation early. This is useful for behavior tests, not throughput targets.")
    parser.add_argument("--pipeline-stages", type=int, default=8)
    parser.add_argument("--equivalent-sparks", type=int, default=2)
    parser.add_argument("--reference-tok-s", type=float, default=144.6, help="Known-good two-Spark-equivalent DSV4 c16 aggregate target.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--job-class", default="analysis")
    parser.add_argument("--priority", type=int, default=None)
    return parser.parse_args()


def _request_json(args: argparse.Namespace, batch_id: str, profile_id: str, idx: int) -> dict[str, Any]:
    return {
        "format": "ds4-inference-request-v1",
        "request_id": f"{batch_id}-{idx:06d}",
        "capability": None,
        "chat": False,
        "immediate": False,
        "job_class": args.job_class,
        "max_output_tokens": args.output_tokens,
        "thinking_budget_tokens": 0,
        "temperature": args.temperature,
        "input": {
            "prompt": _prompt(args.input_tokens, idx),
            "openai": _openai_benchmark_fields(args),
        },
        "output_contract": {"format": "text"},
        "model_pin": {"profile_id": profile_id},
    }


def _openai_benchmark_fields(args: argparse.Namespace) -> dict[str, Any]:
    if not args.ignore_eos:
        return {}
    return {
        "ignore_eos": True,
        "min_tokens": args.output_tokens,
    }


def _performance_score(
    *,
    aggregate_tok_s: float,
    concurrency: int,
    pipeline_stages: int,
    equivalent_sparks: int,
    reference_tok_s: float,
) -> dict[str, Any]:
    concurrency = max(1, int(concurrency))
    pipeline_stages = max(1, int(pipeline_stages))
    equivalent_sparks = max(1, int(equivalent_sparks))
    bubble_factor = (concurrency + pipeline_stages - 1) / concurrency
    stage_groups = pipeline_stages / equivalent_sparks
    corrected = aggregate_tok_s * bubble_factor
    equivalent = corrected / stage_groups if stage_groups > 0 else 0.0
    reference_needed = reference_tok_s * stage_groups / bubble_factor if bubble_factor > 0 else 0.0
    return {
        "pipeline_stages": pipeline_stages,
        "equivalent_sparks": equivalent_sparks,
        "reference_tok_s": round(reference_tok_s, 6),
        "pp_bubble_efficiency": round(1 / bubble_factor, 6) if bubble_factor > 0 else 0.0,
        "bubble_corrected_aggregate_tok_s": round(corrected, 6),
        "two_spark_equivalent_tok_s": round(equivalent, 6),
        "reference_ratio": round(equivalent / reference_tok_s, 6) if reference_tok_s > 0 else 0.0,
        "aggregate_tok_s_needed_for_reference": round(reference_needed, 6),
        "aggregate_tok_s_needed_for_80pct_reference": round(reference_needed * 0.8, 6),
    }


def _profile_id_for_model(base_url: str, model: str) -> str:
    models = _get(base_url, "/v1/models", {})
    for item in models.get("data", []):
        if isinstance(item, dict) and item.get("id") == model:
            profile_id = item.get("ds4_profile_id")
            if isinstance(profile_id, str) and profile_id:
                return profile_id
    return model


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
