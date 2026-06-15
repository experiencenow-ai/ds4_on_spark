#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request
import uuid


TERMINAL = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}


def main() -> int:
    args = _parse_args()
    batch_id, out_dir, requests_payload = _prepare_benchmark_requests(args)
    if args.write_only:
        summary = {"format": "ds4-api-queue-benchmark-plan-v1", "batch_id": batch_id, "request_count": len(requests_payload), "out_dir": str(out_dir) if out_dir else None}
        print(json.dumps(summary, sort_keys=True))
        return 0
    vllm_metrics_before = _maybe_read_vllm_metrics(args)
    if out_dir is not None and vllm_metrics_before is not None:
        _write_json(out_dir / "vllm_metrics_before.json", vllm_metrics_before)
    submit_s, run_s, collected = _submit_and_collect(args, batch_id, out_dir, requests_payload)
    vllm_metrics_after = _maybe_read_vllm_metrics(args)
    if out_dir is not None and vllm_metrics_after is not None:
        _write_json(out_dir / "vllm_metrics_after.json", vllm_metrics_after)
    summary = _benchmark_summary(
        args,
        batch_id,
        out_dir,
        requests_payload,
        submit_s,
        run_s,
        collected,
        vllm_metrics_before=vllm_metrics_before,
        vllm_metrics_after=vllm_metrics_after,
    )
    if out_dir is not None:
        _write_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if int(summary["failed"]) == 0 else 2


def _prepare_benchmark_requests(args: argparse.Namespace) -> tuple[str, Path | None, list[dict[str, Any]]]:
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
        requests_payload = _generated_requests(args, batch_id, profile_id)
    if out_dir is not None:
        _write_requests_jsonl(out_dir / "requests.jsonl", requests_payload)
        _write_json(out_dir / "manifest.json", _manifest_json(args, batch_id, requests_payload))
    return batch_id, out_dir, requests_payload


def _submit_and_collect(args: argparse.Namespace, batch_id: str, out_dir: Path | None, requests_payload: list[dict[str, Any]]) -> tuple[float, float, dict[str, Any]]:
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
            _post(args.base_url, "/ds4/queue/work", {"batch_id": batch_id, "limit": args.limit, "concurrency": args.concurrency, "timeout_s": args.timeout_s}, timeout_s=max(60.0, float(args.timeout_s) + 30.0))
        status = _get(args.base_url, "/ds4/queue/status", {"batch_id": batch_id, "refresh": 0})
        if str(status.get("state")) in TERMINAL:
            break
        poll = _get(args.base_url, "/ds4/queue/poll", {"after_event_id": newest_event_id, "limit": 100})
        newest_event_id = int(poll.get("newest_event_id") or newest_event_id)
        time.sleep(args.poll_s)
        if time.time() - started_run > args.timeout_s:
            _cancel_on_timeout(args, batch_id)
            raise TimeoutError(f"batch {batch_id} did not finish in {args.timeout_s}s")
    run_s = time.time() - started_run
    if out_dir is not None:
        _write_json(out_dir / "status.json", status)
    collected = _get(args.base_url, "/ds4/queue/collect", {"batch_id": batch_id})
    if out_dir is not None:
        _write_json(out_dir / "collect.json", collected)
    return submit_s, run_s, collected


