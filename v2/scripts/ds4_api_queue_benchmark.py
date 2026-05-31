#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request
import uuid


TERMINAL = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}


def main() -> int:
    args = _parse_args()
    batch_id = args.batch_id or f"bench-{uuid.uuid4().hex[:16]}"
    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    if args.requests_jsonl:
        requests_payload = _load_requests_jsonl(Path(args.requests_jsonl))
        if not args.preserve_request_ids:
            requests_payload = _remap_request_ids(requests_payload, batch_id)
    else:
        profile_id = _profile_id_for_model(args.base_url, args.model)
        requests_payload = [_request_json(args, batch_id, profile_id, idx) for idx in range(args.batch_size)]
    if out_dir is not None:
        _write_requests_jsonl(out_dir / "requests.jsonl", requests_payload)
        _write_json(out_dir / "manifest.json", _manifest_json(args, batch_id, requests_payload))
    if args.write_only:
        summary = {"format": "ds4-api-queue-benchmark-plan-v1", "batch_id": batch_id, "request_count": len(requests_payload), "out_dir": str(out_dir) if out_dir else None}
        print(json.dumps(summary, sort_keys=True))
        return 0
    started_submit = time.time()
    submit_response = _post(
        args.base_url,
        "/ds4/queue/submit",
        {
            "batch_id": batch_id,
            "priority": args.priority,
            "requests": requests_payload,
        },
    )
    submit_s = time.time() - started_submit
    if out_dir is not None:
        _write_json(out_dir / "submit.json", submit_response)
    started_run = time.time()
    newest_event_id = 0
    status: dict[str, Any] = {}
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
    if out_dir is not None:
        _write_json(out_dir / "status.json", status)
    collected = _get(args.base_url, "/ds4/queue/collect", {"batch_id": batch_id})
    if out_dir is not None:
        _write_json(out_dir / "collect.json", collected)
    results = collected.get("results", [])
    completed = [row for row in results if isinstance(row, dict) and (row.get("result") or {}).get("status") == "completed"]
    failed = len(results) - len(completed)
    tokens = sum(_completion_tokens(row.get("result") or {}) for row in completed)
    timings = _result_timings(results, run_s=run_s)
    aggregate_tok_s = tokens / run_s if run_s > 0 else 0.0
    transport_aggregate_tok_s = tokens / timings["transport_duration_s_max"] if timings["transport_duration_s_max"] > 0 else 0.0
    perf = _performance_score(
        aggregate_tok_s=aggregate_tok_s,
        concurrency=args.concurrency,
        pipeline_stages=args.pipeline_stages,
        equivalent_sparks=args.equivalent_sparks,
        reference_tok_s=args.reference_tok_s,
    )
    transport_perf = _performance_score(
        aggregate_tok_s=transport_aggregate_tok_s,
        concurrency=args.concurrency,
        pipeline_stages=args.pipeline_stages,
        equivalent_sparks=args.equivalent_sparks,
        reference_tok_s=args.reference_tok_s,
    )
    target_tokens = _target_completion_tokens(requests_payload)
    output_tokens_target = _uniform_request_int(requests_payload, "max_output_tokens", args.output_tokens)
    perf_valid = int(timings["attempt_count_max"]) <= 1
    summary = {
        "format": "ds4-api-queue-benchmark-v1",
        "base_url": args.base_url,
        "batch_id": batch_id,
        "model": args.model,
        "batch_size": len(requests_payload),
        "concurrency": args.concurrency,
        "limit": args.limit,
        "input_tokens_target": args.input_tokens,
        "output_tokens_target": output_tokens_target,
        "worker_mode": "api_sync_work" if args.drive_worker else "external_worker",
        "request_source": str(args.requests_jsonl) if args.requests_jsonl else "generated",
        "preserved_request_ids": bool(args.preserve_request_ids),
        "out_dir": str(out_dir) if out_dir else None,
        "ignore_eos": bool(args.ignore_eos),
        "min_tokens": output_tokens_target if args.ignore_eos else 0,
        "submit_s": round(submit_s, 6),
        "run_s": round(run_s, 6),
        "timings": timings,
        "completed": len(completed),
        "failed": failed,
        "completion_tokens": tokens,
        "completion_tokens_target": target_tokens,
        "completion_tokens_target_ratio": round(tokens / target_tokens, 6) if target_tokens > 0 else 0.0,
        "aggregate_completion_tok_s": round(aggregate_tok_s, 6),
        "transport_aggregate_completion_tok_s": round(transport_aggregate_tok_s, 6),
        "perf_valid": perf_valid,
        "perf_invalid_reason": None if perf_valid else "transport_retries_detected",
        "performance_target": perf,
        "transport_performance_target": transport_perf,
    }
    if out_dir is not None:
        _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if failed == 0 else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the DS4 deployment path through the spark0 coordinator API.")
    parser.add_argument("--base-url", default="http://10.20.0.10:8700")
    parser.add_argument("--model", default="dsv4")
    parser.add_argument("--batch-id")
    parser.add_argument("--out-dir", help="Write the file-driven request set, submit response, collect output, and summary under this directory.")
    parser.add_argument("--requests-jsonl", help="Read request envelopes from this JSONL file instead of generating them in memory.")
    parser.add_argument("--preserve-request-ids", action="store_true", help="Replay request ids exactly as written in --requests-jsonl. By default, JSONL replay remaps request ids to the current batch id so cohorts can be rerun without SQLite request_id collisions.")
    parser.add_argument("--write-only", action="store_true", help="Write requests.jsonl and manifest.json, then exit without submitting.")
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


