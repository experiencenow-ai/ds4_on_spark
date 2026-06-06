from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .builders import new_id, sparkrunner_request
from .profiles import ProfileRegistry
from .pipelines import pipeline_service_batch_limit
from .queue import InferenceQueue
from .runners import make_runner
from .topology import SparkTopology

V2_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    registry = ProfileRegistry.load(args.profiles_dir)
    topology = SparkTopology.load(args.topology)
    queue = InferenceQueue(args.queue_dir)
    records = _read_jsonl(Path(args.input))
    seen: set[str] = set()
    requests = [sparkrunner_request(record, args.model, registry, idx, seen) for idx, record in enumerate(records)]
    response_path = Path(args.output)
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text("", encoding="utf-8")
    record_by_request_id = {request.request_id: records[idx] for idx, request in enumerate(requests)}
    batch_id = args.batch_id or new_id("sparkrunner")
    queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id=batch_id, priority=args.priority)
    runner = make_runner(args.runner, timeout_s=args.timeout_s)
    while True:
        queue.work(
            registry=registry,
            runner=runner,
            batch_id=batch_id,
            limit=max(1, args.work_limit),
            concurrency=max(1, args.concurrency),
            kv_shard_layouts_by_profile=dict(topology.profile_pipeline_services),
            batch_limits_by_service={service.service_id: pipeline_service_batch_limit(service) for service in topology.pipeline_services.values()},
            refill_low_watermarks_by_service={service.service_id: int(service.scheduler.get("refill_low_watermark") or 0) for service in topology.pipeline_services.values()},
            on_result=lambda claim, result: _append_response(response_path, record_by_request_id, args.model, args.response_format, claim.request_id, result),
        )
        status = queue.status(batch_id=batch_id)
        if status.get("state") in {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled"}:
            break
        if time.time() > args.deadline:
            raise TimeoutError(f"batch {batch_id} did not complete before timeout")
        time.sleep(args.poll_s)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SparkRunner JSONL through the v2 ds4-infer queue")
    parser.add_argument("--input", "--input-jsonl", "--requests", "--requests-jsonl", dest="input", required=True)
    parser.add_argument("--output", "--output-jsonl", "--responses", "--responses-jsonl", dest="output", required=True)
    parser.add_argument("--model", default="ds4v")
    parser.add_argument("--profiles-dir", default=str(V2_ROOT / "profiles" / "models"))
    parser.add_argument("--topology", default=str(V2_ROOT / "profiles" / "topology" / "static_sparks.json"))
    parser.add_argument("--queue-dir", default="/tmp/ds4_v2_queue")
    parser.add_argument("--batch-id")
    parser.add_argument("--runner", choices=["spark", "fake"], default="spark")
    parser.add_argument("--response-format", choices=["sparkrunner", "inference"], default="sparkrunner")
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--work-limit", type=int, default=16)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--priority", type=int, help="Lower numbers run first. Default is 10 for normal queued requests and 0 for immediate requests.")
    parser.add_argument("--poll-s", type=float, default=0.2)
    args = parser.parse_args(argv)
    args.deadline = time.time() + max(1, args.timeout_s)
    return args


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _append_response(path: Path, records: dict[str, dict[str, Any]], model: str, response_format: str, request_id: str, result: dict[str, Any]) -> None:
    record = records.get(request_id, {"custom_id": request_id})
    row = _response_row(record, result, model, response_format)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _response_row(record: dict[str, Any], result: dict[str, Any], model: str, response_format: str) -> dict[str, Any]:
    if response_format == "inference":
        return result
    custom_id = str(record.get("custom_id") or record.get("request_id") or result.get("request_id") or "request")
    output = result.get("output", {}) if isinstance(result, dict) else {}
    text = output.get("text", "") if isinstance(output, dict) else ""
    if not text and isinstance(result, dict) and result.get("status") != "completed":
        text = str(result.get("error") or json.dumps(result, sort_keys=True))
    usage = result.get("usage", {}) if isinstance(result, dict) else {}
    return {"custom_id": custom_id, "model": model, "text": str(text), "candidates": [{"text": str(text)}], "usage": usage}


if __name__ == "__main__":
    sys.exit(main())
