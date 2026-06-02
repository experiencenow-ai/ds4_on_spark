from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import time
from typing import Any
import uuid

from .profiles import ModelProfile, ProfileRegistry
from .schemas import InferenceRequest
from .topology import SparkTopology


API_TERMINAL_STATES = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}


def openai_completion_requests(body: dict[str, Any], registry: ProfileRegistry, topology: SparkTopology) -> tuple[ModelProfile, str, str, list[InferenceRequest]]:
    from . import api as api_module

    profile = api_module._resolve_profile(registry, topology, api_module._optional_str(body.get("model")))
    base_request_id = str(body.get("request_id") or f"cmpl-{uuid.uuid4().hex}")
    batch_id = str(body.get("batch_id") or base_request_id)
    prompts = api_module._completion_prompt_items(body.get("prompt"))
    raw_requests = []
    client_stream = bool(body.get("stream"))
    for index, prompt in enumerate(prompts):
        request_id = base_request_id if len(prompts) == 1 else f"{base_request_id}-{index:06d}"
        input_payload = api_module._input_with_api_kv({"prompt": prompt}, body, profile, topology)
        if client_stream:
            input_payload["ds4_client_stream"] = True
        raw_requests.append(
            api_module._make_inference_request_json(
                request_id=request_id,
                profile=profile,
                chat=False,
                input_payload=input_payload,
                output_contract={"format": "text"},
                max_tokens=int(body.get("max_tokens") or 1024),
                temperature=float(body.get("temperature") or 0.0),
                job_class=str(body.get("ds4_job_class") or "analysis"),
                capability=api_module._optional_str(body.get("ds4_capability")),
            )
        )
    return profile, base_request_id, batch_id, [InferenceRequest.from_json(raw) for raw in raw_requests]


def openai_completion_stream_events(api: Any, body: dict[str, Any]):
    from . import api as api_module

    registry = api._registry()
    topology = api._topology()
    profile, base_request_id, batch_id, requests = openai_completion_requests(body, registry, topology)
    if api_module._is_async_request(body):
        raise ValueError("stream=true cannot be combined with ds4_async")
    status = api.queue.status()
    after_event_id = int(status.get("newest_event_id") or 0)
    api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id=batch_id, priority=api_module._optional_int(body.get("priority")))
    timeout_s = float(body.get("ds4_timeout_s") or api.sync_timeout_s)
    model = str(body.get("model") or profile.model_id)
    return _iter_completion_stream(api, base_request_id, model, batch_id, requests, after_event_id, timeout_s)


def _iter_completion_stream(api: Any, request_id: str, model: str, batch_id: str, requests: list[InferenceRequest], after_event_id: int, timeout_s: float):
    pending = {request.request_id: (index, request) for index, request in enumerate(requests)}
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    deadline = time.time() + max(0.1, timeout_s)
    while pending and time.time() < deadline:
        after_event_id, chunks = _drain_completion_stream_events(api, request_id, model, batch_id, pending, usage, after_event_id)
        for chunk in chunks:
            yield chunk
        if pending:
            if not api._dispatcher_is_active():
                if api.dispatcher_enabled and api.dispatcher_thread is not None:
                    break
                api._work_once({"batch_id": batch_id})
            time.sleep(api.poll_interval_s)
    for request_key, (index, _request) in list(pending.items()):
        pending.pop(request_key, None)
        yield _openai_completion_timeout_chunk(request_id, model, batch_id, index, request_key)
    yield _openai_completion_usage_chunk(request_id, model, batch_id, len(requests), usage)


def _drain_completion_stream_events(api: Any, request_id: str, model: str, batch_id: str, pending: dict[str, tuple[int, InferenceRequest]], usage: dict[str, int], after_event_id: int):
    poll = api.queue.poll(after_event_id=after_event_id, limit=200)
    chunks = []
    for event in poll.get("events") or []:
        request_key = str(event.get("request_id") or "")
        state = str(event.get("state") or "")
        if request_key not in pending or state not in API_TERMINAL_STATES:
            continue
        index, _request = pending.pop(request_key)
        row = api.queue.collect(request_id=request_key)
        chunk, item_usage = _openai_completion_stream_chunk(request_id, model, batch_id, index, row)
        _add_usage(usage, item_usage)
        chunks.append(chunk)
    return int(poll.get("newest_event_id") or after_event_id), chunks


def _openai_completion_stream_chunk(request_id: str, model: str, batch_id: str, index: int, row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    from . import api as api_module

    text, status = api_module._result_text_and_status(row)
    usage = api_module._result_usage(row)
    chunk = {
        "id": request_id,
        "object": "text_completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": index, "text": text, "finish_reason": "stop" if status == "completed" else "error"}],
        "usage": usage,
        "ds4": {"batch_id": batch_id, "request": row.get("request"), "status": status},
    }
    return chunk, usage


def _openai_completion_timeout_chunk(request_id: str, model: str, batch_id: str, index: int, request_key: str) -> dict[str, Any]:
    return {
        "id": request_id,
        "object": "text_completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": index, "text": "coordinator stream timeout", "finish_reason": "error"}],
        "ds4": {"batch_id": batch_id, "request_id": request_key, "status": "failed"},
    }


def _openai_completion_usage_chunk(request_id: str, model: str, batch_id: str, result_count: int, usage: dict[str, int]) -> dict[str, Any]:
    return {
        "id": request_id,
        "object": "text_completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [],
        "usage": dict(usage),
        "ds4": {"batch_id": batch_id, "result_count": result_count, "status": "completed"},
    }


def _add_usage(total: dict[str, int], item: dict[str, int]) -> None:
    total["prompt_tokens"] += int(item.get("prompt_tokens", 0) or 0)
    total["completion_tokens"] += int(item.get("completion_tokens", 0) or 0)
    total["total_tokens"] += int(item.get("total_tokens", 0) or 0)


def write_sse(handler: BaseHTTPRequestHandler, events) -> None:
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("x-accel-buffering", "no")
    handler.end_headers()
    for event in events:
        body = "data: " + json.dumps(event, sort_keys=True) + "\n\n"
        handler.wfile.write(body.encode("utf-8"))
        handler.wfile.flush()
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()
