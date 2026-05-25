from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .profiles import ProfileRegistry
from .queue import InferenceQueue
from .runners import make_runner
from .schemas import InferenceRequest
from .topology import SparkTopology

V2_ROOT = Path(__file__).resolve().parents[2]
MODEL_ALIASES = {
    "ds4a": "dsv4_antirez_smart_v1",
    "ds4v": "dsv4_vllm_mtp_smartest_v1",
    "qwen": "qwen3_6_27b_fp8_efficient_v1",
    "fast": "qwen3_6_35b_a3b_fp8_fastest_v1",
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    registry = ProfileRegistry.load(args.profiles_dir)
    topology = SparkTopology.load(args.topology)
    queue = InferenceQueue(args.queue_dir)
    records = _read_jsonl(Path(args.input))
    requests = [_to_request(record, args.model, registry, idx) for idx, record in enumerate(records)]
    batch_id = args.batch_id or f"sparkrunner-{int(time.time() * 1000)}"
    queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id=batch_id)
    runner = make_runner(args.runner, timeout_s=args.timeout_s)
    while True:
        queue.work(registry=registry, runner=runner, limit=max(1, args.work_limit))
        status = queue.status(batch_id=batch_id)
        if status.get("state") in {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled"}:
            break
        if time.time() > args.deadline:
            raise TimeoutError(f"batch {batch_id} did not complete before timeout")
        time.sleep(args.poll_s)
    collected = queue.collect(batch_id=batch_id)
    outputs = _responses(records, collected.get("results", []), args.model, args.response_format)
    _write_jsonl(Path(args.output), outputs)
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
    parser.add_argument("--runner", choices=["spark", "auto", "fake"], default="spark")
    parser.add_argument("--response-format", choices=["sparkrunner", "inference"], default="sparkrunner")
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--work-limit", type=int, default=16)
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


def _to_request(record: dict[str, Any], model: str, registry: ProfileRegistry, index: int) -> InferenceRequest:
    profile_id = MODEL_ALIASES.get(model, model)
    profile = registry.get(profile_id)
    custom_id = str(record.get("custom_id") or record.get("request_id") or f"request-{index}")
    messages = record.get("messages")
    chat = bool(profile.supports_chat and isinstance(messages, list) and messages)
    prompt = str(record.get("prompt") or _messages_text(messages if isinstance(messages, list) else []))
    data = {
        "format": "ds4-inference-request-v1",
        "request_id": _safe_id(custom_id, index),
        "capability": None,
        "chat": chat,
        "immediate": bool(record.get("immediate", False)),
        "job_class": str(record.get("job_class") or _job_class(profile.supported_job_classes, chat)),
        "max_output_tokens": int(record.get("max_tokens") or record.get("max_completion_tokens") or 1024),
        "thinking_budget_tokens": int(record.get("thinking_budget_tokens") or 0),
        "temperature": float(record.get("temperature", 0.0)),
        "input": {"messages": messages if isinstance(messages, list) else [], "prompt": prompt, "suffix": prompt},
        "output_contract": dict(record.get("output_contract") or {"format": "text"}),
        "model_pin": {"profile_id": profile.profile_id},
    }
    return InferenceRequest.from_json(data)


def _responses(records: list[dict[str, Any]], results: list[dict[str, Any]], model: str, response_format: str) -> list[dict[str, Any]]:
    by_id = {item.get("request", {}).get("request_id"): item for item in results if isinstance(item, dict)}
    outputs: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        custom_id = str(record.get("custom_id") or record.get("request_id") or f"request-{index}")
        item = by_id.get(_safe_id(custom_id, index), {})
        result = item.get("result", {}) if isinstance(item, dict) else {}
        if response_format == "inference":
            outputs.append(result)
            continue
        output = result.get("output", {}) if isinstance(result, dict) else {}
        text = output.get("text", "") if isinstance(output, dict) else ""
        outputs.append({"custom_id": custom_id, "model": model, "text": str(text), "candidates": [{"text": str(text)}], "usage": result.get("usage", {}) if isinstance(result, dict) else {}})
    return outputs


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _messages_text(messages: list[Any]) -> str:
    return "\n".join(str(message.get("content", "")) for message in messages if isinstance(message, dict))


def _safe_id(value: str, index: int) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value)
    return keep or f"request-{index}"


def _job_class(supported: tuple[str, ...], chat: bool) -> str:
    preferred = ("tool_chat", "analysis", "summary", "atom_edit") if chat else ("atom_edit", "analysis", "summary")
    for job_class in preferred:
        if job_class in supported:
            return job_class
    return supported[0]


if __name__ == "__main__":
    sys.exit(main())