def _load_requests_jsonl(path: Path) -> list[dict[str, Any]]:
    requests_payload: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        item = json.loads(raw)
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{line_no}: request must be a JSON object")
        requests_payload.append(item)
    if not requests_payload:
        raise ValueError(f"{path}: no requests found")
    return requests_payload


def _remap_request_ids(requests_payload: list[dict[str, Any]], batch_id: str) -> list[dict[str, Any]]:
    remapped: list[dict[str, Any]] = []
    for idx, item in enumerate(requests_payload):
        cloned = dict(item)
        cloned["request_id"] = f"{batch_id}-{idx:06d}"
        remapped.append(cloned)
    return remapped


def _write_requests_jsonl(path: Path, requests_payload: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in requests_payload:
            handle.write(json.dumps(item, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _manifest_json(args: argparse.Namespace, batch_id: str, requests_payload: list[dict[str, Any]]) -> dict[str, Any]:
    output_tokens_target = _uniform_request_int(requests_payload, "max_output_tokens", args.output_tokens)
    return {
        "format": "ds4-api-file-driven-benchmark-manifest-v1",
        "base_url": args.base_url,
        "batch_id": batch_id,
        "model": args.model,
        "request_count": len(requests_payload),
        "input_tokens_target": args.input_tokens,
        "output_tokens_target": output_tokens_target,
        "completion_tokens_target": _target_completion_tokens(requests_payload),
        "concurrency": args.concurrency,
        "limit": args.limit,
        "worker_mode": "api_sync_work" if args.drive_worker else "external_worker",
        "requests_jsonl": "requests.jsonl",
        "preserved_request_ids": bool(args.preserve_request_ids),
        "ignore_eos": bool(args.ignore_eos),
        "min_tokens": output_tokens_target if args.ignore_eos else 0,
    }


def _uniform_request_int(requests_payload: list[dict[str, Any]], key: str, fallback: int) -> int:
    values: set[int] = set()
    for item in requests_payload:
        try:
            values.add(int(item[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return next(iter(values)) if len(values) == 1 else int(fallback)


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


def _result_timings(results: list[Any], *, run_s: float) -> dict[str, Any]:
    created: list[float] = []
    started: list[float] = []
    completed: list[float] = []
    transports: list[float] = []
    attempts: list[int] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        request_status = row.get("request")
        result = row.get("result")
        if isinstance(request_status, dict):
            _append_float(created, request_status.get("created_at"))
            _append_float(started, request_status.get("started_at"))
            _append_float(completed, request_status.get("completed_at"))
            try:
                attempts.append(int(request_status.get("attempt_count") or 0))
            except (TypeError, ValueError):
                pass
        if isinstance(result, dict):
            transport = result.get("transport")
            if isinstance(transport, dict):
                _append_float(transports, transport.get("duration_s"))
    request_window_s = (max(completed) - min(started)) if started and completed else 0.0
    queue_wait_s = (min(started) - min(created)) if started and created else 0.0
    queue_total_s = (max(completed) - min(created)) if completed and created else 0.0
    transport_duration_s_max = max(transports) if transports else 0.0
    return {
        "attempt_count_max": max(attempts) if attempts else 0,
        "attempt_count_min": min(attempts) if attempts else 0,
        "queue_wait_s": round(max(0.0, queue_wait_s), 6),
        "queue_total_s": round(max(0.0, queue_total_s), 6),
        "request_window_s": round(max(0.0, request_window_s), 6),
        "transport_duration_s_max": round(max(0.0, transport_duration_s_max), 6),
        "transport_duration_s_min": round(min(transports), 6) if transports else 0.0,
        "transport_duration_s_avg": round(sum(transports) / len(transports), 6) if transports else 0.0,
        "end_to_end_run_s": round(max(0.0, run_s), 6),
    }


def _append_float(values: list[float], value: Any) -> None:
    try:
        values.append(float(value))
    except (TypeError, ValueError):
        return


def _target_completion_tokens(requests_payload: list[dict[str, Any]]) -> int:
    total = 0
    for item in requests_payload:
        try:
            total += max(0, int(item.get("max_output_tokens", 0)))
        except (TypeError, ValueError):
            continue
    return total


if __name__ == "__main__":
    raise SystemExit(main())