def _benchmark_summary(
    args: argparse.Namespace,
    batch_id: str,
    out_dir: Path | None,
    requests_payload: list[dict[str, Any]],
    submit_s: float,
    run_s: float,
    collected: dict[str, Any],
    *,
    vllm_metrics_before: dict[str, Any] | None = None,
    vllm_metrics_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _benchmark_metrics(args, requests_payload, run_s, collected)
    summary = {
        "format": "ds4-api-queue-benchmark-v1",
        "base_url": args.base_url,
        "batch_id": batch_id,
        "model": args.model,
        "batch_size": len(requests_payload),
        "concurrency": args.concurrency,
        "limit": args.limit,
        "input_tokens_target": args.input_tokens,
        "output_tokens_target": metrics["output_tokens_target"],
        "worker_mode": "api_sync_work" if args.drive_worker else "external_worker",
        "request_source": str(args.requests_jsonl) if args.requests_jsonl else "generated",
        "preserved_request_ids": bool(args.preserve_request_ids),
        "out_dir": str(out_dir) if out_dir else None,
        "ignore_eos": bool(args.ignore_eos),
        "cancel_on_timeout": bool(args.cancel_on_timeout),
        "min_tokens": metrics["output_tokens_target"] if args.ignore_eos else 0,
        "submit_s": round(submit_s, 6),
        "run_s": round(run_s, 6),
    }
    summary.update(metrics)
    vllm_metrics = _vllm_metrics_delta_summary(vllm_metrics_before, vllm_metrics_after)
    if vllm_metrics is not None:
        summary["vllm_metrics_url"] = args.vllm_metrics_url
        summary["vllm_metrics"] = vllm_metrics
    return summary


def _benchmark_metrics(args: argparse.Namespace, requests_payload: list[dict[str, Any]], run_s: float, collected: dict[str, Any]) -> dict[str, Any]:
    results = collected.get("results", [])
    completed = [row for row in results if isinstance(row, dict) and (row.get("result") or {}).get("status") == "completed"]
    tokens = sum(_completion_tokens(row.get("result") or {}) for row in completed)
    timings = _result_timings(results, run_s=run_s)
    aggregate_tok_s = tokens / run_s if run_s > 0 else 0.0
    transport_tok_s = tokens / timings["transport_duration_s_max"] if timings["transport_duration_s_max"] > 0 else 0.0
    target_tokens = _target_completion_tokens(requests_payload)
    output_token_range = _request_int_range(requests_payload, "max_output_tokens")
    perf_valid = int(timings["attempt_count_max"]) <= 1
    return {
        "timings": timings,
        "transport_counts": _transport_counts(results),
        "completed": len(completed),
        "failed": len(results) - len(completed),
        "completion_tokens": tokens,
        "completion_tokens_target": target_tokens,
        "completion_tokens_target_ratio": round(tokens / target_tokens, 6) if target_tokens > 0 else 0.0,
        "aggregate_completion_tok_s": round(aggregate_tok_s, 6),
        "transport_aggregate_completion_tok_s": round(transport_tok_s, 6),
        "perf_valid": perf_valid,
        "perf_invalid_reason": None if perf_valid else "transport_retries_detected",
        "performance_target": _benchmark_performance_score(args, aggregate_tok_s),
        "transport_performance_target": _benchmark_performance_score(args, transport_tok_s),
        "output_tokens_target": _uniform_request_int(requests_payload, "max_output_tokens", args.output_tokens),
        "output_tokens_target_min": output_token_range[0],
        "output_tokens_target_max": output_token_range[1],
    }


def _benchmark_performance_score(args: argparse.Namespace, aggregate_tok_s: float) -> dict[str, Any]:
    return _performance_score(
        aggregate_tok_s=aggregate_tok_s,
        concurrency=args.concurrency,
        pipeline_stages=args.pipeline_stages,
        equivalent_sparks=args.equivalent_sparks,
        reference_tok_s=args.reference_tok_s,
    )


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
    parser.add_argument("--shape-mix-json", help="JSON array of request shapes, for example '[{\"count\":64,\"input_tokens\":256,\"output_tokens\":128},{\"count\":64,\"input_tokens\":2048,\"output_tokens\":128}]'.")
    parser.add_argument("--shape-mix-file", help="Read --shape-mix-json from a file.")
    parser.add_argument("--shape-mix-order", choices=("grouped", "round-robin"), default="grouped", help="Order generated shape-mix requests. grouped preserves shape order; round-robin interleaves one request per shape each pass.")
    parser.add_argument("--shared-prefix-tokens", type=int, default=0, help="Approximate token count for a token-identical prefix placed before each unique suffix.")
    parser.add_argument("--suffix-tokens", type=int, help="Approximate token count for the per-request suffix when --shared-prefix-tokens is used. Defaults to input_tokens - shared_prefix_tokens.")
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument("--timeout-s", type=int, default=1800)
    parser.add_argument("--poll-s", type=float, default=0.02)
    parser.add_argument("--cancel-on-timeout", dest="cancel_on_timeout", action="store_true", default=True, help="Force-cancel the benchmark batch if polling times out.")
    parser.add_argument("--no-cancel-on-timeout", dest="cancel_on_timeout", action="store_false", help="Leave a timed-out benchmark batch in place for debugging.")
    parser.add_argument("--drive-worker", action="store_true", help="Also call the synchronous /ds4/queue/work endpoint. Production benchmarks should leave this off and run ds4_pipeline_queue_worker.sh separately.")
    parser.add_argument("--ignore-eos", dest="ignore_eos", action="store_true", default=True, help="Force benchmark decode to the requested output token count by passing ignore_eos/min_tokens through to vLLM.")
    parser.add_argument("--allow-eos", dest="ignore_eos", action="store_false", help="Let EOS stop generation early. This is useful for behavior tests, not throughput targets.")
    parser.add_argument("--pipeline-stages", type=int, default=8)
    parser.add_argument("--equivalent-sparks", type=int, default=2)
    parser.add_argument("--reference-tok-s", type=float, default=144.6, help="Known-good two-Spark-equivalent DSV4 c16 aggregate target.")
    parser.add_argument("--vllm-metrics-url", help="Snapshot this vLLM Prometheus metrics URL before and after the benchmark and include cache/token-source deltas in summary.json.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--job-class", default="analysis")
    parser.add_argument("--priority", type=int, default=None)
    parser.add_argument("--external-kv-key", help="Attach a DS4 external KV manifest load plan to every generated request.")
    parser.add_argument("--external-kv-namespace", default="bench")
    parser.add_argument("--external-kv-service-id")
    parser.add_argument("--external-kv-backend", default="auto")
    parser.add_argument("--external-kv-mode", default="prefer", choices=("prefer", "require", "skip"))
    parser.add_argument("--external-kv-miss-policy", default="compute", choices=("compute", "fail", "compute_and_store"))
    parser.add_argument("--external-kv-route-affinity", default="required", choices=("none", "preferred", "required"))
    parser.add_argument("--external-kv-prefix-hash")
    parser.add_argument("--external-kv-total-bytes", type=int, default=0)
    parser.add_argument("--kv-cache-directive-json", help="Attach an exact input.kv_cache directive JSON object to every generated request.")
    parser.add_argument("--kv-cache-directive-file", help="Read an exact input.kv_cache directive JSON object from this file.")
    parser.add_argument("--kv-cache-id", help="Build and attach an input.kv_cache directive for a node-local cache object.")
    parser.add_argument("--kv-cache-phase", default="warm-load", choices=("cold-store", "warm-load", "refresh-load-store"), help="Generated --kv-cache-id directive phase.")
    parser.add_argument("--kv-cache-backend", default="auto")
    parser.add_argument("--kv-cache-prefix-hash")
    parser.add_argument("--kv-cache-sha256", help="Required by local_store warm-load directives.")
    parser.add_argument("--kv-cache-bytes", type=int, default=0)
    parser.add_argument("--kv-cache-load-mode", choices=("prefer", "require", "skip"))
    parser.add_argument("--kv-cache-store-mode", choices=("write_through", "write_back", "skip"))
    parser.add_argument("--kv-cache-miss-policy", choices=("compute", "fail", "compute_and_store"))
    parser.add_argument("--kv-cache-route-affinity", default="required", choices=("none", "preferred", "required"))
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
    output_token_range = _request_int_range(requests_payload, "max_output_tokens")
    return {
        "format": "ds4-api-file-driven-benchmark-manifest-v1",
        "base_url": args.base_url,
        "batch_id": batch_id,
        "model": args.model,
        "request_count": len(requests_payload),
        "input_tokens_target": args.input_tokens,
        "shape_mix": _shape_mix_manifest(args),
        "shape_mix_order": getattr(args, "shape_mix_order", "grouped"),
        "shared_prefix_tokens_target": int(getattr(args, "shared_prefix_tokens", 0) or 0),
        "suffix_tokens_target": _suffix_tokens(args),
        "output_tokens_target": output_tokens_target,
        "output_tokens_target_min": output_token_range[0],
        "output_tokens_target_max": output_token_range[1],
        "completion_tokens_target": _target_completion_tokens(requests_payload),
        "concurrency": args.concurrency,
        "limit": args.limit,
        "worker_mode": "api_sync_work" if args.drive_worker else "external_worker",
        "requests_jsonl": "requests.jsonl",
        "preserved_request_ids": bool(args.preserve_request_ids),
        "ignore_eos": bool(args.ignore_eos),
        "min_tokens": output_tokens_target if args.ignore_eos else 0,
        "cache_mode": _cache_mode(args),
        "external_kv": _external_kv_manifest_summary(args),
        "kv_cache_directive": _kv_cache_directive_summary(args),
    }


def _uniform_request_int(requests_payload: list[dict[str, Any]], key: str, fallback: int) -> int:
    values: set[int] = set()
    for item in requests_payload:
        try:
            values.add(int(item[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return next(iter(values)) if len(values) == 1 else int(fallback)


def _request_int_range(requests_payload: list[dict[str, Any]], key: str) -> tuple[int, int]:
    values: list[int] = []
    for item in requests_payload:
        try:
            values.append(int(item[key]))
        except (KeyError, TypeError, ValueError):
            continue
    if not values:
        return (0, 0)
    return (min(values), max(values))


def _generated_requests(args: argparse.Namespace, batch_id: str, profile_id: str) -> list[dict[str, Any]]:
    shapes = _shape_mix(args)
    if not shapes:
        return [_request_json(args, batch_id, profile_id, idx) for idx in range(args.batch_size)]
    if getattr(args, "shape_mix_order", "grouped") == "round-robin":
        return _generated_round_robin_shape_requests(args, batch_id, profile_id, shapes)
    requests_payload: list[dict[str, Any]] = []
    for shape_index, shape in enumerate(shapes):
        count = max(1, int(shape.get("count", 1) or 1))
        for _ in range(count):
            idx = len(requests_payload)
            requests_payload.append(_request_json(args, batch_id, profile_id, idx, shape=shape, shape_index=shape_index))
    return requests_payload


def _generated_round_robin_shape_requests(args: argparse.Namespace, batch_id: str, profile_id: str, shapes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests_payload: list[dict[str, Any]] = []
    remaining = [max(1, int(shape.get("count", 1) or 1)) for shape in shapes]
    while any(count > 0 for count in remaining):
        for shape_index, shape in enumerate(shapes):
            if remaining[shape_index] <= 0:
                continue
            idx = len(requests_payload)
            requests_payload.append(_request_json(args, batch_id, profile_id, idx, shape=shape, shape_index=shape_index))
            remaining[shape_index] -= 1
    return requests_payload


def _shape_mix(args: argparse.Namespace) -> list[dict[str, Any]]:
    raw_json = getattr(args, "shape_mix_json", None)
    raw_file = getattr(args, "shape_mix_file", None)
    if raw_json and raw_file:
        raise ValueError("provide only one of --shape-mix-json or --shape-mix-file")
    if raw_file:
        raw_json = Path(str(raw_file)).read_text(encoding="utf-8")
    if not raw_json:
        return []
    data = json.loads(str(raw_json))
    if not isinstance(data, list) or not data:
        raise ValueError("shape mix must be a non-empty JSON array")
    shapes: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"shape mix entry {index} must be an object")
        shape = dict(item)
        shape.setdefault("count", 1)
        shape.setdefault("input_tokens", args.input_tokens)
        shape.setdefault("output_tokens", args.output_tokens)
        shapes.append(shape)
    return shapes


def _shape_mix_manifest(args: argparse.Namespace) -> list[dict[str, Any]]:
    return [
        {
            "count": max(1, int(shape.get("count", 1) or 1)),
            "input_tokens": max(1, int(shape.get("input_tokens", args.input_tokens) or args.input_tokens)),
            "output_tokens": max(1, int(shape.get("output_tokens", args.output_tokens) or args.output_tokens)),
            "shared_prefix_tokens": max(0, int(shape.get("shared_prefix_tokens", getattr(args, "shared_prefix_tokens", 0) or 0) or 0)),
            "suffix_tokens": _shape_suffix_tokens(args, shape),
        }
        for shape in _shape_mix(args)
    ]


def _request_json(args: argparse.Namespace, batch_id: str, profile_id: str, idx: int, *, shape: dict[str, Any] | None = None, shape_index: int | None = None) -> dict[str, Any]:
    output_tokens = _shape_int(args, shape, "output_tokens", args.output_tokens, minimum=1)
    input_payload = {
        "prompt": _prompt(args, idx, shape=shape),
        "openai": _openai_benchmark_fields(args),
    }
    if args.ignore_eos:
        input_payload["openai"]["min_tokens"] = output_tokens
    input_payload["benchmark_shape"] = {
        "shape_index": shape_index if shape_index is not None else 0,
        "input_tokens": _shape_int(args, shape, "input_tokens", args.input_tokens, minimum=1),
        "output_tokens": output_tokens,
        "shared_prefix_tokens": _shape_int(args, shape, "shared_prefix_tokens", getattr(args, "shared_prefix_tokens", 0) or 0, minimum=0),
        "suffix_tokens": _shape_suffix_tokens(args, shape),
    }
    _attach_cache_fields(input_payload, args)
    return {
        "format": "ds4-inference-request-v1",
        "request_id": f"{batch_id}-{idx:06d}",
        "capability": None,
        "chat": False,
        "immediate": False,
        "job_class": args.job_class,
        "max_output_tokens": output_tokens,
        "thinking_budget_tokens": 0,
        "temperature": args.temperature,
        "input": input_payload,
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


def _post(base_url: str, endpoint: str, body: dict[str, Any], *, timeout_s: float = 60.0) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(base_url.rstrip("/") + endpoint, data=data, headers={"content-type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"POST {endpoint} HTTP {exc.code}: {detail}") from exc


def _cancel_on_timeout(args: argparse.Namespace, batch_id: str) -> None:
    if not args.cancel_on_timeout:
        return
    try:
        _post(args.base_url, "/ds4/queue/cancel", {"batch_id": batch_id, "reason": "benchmark timed out", "force_running": True})
    except Exception:
        return


def _get(base_url: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    query = parse.urlencode({key: value for key, value in params.items() if value is not None})
    with request.urlopen(base_url.rstrip("/") + endpoint + ("?" + query if query else ""), timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _maybe_read_vllm_metrics(args: argparse.Namespace) -> dict[str, Any] | None:
    metrics_url = getattr(args, "vllm_metrics_url", None)
    if not metrics_url:
        return None
    with request.urlopen(str(metrics_url), timeout=30) as response:
        text = response.read().decode("utf-8", errors="replace")
    return _parse_vllm_prometheus_metrics(text)


def _parse_vllm_prometheus_metrics(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "format": "vllm-prometheus-snapshot-v1",
        "counters": {},
        "gauges": {},
        "prompt_tokens_by_source_total": {},
    }
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or " " not in raw:
            continue
        head, raw_value = raw.split(None, 1)
        try:
            value = float(raw_value.split()[0])
        except (IndexError, ValueError):
            continue
        metric_name, labels = _prometheus_metric_head(head)
        if metric_name == "prompt_tokens_by_source_total":
            source = labels.get("source") or "unknown"
            _add_metric_value(parsed["prompt_tokens_by_source_total"], source, value)
        elif metric_name in {
            "prompt_tokens_cached_total",
            "generation_tokens_total",
            "prefix_cache_query_total",
            "prefix_cache_queries_total",
            "prefix_cache_hit_total",
            "prefix_cache_hits_total",
            "external_prefix_cache_query_total",
            "external_prefix_cache_queries_total",
            "external_prefix_cache_hit_total",
            "external_prefix_cache_hits_total",
        }:
            _add_metric_value(parsed["counters"], metric_name, value)
        elif metric_name in {"num_requests_running", "num_requests_waiting"}:
            _add_metric_value(parsed["gauges"], metric_name, value)
        elif metric_name == "kv_cache_usage_perc":
            old_value = parsed["gauges"].get(metric_name)
            parsed["gauges"][metric_name] = round(max(float(old_value or 0.0), value), 6)
    return parsed


def _prometheus_metric_head(head: str) -> tuple[str, dict[str, str]]:
    labels: dict[str, str] = {}
    metric = head
    if "{" in head and head.endswith("}"):
        metric, label_text = head.split("{", 1)
        labels = _parse_prometheus_labels(label_text[:-1])
    if metric.startswith("vllm:"):
        metric = metric.split(":", 1)[1]
    return metric, labels


def _parse_prometheus_labels(label_text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    index = 0
    while index < len(label_text):
        equals = label_text.find("=", index)
        if equals < 0:
            break
        key = label_text[index:equals].strip()
        index = equals + 1
        if index >= len(label_text) or label_text[index] != '"':
            comma = label_text.find(",", index)
            if comma < 0:
                break
            index = comma + 1
            continue
        index += 1
        chars: list[str] = []
        while index < len(label_text):
            char = label_text[index]
            if char == "\\" and index + 1 < len(label_text):
                chars.append(label_text[index + 1])
                index += 2
                continue
            if char == '"':
                index += 1
                break
            chars.append(char)
            index += 1
        if key:
            labels[key] = "".join(chars)
        if index < len(label_text) and label_text[index] == ",":
            index += 1
    return labels


def _add_metric_value(values: dict[str, Any], key: str, value: float) -> None:
    values[key] = round(float(values.get(key) or 0.0) + float(value), 6)


def _vllm_metrics_delta_summary(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any] | None:
    if before is None and after is None:
        return None
    before = before or {}
    after = after or {}
    source_delta = _dict_metric_delta(
        before.get("prompt_tokens_by_source_total") if isinstance(before.get("prompt_tokens_by_source_total"), dict) else {},
        after.get("prompt_tokens_by_source_total") if isinstance(after.get("prompt_tokens_by_source_total"), dict) else {},
    )
    counter_delta = _dict_metric_delta(
        before.get("counters") if isinstance(before.get("counters"), dict) else {},
        after.get("counters") if isinstance(after.get("counters"), dict) else {},
    )
    derived = _vllm_metrics_derived_summary(source_delta, counter_delta)
    return {
        "before": before,
        "after": after,
        "delta": {
            "prompt_tokens_by_source_total": source_delta,
            "counters": counter_delta,
        },
        "derived": derived,
    }


def _vllm_metrics_derived_summary(source_delta: dict[str, float], counter_delta: dict[str, float]) -> dict[str, float]:
    total_prompt_tokens = round(sum(source_delta.values()), 6)
    external_tokens = source_delta.get("external_kv_transfer", 0.0)
    local_cache_tokens = source_delta.get("local_cache_hit", 0.0)
    local_compute_tokens = source_delta.get("local_compute", 0.0)
    cache_hit_tokens = round(external_tokens + local_cache_tokens, 6)
    prefix_queries = _counter_delta_value(counter_delta, "prefix_cache_queries_total", "prefix_cache_query_total")
    prefix_hits = _counter_delta_value(counter_delta, "prefix_cache_hits_total", "prefix_cache_hit_total")
    external_prefix_queries = _counter_delta_value(
        counter_delta,
        "external_prefix_cache_queries_total",
        "external_prefix_cache_query_total",
    )
    external_prefix_hits = _counter_delta_value(
        counter_delta,
        "external_prefix_cache_hits_total",
        "external_prefix_cache_hit_total",
    )
    return {
        "prompt_token_source_total_delta": total_prompt_tokens,
        "local_compute_token_delta": local_compute_tokens,
        "local_cache_hit_token_delta": local_cache_tokens,
        "external_kv_transfer_token_delta": external_tokens,
        "cache_hit_token_delta": cache_hit_tokens,
        "cache_hit_token_ratio": round(cache_hit_tokens / total_prompt_tokens, 6) if total_prompt_tokens > 0 else 0.0,
        "generation_token_delta": counter_delta.get("generation_tokens_total", 0.0),
        "prompt_tokens_cached_delta": counter_delta.get("prompt_tokens_cached_total", 0.0),
        "prefix_cache_query_delta": prefix_queries,
        "prefix_cache_hit_delta": prefix_hits,
        "prefix_cache_hit_ratio": round(prefix_hits / prefix_queries, 6) if prefix_queries > 0 else 0.0,
        "external_prefix_cache_query_delta": external_prefix_queries,
        "external_prefix_cache_hit_delta": external_prefix_hits,
        "external_prefix_cache_hit_ratio": (
            round(external_prefix_hits / external_prefix_queries, 6)
            if external_prefix_queries > 0
            else 0.0
        ),
    }


def _counter_delta_value(counters: dict[str, float], *names: str) -> float:
    return round(sum(float(counters.get(name) or 0.0) for name in names), 6)


def _dict_metric_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float]:
    keys = sorted(set(before) | set(after))
    delta: dict[str, float] = {}
    for key in keys:
        try:
            value = float(after.get(key) or 0.0) - float(before.get(key) or 0.0)
        except (TypeError, ValueError):
            continue
        if abs(value) > 0.0000001:
            delta[str(key)] = round(value, 6)
    return delta


def _prompt(args: argparse.Namespace, idx: int, *, shape: dict[str, Any] | None = None) -> str:
    input_tokens = _shape_int(args, shape, "input_tokens", args.input_tokens, minimum=1)
    shared_tokens = _shape_int(args, shape, "shared_prefix_tokens", getattr(args, "shared_prefix_tokens", 0) or 0, minimum=0)
    if shared_tokens > 0:
        shared = " ".join("shared-prefix-benchmark" for _ in range(shared_tokens))
        suffix = " ".join("request-specific-detail" for _ in range(_shape_suffix_tokens(args, shape)))
        return f"{shared}\n\nRequest {idx}. Continue with useful, non-repetitive details until the token budget is used. {suffix}"
    filler = " ".join("benchmark" for _ in range(input_tokens))
    return f"Request {idx}. Continue with useful, non-repetitive details until the token budget is used. {filler}"


def _suffix_tokens(args: argparse.Namespace) -> int:
    shared_tokens = int(getattr(args, "shared_prefix_tokens", 0) or 0)
    if shared_tokens <= 0:
        return max(1, int(args.input_tokens))
    suffix = getattr(args, "suffix_tokens", None)
    if suffix is not None:
        return max(1, int(suffix))
    return max(1, int(args.input_tokens) - shared_tokens)


def _shape_suffix_tokens(args: argparse.Namespace, shape: dict[str, Any] | None) -> int:
    if shape is None:
        return _suffix_tokens(args)
    shared_tokens = _shape_int(args, shape, "shared_prefix_tokens", getattr(args, "shared_prefix_tokens", 0) or 0, minimum=0)
    suffix = shape.get("suffix_tokens")
    if suffix is not None:
        return max(1, int(suffix))
    input_tokens = _shape_int(args, shape, "input_tokens", args.input_tokens, minimum=1)
    return max(1, input_tokens - shared_tokens) if shared_tokens > 0 else input_tokens


def _shape_int(args: argparse.Namespace, shape: dict[str, Any] | None, key: str, fallback: int, *, minimum: int) -> int:
    value = shape.get(key) if shape is not None and shape.get(key) is not None else fallback
    return max(minimum, int(value))


def _attach_cache_fields(input_payload: dict[str, Any], args: argparse.Namespace) -> None:
    directive = _kv_cache_directive(args)
    external_plan = _external_kv_plan(args)
    if directive is not None and external_plan is not None:
        raise ValueError("provide only one of --kv-cache-directive-* or --external-kv-key")
    if directive is not None:
        input_payload["kv_cache"] = directive
        return
    if external_plan is not None:
        input_payload["kv_cache_plan"] = _plan_with_source_provenance(external_plan, input_payload)
        input_payload["kv_cache_key"] = external_plan["cache_id"]
        total_bytes = int(getattr(args, "external_kv_total_bytes", 0) or 0)
        if total_bytes > 0:
            input_payload["kv_bytes_estimate"] = total_bytes


def _kv_cache_directive(args: argparse.Namespace) -> dict[str, Any] | None:
    raw_json = getattr(args, "kv_cache_directive_json", None)
    raw_file = getattr(args, "kv_cache_directive_file", None)
    generated = _generated_kv_cache_directive(args)
    if sum(1 for value in (raw_json, raw_file, generated) if value) > 1:
        raise ValueError("provide only one of --kv-cache-directive-json, --kv-cache-directive-file, or --kv-cache-id")
    if raw_json:
        data = json.loads(str(raw_json))
    elif raw_file:
        data = json.loads(Path(str(raw_file)).read_text(encoding="utf-8"))
    elif generated:
        data = generated
    else:
        return None
    if not isinstance(data, dict):
        raise ValueError("KV cache directive must be a JSON object")
    return data


def _generated_kv_cache_directive(args: argparse.Namespace) -> dict[str, Any] | None:
    cache_id = getattr(args, "kv_cache_id", None)
    if not cache_id:
        return None
    phase = str(getattr(args, "kv_cache_phase", "warm-load") or "warm-load")
    load_enabled = phase in {"warm-load", "refresh-load-store"}
    store_enabled = phase in {"cold-store", "refresh-load-store"}
    load_mode = getattr(args, "kv_cache_load_mode", None) or ("require" if load_enabled else "skip")
    store_mode = getattr(args, "kv_cache_store_mode", None) or ("write_back" if store_enabled else "skip")
    if load_mode != "skip" and not getattr(args, "kv_cache_sha256", None):
        raise ValueError("--kv-cache-sha256 is required when generated local_store KV cache loading is enabled")
    directive: dict[str, Any] = {
        "format": "ds4-kv-cache-directive-v1",
        "cache_id": str(cache_id),
        "backend": str(getattr(args, "kv_cache_backend", "auto") or "auto"),
        "load": _local_store_endpoint(mode=load_mode, cache_id=str(cache_id), args=args, load=True),
        "store": _local_store_endpoint(mode=store_mode, cache_id=str(cache_id), args=args, load=False),
        "miss_policy": getattr(args, "kv_cache_miss_policy", None) or _generated_miss_policy(load_mode, store_mode),
        "route_affinity": str(getattr(args, "kv_cache_route_affinity", "required") or "required"),
        "model_fingerprint": {},
    }
    prefix_hash = getattr(args, "kv_cache_prefix_hash", None)
    if prefix_hash:
        directive["prefix_hash"] = str(prefix_hash)
    return directive


def _local_store_endpoint(*, mode: str, cache_id: str, args: argparse.Namespace, load: bool) -> dict[str, Any]:
    if mode == "skip":
        return {"mode": "skip", "transport": "none"}
    endpoint: dict[str, Any] = {"mode": mode, "transport": "local_store", "cache_key": cache_id}
    sha256 = getattr(args, "kv_cache_sha256", None)
    if sha256:
        endpoint["sha256"] = str(sha256)
    byte_count = int(getattr(args, "kv_cache_bytes", 0) or 0)
    if byte_count > 0:
        endpoint["bytes"] = byte_count
    if not load:
        endpoint["on_error"] = "fail"
    return endpoint


def _generated_miss_policy(load_mode: str, store_mode: str) -> str:
    if load_mode == "require":
        return "fail"
    if load_mode != "skip":
        return "compute_and_store" if store_mode != "skip" else "compute"
    return "compute_and_store" if store_mode != "skip" else "compute"


def _external_kv_plan(args: argparse.Namespace) -> dict[str, Any] | None:
    kv_key = getattr(args, "external_kv_key", None)
    if not kv_key:
        return None
    namespace = str(getattr(args, "external_kv_namespace", "bench") or "bench")
    service_id = getattr(args, "external_kv_service_id", None)
    load: dict[str, Any] = {
        "mode": str(getattr(args, "external_kv_mode", "prefer") or "prefer"),
        "transport": "external_manifest",
        "namespace": namespace,
        "kv_key": str(kv_key),
    }
    if service_id:
        load["service_id"] = str(service_id)
    plan: dict[str, Any] = {
        "format": "ds4-kv-cache-plan-v1",
        "backend": str(getattr(args, "external_kv_backend", "auto") or "auto"),
        "cache_id": str(kv_key),
        "prefix_hash": _optional_str(getattr(args, "external_kv_prefix_hash", None)),
        "load": load,
        "store": {"mode": "skip", "transport": "none"},
        "miss_policy": str(getattr(args, "external_kv_miss_policy", "compute") or "compute"),
        "route_affinity": str(getattr(args, "external_kv_route_affinity", "required") or "required"),
        "model_fingerprint": {},
        "operation": "load",
    }
    plan["batch_key_hash"] = "sha256:" + hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return plan


def _plan_with_source_provenance(plan: dict[str, Any], input_payload: dict[str, Any]) -> dict[str, Any]:
    prompt = input_payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return plan
    prompt_bytes = prompt.encode("utf-8")
    out = dict(plan)
    source: dict[str, Any] = {
        "format": "ds4-kv-source-provenance-v1",
        "source_type": "prompt",
        "prompt_sha256": "sha256:" + hashlib.sha256(prompt_bytes).hexdigest(),
        "prompt_bytes": len(prompt_bytes),
        "prompt_text": prompt,
    }
    shape = input_payload.get("benchmark_shape")
    if isinstance(shape, dict) and shape.get("input_tokens") is not None:
        source["estimated_prompt_tokens"] = int(shape.get("input_tokens") or 0)
    out["source_provenance"] = source
    return out


def _cache_mode(args: argparse.Namespace) -> str:
    if _kv_cache_directive(args) is not None:
        return "kv_cache_directive"
    if _external_kv_plan(args) is not None:
        return "external_kv"
    if int(getattr(args, "shared_prefix_tokens", 0) or 0) > 0:
        return "vllm_prefix_cache_candidate"
    return "cold_unique_prefix"


def _external_kv_manifest_summary(args: argparse.Namespace) -> dict[str, Any] | None:
    if not getattr(args, "external_kv_key", None):
        return None
    return {
        "namespace": str(getattr(args, "external_kv_namespace", "bench") or "bench"),
        "kv_key": str(getattr(args, "external_kv_key")),
        "service_id": _optional_str(getattr(args, "external_kv_service_id", None)),
        "mode": str(getattr(args, "external_kv_mode", "prefer") or "prefer"),
        "miss_policy": str(getattr(args, "external_kv_miss_policy", "compute") or "compute"),
        "route_affinity": str(getattr(args, "external_kv_route_affinity", "required") or "required"),
    }


def _kv_cache_directive_summary(args: argparse.Namespace) -> dict[str, Any] | None:
    directive = _kv_cache_directive(args)
    if directive is None:
        return None
    return {
        "format": directive.get("format"),
        "cache_id": directive.get("cache_id"),
        "prefix_hash": directive.get("prefix_hash"),
        "backend": directive.get("backend"),
        "load": directive.get("load"),
        "store": directive.get("store"),
    }


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


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


def _transport_counts(results: list[Any]) -> dict[str, int]:
    counts = {
        "coalesced_chat_batch": 0,
        "coalesced_completion_batch": 0,
        "coalesced_completion_streaming": 0,
        "coalesced_completion_split_retry": 0,
        "transport_failed": 0,
    }
    for row in results:
        if not isinstance(row, dict):
            continue
        result = row.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("status") == "transport_failed":
            counts["transport_failed"] += 1
        transport = result.get("transport")
        if not isinstance(transport, dict):
            continue
        for key in counts:
            if key == "transport_failed":
                continue
            if bool(transport.get(key)):
                counts[key] += 1
    return counts


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
