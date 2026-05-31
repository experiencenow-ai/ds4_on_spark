from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
import uuid

from .profiles import ModelProfile, ProfileRegistry
from .kv_cache import KV_CACHE_DIRECTIVE_FORMAT, KV_CACHE_PLAN_FORMAT, normalize_kv_cache_directive
from .runners import FakeRunner, PipelineOpenAIRunner, Runner
from .queue import InferenceQueue
from .schemas import InferenceRequest, REQUEST_FORMAT
from .topology import SparkTopology


class CoordinatorApi:
    def __init__(
        self,
        *,
        queue_dir: str | Path,
        profiles_dir: str | Path,
        topology_path: str | Path,
        runner_kind: str = "pipeline",
        sync_timeout_s: float = 300.0,
        poll_interval_s: float = 0.02,
    ) -> None:
        self.queue = InferenceQueue(queue_dir)
        self.profiles_dir = Path(profiles_dir)
        self.topology_path = Path(topology_path)
        self.runner_kind = runner_kind
        self.sync_timeout_s = float(sync_timeout_s)
        self.poll_interval_s = max(0.001, float(poll_interval_s))
        self.dispatcher_enabled = _env_bool("DS4_API_BACKGROUND_DISPATCH", True)
        self.dispatcher_window = max(1, _env_int("DS4_API_DISPATCH_WINDOW", 64))
        self.dispatcher_idle_sleep_s = max(0.001, _env_float("DS4_API_DISPATCH_IDLE_SLEEP_S", 0.005))
        self.dispatcher_batch_linger_s = max(0.0, _env_float("DS4_API_DISPATCH_BATCH_LINGER_S", 0.01))
        self.dispatcher_lease_ttl_s = max(1, _env_int("DS4_API_DISPATCH_LEASE_TTL_S", 900))
        self.dispatcher_heartbeat_s = max(0.25, _env_float("DS4_API_DISPATCH_HEARTBEAT_S", 2.0))
        self.dispatcher_transport_timeout_s = max(1, _env_int("DS4_API_TRANSPORT_TIMEOUT_S", 3600))
        self.dispatcher_transport_max_attempts = max(1, _env_int("DS4_API_TRANSPORT_MAX_ATTEMPTS", 1))
        self.dispatcher_stop = threading.Event()
        self.dispatcher_thread: threading.Thread | None = None
        self.dispatcher_lock = threading.Lock()
        self.dispatcher_state: dict[str, Any] = {
            "enabled": self.dispatcher_enabled,
            "running": False,
            "window": self.dispatcher_window,
            "started_at": None,
            "last_work_at": None,
            "last_error": None,
            "worked_count": 0,
            "claimed_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "retried_count": 0,
            "idle_count": 0,
            "transport_timeout_s": self.dispatcher_transport_timeout_s,
            "transport_max_attempts": self.dispatcher_transport_max_attempts,
            "last_summary": None,
        }

    def handle_get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        if path in {"/health", "/ds4/health"}:
            return 200, {"ok": True, "service": "ds4-coordinator-api", "entry_node_id": self._topology().routing_policy.get("queue_entry_node_id", "spark0"), "dispatcher": self.dispatcher_status()}
        if path == "/v1/models":
            return 200, _openai_models(self._registry(), self._topology())
        if path == "/ds4/dispatcher/status":
            return 200, self.dispatcher_status()
        if path == "/ds4/queue/status":
            return 200, self.queue.status(request_id=_one(query, "request_id"), batch_id=_one(query, "batch_id"), job_id=_one(query, "job_id"))
        if path == "/ds4/queue/poll":
            return 200, self.queue.poll(after_event_id=int(_one(query, "after_event_id") or 0), limit=int(_one(query, "limit") or 100))
        if path == "/ds4/queue/collect":
            return 200, self.queue.collect(request_id=_one(query, "request_id"), batch_id=_one(query, "batch_id"), job_id=_one(query, "job_id"))
        if path == "/ds4/pipelines":
            topology = self._topology()
            status = self.queue.pipeline_status(service_id=_one(query, "service_id"))
            return 200, {"format": "ds4-pipeline-api-status-v1", "topology": topology.to_public_dict(), "queue": status}
        if path in {"/ds4/kvcache/lookup", "/ds4/kv-cache/lookup", "/ds4/kvcache/resolve", "/ds4/kv-cache/resolve"}:
            return 200, self.queue.external_kv_lookup(namespace=_one(query, "namespace") or "default", kv_key=_required_query(query, "kv_key"), service_id=_one(query, "service_id"))
        if path in {"/ds4/kvcache/list", "/ds4/kv-cache/list"}:
            return 200, self.queue.external_kv_list(
                namespace=_one(query, "namespace") or "default",
                service_id=_one(query, "service_id"),
                owner=_one(query, "owner"),
                state=_one(query, "state"),
                prefix=_one(query, "prefix"),
                include_shards=(_one(query, "include_shards") or "").lower() in {"1", "true", "yes"},
                limit=int(_one(query, "limit") or 100),
            )
        return 404, {"error": f"unknown endpoint: {path}"}

    def handle_post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/v1/chat/completions":
            return self._handle_openai_chat(body)
        if path == "/v1/completions":
            return self._handle_openai_completion(body)
        if path == "/v1/messages":
            return self._handle_anthropic_messages(body)
        if path == "/ds4/queue/submit":
            raw_requests = body.get("requests")
            if not isinstance(raw_requests, list):
                return 400, {"error": "requests must be a list"}
            requests = [InferenceRequest.from_json(dict(item)) for item in raw_requests]
            return 200, self.queue.submit_requests(requests=requests, registry=self._registry(), topology=self._topology(), batch_id=_optional_str(body.get("batch_id")), priority=_optional_int(body.get("priority")))
        if path == "/ds4/queue/work":
            return 200, self._work_once(body)
        if path == "/ds4/queue/cancel":
            return 200, self.queue.cancel(request_id=_optional_str(body.get("request_id")), batch_id=_optional_str(body.get("batch_id")), job_id=_optional_str(body.get("job_id")), reason=str(body.get("reason") or "cancelled by operator"))
        if path == "/ds4/pipeline/telemetry":
            topology = self._topology()
            return 200, self.queue.record_pipeline_telemetry(_pipeline_telemetry_with_topology(body, topology))
        if path in {"/ds4/kvcache/declare", "/ds4/kv-cache/declare"}:
            return 200, self._kv_declare(body)
        if path in {"/ds4/kvcache/lookup", "/ds4/kv-cache/lookup", "/ds4/kvcache/resolve", "/ds4/kv-cache/resolve"}:
            return 200, self.queue.external_kv_lookup(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=_optional_str(body.get("service_id")))
        if path in {"/ds4/kvcache/list", "/ds4/kv-cache/list"}:
            return 200, self.queue.external_kv_list(
                namespace=str(body.get("namespace") or "default"),
                service_id=_optional_str(body.get("service_id")),
                owner=_optional_str(body.get("owner")),
                state=_optional_str(body.get("state")),
                prefix=_optional_str(body.get("prefix")),
                include_shards=bool(body.get("include_shards")),
                limit=int(body.get("limit") or 100),
            )
        if path in {"/ds4/kvcache/touch", "/ds4/kv-cache/touch", "/ds4/kvcache/metadata", "/ds4/kv-cache/metadata"}:
            return 200, self.queue.external_kv_touch(
                namespace=str(body.get("namespace") or "default"),
                kv_key=str(body["kv_key"]),
                service_id=str(body["service_id"]),
                owner=_optional_str(body.get("owner")),
                state=_optional_str(body.get("state")),
                priority=_optional_int(body.get("priority")),
                ttl_s=float(body["ttl_s"]) if body.get("ttl_s") is not None else None,
                metadata=dict(body.get("metadata") or {}),
            )
        if path in {"/ds4/kvcache/lease", "/ds4/kv-cache/lease"}:
            return 200, self.queue.external_kv_lease(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=str(body["service_id"]), owner=_optional_str(body.get("owner")), mode=str(body.get("mode") or "read"), ttl_s=float(body.get("ttl_s") or 300.0))
        if path in {"/ds4/kvcache/release", "/ds4/kv-cache/release"}:
            return 200, self.queue.external_kv_release(lease_id=str(body["lease_id"]))
        if path in {"/ds4/kvcache/prefetch", "/ds4/kv-cache/prefetch"}:
            service_id = str(body["service_id"])
            manifest = self.queue.external_kv_transition(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=service_id, state="prefetch_requested", shard_state="prefetch_requested", metadata={"prefetch": dict(body), "execution": "control_plane_only"})
            manifest["prefetch"] = {"execution": "control_plane_only", "gpu_jit_load": False, "connector_required": True}
            return 202, manifest
        if path in {"/ds4/kvcache/commit", "/ds4/kv-cache/commit"}:
            return 200, self.queue.external_kv_commit_shards(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=str(body["service_id"]), object_state=str(body.get("object_state") or "available"), shard_state=str(body.get("shard_state") or "ready_on_ssd"), shard_updates=body.get("shards") or body.get("shard_updates") or ())
        if path in {"/ds4/kvcache/shard/commit", "/ds4/kv-cache/shard/commit", "/ds4/kvcache/shard/archive", "/ds4/kv-cache/shard/archive"}:
            return 200, self._kv_shard_commit(body)
        if path in {"/ds4/kvcache/transition", "/ds4/kv-cache/transition"}:
            return 200, self.queue.external_kv_transition(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=str(body["service_id"]), state=str(body["state"]), shard_state=_optional_str(body.get("shard_state")), metadata=dict(body.get("metadata") or {}))
        if path in {"/ds4/kvcache/pin", "/ds4/kv-cache/pin"}:
            return 200, self.queue.external_kv_pin(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=str(body["service_id"]), delta=1)
        if path in {"/ds4/kvcache/unpin", "/ds4/kv-cache/unpin"}:
            return 200, self.queue.external_kv_pin(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=str(body["service_id"]), delta=-1)
        if path in {"/ds4/kvcache/evict", "/ds4/kv-cache/evict"}:
            return 200, self.queue.external_kv_evict(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=str(body["service_id"]), reason=_optional_str(body.get("reason")))
        return 404, {"error": f"unknown endpoint: {path}"}

    def _handle_openai_chat(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if body.get("stream"):
            return 400, {"error": "stream=true is not implemented in the spark0 coordinator yet"}
        registry = self._registry()
        topology = self._topology()
        profile = _resolve_profile(registry, topology, _optional_str(body.get("model")))
        request_id = str(body.get("request_id") or f"chatcmpl-{uuid.uuid4().hex}")
        batch_id = str(body.get("batch_id") or request_id)
        metadata = dict(body.get("metadata") or {})
        raw_request = _make_inference_request_json(
            request_id=request_id,
            profile=profile,
            chat=True,
            input_payload=_input_with_api_kv({"messages": list(body.get("messages") or []), "metadata": metadata}, body, profile, topology),
            output_contract=_openai_output_contract(body),
            max_tokens=int(body.get("max_completion_tokens") or body.get("max_tokens") or 1024),
            temperature=float(body.get("temperature") or 0.0),
            job_class=str(body.get("ds4_job_class") or metadata.get("job_class") or "analysis"),
            capability=_optional_str(body.get("ds4_capability") or metadata.get("capability")),
        )
        submitted = self.queue.submit_requests(requests=[InferenceRequest.from_json(raw_request)], registry=registry, topology=topology, batch_id=batch_id, priority=_optional_int(body.get("priority")))
        if _is_async_request(body):
            return 202, _async_queue_response("openai_chat", request_id, batch_id, submitted)
        result = self._run_until_collected(batch_id=batch_id, request_id=request_id, timeout_s=float(body.get("ds4_timeout_s") or self.sync_timeout_s))
        return 200, _openai_chat_response(request_id=request_id, model=str(body.get("model") or profile.model_id), result=result)

    def _handle_openai_completion(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        registry = self._registry()
        topology = self._topology()
        profile = _resolve_profile(registry, topology, _optional_str(body.get("model")))
        request_id = str(body.get("request_id") or f"cmpl-{uuid.uuid4().hex}")
        batch_id = str(body.get("batch_id") or request_id)
        prompt = body.get("prompt")
        raw_request = _make_inference_request_json(
            request_id=request_id,
            profile=profile,
            chat=False,
            input_payload=_input_with_api_kv({"prompt": prompt}, body, profile, topology),
            output_contract={"format": "text"},
            max_tokens=int(body.get("max_tokens") or 1024),
            temperature=float(body.get("temperature") or 0.0),
            job_class=str(body.get("ds4_job_class") or "analysis"),
            capability=_optional_str(body.get("ds4_capability")),
        )
        submitted = self.queue.submit_requests(requests=[InferenceRequest.from_json(raw_request)], registry=registry, topology=topology, batch_id=batch_id, priority=_optional_int(body.get("priority")))
        if _is_async_request(body):
            return 202, _async_queue_response("openai_completion", request_id, batch_id, submitted)
        result = self._run_until_collected(batch_id=batch_id, request_id=request_id, timeout_s=float(body.get("ds4_timeout_s") or self.sync_timeout_s))
        return 200, _openai_completion_response(request_id=request_id, model=str(body.get("model") or profile.model_id), result=result)

    def _handle_anthropic_messages(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if body.get("stream"):
            return 400, {"error": "stream=true is not implemented in the spark0 coordinator yet"}
        registry = self._registry()
        topology = self._topology()
        profile = _resolve_profile(registry, topology, _optional_str(body.get("model")))
        request_id = str(body.get("request_id") or f"msg_{uuid.uuid4().hex}")
        batch_id = str(body.get("batch_id") or request_id)
        metadata = dict(body.get("metadata") or {})
        input_payload = _input_with_api_kv({"system": body.get("system"), "messages": list(body.get("messages") or []), "tools": body.get("tools"), "metadata": metadata}, body, profile, topology)
        raw_request = _make_inference_request_json(
            request_id=request_id,
            profile=profile,
            chat=True,
            input_payload=input_payload,
            output_contract={"format": "text"},
            max_tokens=int(body.get("max_tokens") or 1024),
            temperature=float(body.get("temperature") or 0.0),
            job_class=str(body.get("ds4_job_class") or metadata.get("job_class") or "analysis"),
            capability=_optional_str(body.get("ds4_capability") or metadata.get("capability")),
        )
        submitted = self.queue.submit_requests(requests=[InferenceRequest.from_json(raw_request)], registry=registry, topology=topology, batch_id=batch_id, priority=_optional_int(body.get("priority")))
        if _is_async_request(body):
            return 202, _async_queue_response("anthropic_messages", request_id, batch_id, submitted)
        result = self._run_until_collected(batch_id=batch_id, request_id=request_id, timeout_s=float(body.get("ds4_timeout_s") or self.sync_timeout_s))
        return 200, _anthropic_message_response(request_id=request_id, model=str(body.get("model") or profile.model_id), result=result)

    def _kv_declare(self, body: dict[str, Any]) -> dict[str, Any]:
        topology = self._topology()
        registry = self._registry()
        service = _resolve_pipeline_service(topology, registry, body)
        namespace = str(body.get("namespace") or "default")
        kv_key = str(body["kv_key"])
        total_bytes = int(body.get("total_bytes") or body.get("bytes") or 0)
        storage_root = _optional_str(body.get("storage_root") or body.get("cache_root") or service.kv_cache.get("storage_root") or service.kv_cache.get("cache_root"))
        shards = body.get("shards")
        if shards is None:
            shards = service.external_cache_shards(namespace=namespace, kv_key=kv_key, total_bytes=total_bytes, storage_root=storage_root)
        return self.queue.upsert_external_kv_object(
            namespace=namespace,
            kv_key=kv_key,
            service_id=service.service_id,
            profile_id=service.profile_id,
            model_id=service.model_id,
            owner=_optional_str(body.get("owner")),
            content_hash=_optional_str(body.get("content_hash")),
            total_bytes=total_bytes,
            total_tokens=int(body.get("total_tokens") or 0),
            state=str(body.get("state") or "declared"),
            pin_count=int(body.get("pin_count") or (1 if body.get("pinned") else 0)),
            priority=int(body.get("priority") or 100),
            ttl_s=float(body["ttl_s"]) if body.get("ttl_s") is not None else None,
            metadata=dict(body.get("metadata") or {}),
            shards=shards,
        )

    def _kv_shard_commit(self, body: dict[str, Any]) -> dict[str, Any]:
        topology = self._topology()
        registry = self._registry()
        service = _resolve_pipeline_service(topology, registry, body)
        node_id = str(body["node_id"])
        stage_index = _optional_int(body.get("stage_index"))
        if stage_index is None:
            stage_index = service.stage_for_node(node_id).stage_index
        metadata = dict(body.get("metadata") or {})
        if body.get("content_hash") is not None:
            metadata["content_hash"] = str(body["content_hash"])
        if body.get("archive_uri") is not None:
            metadata["archive_uri"] = str(body["archive_uri"])
        metadata.setdefault("archive_owner_node_id", node_id)
        metadata.setdefault("archive_mode", "node_local_shard")
        update: dict[str, Any] = {
            "node_id": node_id,
            "stage_index": stage_index,
            "state": str(body.get("state") or body.get("shard_state") or "ready_on_ssd"),
            "metadata": metadata,
        }
        if body.get("bytes") is not None:
            update["bytes"] = int(body["bytes"])
        if body.get("storage_uri") is not None:
            update["storage_uri"] = str(body["storage_uri"])
        if body.get("gpu_resident") is not None:
            update["gpu_resident"] = bool(body["gpu_resident"])
        return self.queue.external_kv_commit_shards(
            namespace=str(body.get("namespace") or "default"),
            kv_key=str(body["kv_key"]),
            service_id=service.service_id,
            object_state="available",
            shard_state=str(body.get("state") or body.get("shard_state") or "ready_on_ssd"),
            shard_updates=[update],
        )

    def _work_once(self, body: dict[str, Any]) -> dict[str, Any]:
        registry = self._registry()
        topology = self._topology()
        runner = self._runner(topology, timeout_s=int(body.get("timeout_s") or self.sync_timeout_s))
        entry_node_id = str(body.get("node_id") or topology.routing_policy.get("queue_entry_node_id") or "spark0")
        return self.queue.work(
            registry=registry,
            runner=runner,
            node_id=entry_node_id,
            batch_id=_optional_str(body.get("batch_id")),
            limit=int(body.get("limit") or 48),
            concurrency=int(body.get("concurrency") or body.get("limit") or 48),
            worker_id=str(body.get("worker_id") or "spark0-api-pipeline-worker"),
            lease_ttl_s=int(body.get("lease_ttl_s") or 900),
            heartbeat_interval_s=float(body.get("heartbeat_interval_s") or 5.0),
            node_profile_ids=_node_profile_ids(topology, entry_node_id),
            max_node_depth=int(body.get("max_node_depth") or 0),
            batch_linger_s=_body_float(body, "batch_linger_s", 0.05),
            kv_capacity_bytes=int(body.get("kv_capacity_bytes") or 0),
            transport_max_attempts=int(body.get("transport_max_attempts") or self.dispatcher_transport_max_attempts),
            kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
            batch_limits_by_service=_batch_limits_by_service(topology),
            refill_low_watermarks_by_service=_refill_low_watermarks_by_service(topology),
        )

    def _run_until_collected(self, *, batch_id: str, request_id: str, timeout_s: float) -> dict[str, Any]:
        deadline = time.time() + max(0.1, timeout_s)
        idle_sleep = self.poll_interval_s
        while time.time() < deadline:
            status = self.queue.status(batch_id=batch_id)
            state = str(status.get("state") or "")
            if state in {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}:
                return self.queue.collect(request_id=request_id)
            if not self.dispatcher_enabled or self.dispatcher_thread is None:
                self._work_once({"batch_id": batch_id})
            elif not self._dispatcher_is_active():
                return {"request": {"request_id": request_id, "state": "failed"}, "result": {"status": "failed", "error": "coordinator dispatcher is not running"}}
            time.sleep(idle_sleep)
        return {"request": {"request_id": request_id, "state": "failed"}, "result": {"status": "failed", "error": "coordinator sync timeout"}}

    def start_background_dispatcher(self) -> None:
        if not self.dispatcher_enabled:
            return
        if self.dispatcher_thread is not None and self.dispatcher_thread.is_alive():
            return
        self.dispatcher_stop.clear()
        self.dispatcher_thread = threading.Thread(target=self._dispatcher_loop, name="ds4-api-dispatcher", daemon=True)
        self.dispatcher_thread.start()

    def stop_background_dispatcher(self) -> None:
        self.dispatcher_stop.set()
        thread = self.dispatcher_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=10.0)

    def dispatcher_status(self) -> dict[str, Any]:
        with self.dispatcher_lock:
            return dict(self.dispatcher_state)

    def _dispatcher_is_active(self) -> bool:
        return bool(self.dispatcher_enabled and self.dispatcher_thread is not None and self.dispatcher_thread.is_alive())

    def _dispatcher_note(self, **updates: Any) -> None:
        with self.dispatcher_lock:
            self.dispatcher_state.update(updates)

    def _dispatcher_count(self, **increments: int) -> None:
        with self.dispatcher_lock:
            for key, delta in increments.items():
                self.dispatcher_state[key] = int(self.dispatcher_state.get(key) or 0) + int(delta)

    def _dispatcher_loop(self) -> None:
        self._dispatcher_note(running=True, started_at=time.time(), last_error=None)
        try:
            while not self.dispatcher_stop.is_set():
                worked = self._work_once(
                    {
                        "limit": self.dispatcher_window,
                        "concurrency": self.dispatcher_window,
                        "worker_id": "spark0-api-continuous-dispatcher",
                        "lease_ttl_s": self.dispatcher_lease_ttl_s,
                        "heartbeat_interval_s": self.dispatcher_heartbeat_s,
                        "batch_linger_s": self.dispatcher_batch_linger_s,
                        "timeout_s": self.dispatcher_transport_timeout_s,
                        "transport_max_attempts": self.dispatcher_transport_max_attempts,
                    }
                )
                claimed = int(worked.get("claimed_count") or 0)
                self._dispatcher_note(last_summary=worked, last_error=None)
                if claimed:
                    self._dispatcher_note(last_work_at=time.time())
                    self._dispatcher_count(
                        worked_count=1,
                        claimed_count=claimed,
                        completed_count=int(worked.get("completed_count") or 0),
                        failed_count=int(worked.get("failed_count") or 0),
                        retried_count=int(worked.get("retried_count") or 0),
                    )
                else:
                    self._dispatcher_count(idle_count=1)
                    self.dispatcher_stop.wait(self.dispatcher_idle_sleep_s)
        except Exception as exc:
            self._dispatcher_note(last_error=str(exc))
            raise
        finally:
            self._dispatcher_note(running=False)

    def _registry(self) -> ProfileRegistry:
        return ProfileRegistry.load(self.profiles_dir)

    def _topology(self) -> SparkTopology:
        return SparkTopology.load(self.topology_path)

    def _runner(self, topology: SparkTopology, *, timeout_s: int) -> Runner:
        if self.runner_kind == "fake":
            return FakeRunner()
        return PipelineOpenAIRunner(timeout_s=int(timeout_s), base_urls=_pipeline_base_urls(topology))


def serve(*, host: str, port: int, queue_dir: str | Path, profiles_dir: str | Path, topology_path: str | Path, runner_kind: str = "pipeline") -> None:
    api = CoordinatorApi(queue_dir=queue_dir, profiles_dir=profiles_dir, topology_path=topology_path, runner_kind=runner_kind)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            code, payload = api.handle_get(parsed.path, parse_qs(parsed.query))
            _write_json(self, code, payload)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                body = _read_json(self)
                code, payload = api.handle_post(parsed.path, body)
            except Exception as exc:
                code, payload = 400, {"error": str(exc)}
            _write_json(self, code, payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    api.start_background_dispatcher()
    try:
        server.serve_forever()
    finally:
        api.stop_background_dispatcher()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-coordinator-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8700)
    parser.add_argument("--queue-dir", default="/tmp/ds4_v2_queue")
    parser.add_argument("--profiles-dir", default="profiles/models")
    parser.add_argument("--topology", default="profiles/topology/static_sparks.json")
    parser.add_argument("--runner-kind", choices=("pipeline", "fake"), default="pipeline")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, queue_dir=args.queue_dir, profiles_dir=args.profiles_dir, topology_path=args.topology, runner_kind=args.runner_kind)
    return 0


def _make_inference_request_json(
    *,
    request_id: str,
    profile: ModelProfile,
    chat: bool,
    input_payload: dict[str, Any],
    output_contract: dict[str, Any],
    max_tokens: int,
    temperature: float,
    job_class: str,
    capability: str | None,
) -> dict[str, Any]:
    if job_class not in profile.supported_job_classes:
        job_class = "analysis" if "analysis" in profile.supported_job_classes else profile.supported_job_classes[0]
    return {
        "format": REQUEST_FORMAT,
        "request_id": request_id,
        "capability": capability or (profile.capability_classes[0] if profile.capability_classes else None),
        "chat": bool(chat),
        "immediate": False,
        "job_class": job_class,
        "max_output_tokens": max(1, int(max_tokens)),
        "thinking_budget_tokens": 0,
        "temperature": float(temperature),
        "input": input_payload,
        "output_contract": output_contract,
        "model_pin": {"profile_id": profile.profile_id},
        "raw": {},
    }


def _input_with_api_kv(input_payload: dict[str, Any], body: dict[str, Any], profile: ModelProfile, topology: SparkTopology) -> dict[str, Any]:
    out = dict(input_payload)
    openai = {key: body[key] for key in OPENAI_REQUEST_FIELDS if key in body and body[key] is not None}
    if openai:
        out["openai"] = {**dict(out.get("openai") or {}), **openai}
    has_kv_cache = body.get("kv_cache") is not None
    has_external_kv = body.get("external_kv") is not None
    if has_kv_cache and has_external_kv and body.get("kv_cache") != body.get("external_kv"):
        raise ValueError("provide only one of kv_cache or external_kv")
    raw = body.get("kv_cache") if has_kv_cache else body.get("external_kv")
    if raw is None:
        return out
    if not isinstance(raw, dict):
        raise ValueError("kv_cache/external_kv must be an object")
    if raw.get("format") == KV_CACHE_PLAN_FORMAT:
        out["kv_cache_plan"] = dict(raw)
        return out
    if raw.get("format") == KV_CACHE_DIRECTIVE_FORMAT or has_kv_cache:
        directive = dict(raw)
        directive.setdefault("format", KV_CACHE_DIRECTIVE_FORMAT)
        out["kv_cache"] = directive
        out["kv_cache_plan"] = normalize_kv_cache_directive(directive)
        return out
    out["external_kv"] = dict(raw)
    out["kv_cache_plan"] = _external_kv_plan(raw, profile=profile, topology=topology)
    out["kv_cache_key"] = str(raw["kv_key"])
    if raw.get("total_bytes") is not None or raw.get("bytes") is not None:
        out["kv_bytes_estimate"] = int(raw.get("total_bytes") or raw.get("bytes") or 0)
    return out


def _external_kv_plan(raw: dict[str, Any], *, profile: ModelProfile, topology: SparkTopology) -> dict[str, Any]:
    kv_key = str(raw.get("kv_key") or "")
    if not kv_key:
        raise ValueError("external_kv shorthand requires kv_key")
    namespace = str(raw.get("namespace") or "default")
    service_id = _optional_str(raw.get("service_id"))
    if service_id is None:
        service = topology.pipeline_service_for_profile(profile.profile_id)
        service_id = service.service_id if service is not None else None
    load = {
        "mode": str(raw.get("mode") or raw.get("load_mode") or "prefer"),
        "transport": "external_manifest",
        "namespace": namespace,
        "kv_key": kv_key,
        "service_id": service_id,
    }
    if raw.get("lease_id") is not None:
        load["lease_id"] = str(raw["lease_id"])
    if raw.get("content_hash") is not None:
        load["content_hash"] = str(raw["content_hash"])
    plan = {
        "format": KV_CACHE_PLAN_FORMAT,
        "backend": str(raw.get("backend") or "auto"),
        "cache_id": kv_key,
        "prefix_hash": _optional_str(raw.get("prefix_hash")),
        "load": load,
        "store": {"mode": "skip", "transport": "none"},
        "miss_policy": str(raw.get("miss_policy") or "compute"),
        "route_affinity": str(raw.get("route_affinity") or "required"),
        "model_fingerprint": dict(raw.get("model_fingerprint") or {}),
        "operation": "load",
    }
    plan["batch_key_hash"] = "sha256:" + hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return plan


def _openai_output_contract(body: dict[str, Any]) -> dict[str, Any]:
    response_format = body.get("response_format")
    if isinstance(response_format, dict):
        if response_format.get("type") == "json_schema":
            return {"format": "json_schema", "schema": response_format.get("json_schema")}
        if response_format.get("type") == "json_object":
            return {"format": "json_object"}
    return {"format": "text"}


def _openai_models(registry: ProfileRegistry, topology: SparkTopology) -> dict[str, Any]:
    seen: set[str] = set()
    data: list[dict[str, Any]] = []
    for service in topology.pipeline_services.values():
        for model_id in (service.service_id, service.model_id, service.profile_id):
            if model_id in seen:
                continue
            seen.add(model_id)
            data.append({"id": model_id, "object": "model", "owned_by": "ds4", "ds4_service_id": service.service_id, "ds4_profile_id": service.profile_id})
    for profile in registry.all_profiles():
        if profile.profile_id in seen:
            continue
        seen.add(profile.profile_id)
        data.append({"id": profile.profile_id, "object": "model", "owned_by": "ds4", "ds4_profile_id": profile.profile_id})
    return {"object": "list", "data": data}


def _resolve_profile(registry: ProfileRegistry, topology: SparkTopology, model: str | None) -> ModelProfile:
    if model:
        try:
            return registry.get(model)
        except ValueError:
            pass
        for service in topology.pipeline_services.values():
            if model in {service.service_id, service.model_id, service.profile_id}:
                return registry.get(service.profile_id)
        matches = [profile for profile in registry.all_profiles() if profile.model_id == model]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            prod = [profile for profile in matches if profile.production_eligible]
            return sorted(prod or matches, key=lambda profile: int(profile.routing.get("rank", 1000)))[0]
        raise ValueError(f"unknown model/profile/service: {model}")
    return registry.resolve(capability="efficient", chat=True, job_class="analysis", model_pin=None)


def _resolve_pipeline_service(topology: SparkTopology, registry: ProfileRegistry, body: dict[str, Any]):
    service_id = _optional_str(body.get("service_id"))
    if service_id:
        return topology.pipeline_service_by_id(service_id)
    profile_id = _optional_str(body.get("profile_id"))
    if profile_id:
        service = topology.pipeline_service_for_profile(profile_id)
        if service is None:
            raise ValueError(f"profile {profile_id!r} is not a pipeline service")
        return service
    model_id = _optional_str(body.get("model_id") or body.get("model"))
    if model_id:
        for service in topology.pipeline_services.values():
            if model_id in {service.model_id, service.service_id, service.profile_id}:
                return service
        profile = _resolve_profile(registry, topology, model_id)
        service = topology.pipeline_service_for_profile(profile.profile_id)
        if service is not None:
            return service
    default_service = topology.pipeline_service_for_profile(registry.resolve(capability="efficient", chat=True, job_class="analysis").profile_id)
    if default_service is None:
        raise ValueError("no default pipeline service is configured")
    return default_service


OPENAI_REQUEST_FIELDS = {
    "ignore_eos",
    "include_stop_str_in_output",
    "min_tokens",
    "repetition_penalty",
    "seed",
    "skip_special_tokens",
    "stop",
    "stop_token_ids",
    "top_k",
    "top_p",
    "truncate_prompt_tokens",
}


def _openai_chat_response(*, request_id: str, model: str, result: dict[str, Any]) -> dict[str, Any]:
    text, status = _result_text_and_status(result)
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop" if status == "completed" else "error"}],
        "usage": _result_usage(result),
        "ds4": {"request": result.get("request"), "status": status},
    }


def _openai_completion_response(*, request_id: str, model: str, result: dict[str, Any]) -> dict[str, Any]:
    text, status = _result_text_and_status(result)
    return {
        "id": request_id,
        "object": "text_completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "text": text, "finish_reason": "stop" if status == "completed" else "error"}],
        "usage": _result_usage(result),
        "ds4": {"request": result.get("request"), "status": status},
    }


def _anthropic_message_response(*, request_id: str, model: str, result: dict[str, Any]) -> dict[str, Any]:
    text, status = _result_text_and_status(result)
    return {
        "id": request_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn" if status == "completed" else "error",
        "stop_sequence": None,
        "usage": _anthropic_usage(result),
        "ds4": {"request": result.get("request"), "status": status},
    }


def _result_text_and_status(result: dict[str, Any]) -> tuple[str, str]:
    body = result.get("result") if isinstance(result.get("result"), dict) else {}
    status = str(body.get("status") or result.get("request", {}).get("state") or "unknown")
    output = body.get("output") if isinstance(body.get("output"), dict) else {}
    text = str(output.get("text") if output.get("text") is not None else body.get("error") or body.get("status") or "")
    return text, status


def _result_usage(result: dict[str, Any]) -> dict[str, int]:
    body = result.get("result") if isinstance(result.get("result"), dict) else {}
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return {"prompt_tokens": int(usage.get("input_tokens", 0) or 0), "completion_tokens": int(usage.get("output_tokens", 0) or 0), "total_tokens": int(usage.get("total_tokens", 0) or 0)}


def _anthropic_usage(result: dict[str, Any]) -> dict[str, int]:
    usage = _result_usage(result)
    return {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]}


def _async_queue_response(kind: str, request_id: str, batch_id: str, submitted: dict[str, Any]) -> dict[str, Any]:
    return {"format": "ds4-async-api-response-v1", "api": kind, "request_id": request_id, "batch_id": batch_id, "job_id": batch_id, "queue": submitted}


def _is_async_request(body: dict[str, Any]) -> bool:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    extra_body = body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}
    return bool(body.get("ds4_async") or metadata.get("ds4_async") or extra_body.get("ds4_async"))


def _pipeline_telemetry_with_topology(report: dict[str, Any], topology: SparkTopology) -> dict[str, Any]:
    normalized = dict(report)
    if isinstance(normalized.get("stages"), list):
        base = {key: value for key, value in normalized.items() if key != "stages"}
        stages = []
        for item in normalized["stages"]:
            if not isinstance(item, dict):
                raise ValueError("pipeline telemetry stages must be objects")
            merged = dict(base)
            merged.update(item)
            stages.append(_pipeline_telemetry_with_topology(merged, topology))
        normalized["stages"] = stages
        return normalized
    service = _telemetry_service(topology, normalized)
    if service is None:
        return normalized
    normalized.setdefault("service_id", service.service_id)
    normalized.setdefault("profile_id", service.profile_id)
    normalized.setdefault("stage_count", service.pipeline_parallel_size)
    stage = None
    if normalized.get("node_id") is not None:
        stage = service.stage_for_node(str(normalized["node_id"]))
    elif normalized.get("stage_index") is not None:
        stage = service.stage_for_index(int(normalized["stage_index"]))
        normalized.setdefault("node_id", stage.node_id)
    if stage is not None:
        normalized.setdefault("node_id", stage.node_id)
        normalized.setdefault("stage_index", stage.stage_index)
        normalized.setdefault("stage_count", stage.stage_count)
        normalized.setdefault("layer_start", stage.layer_start)
        normalized.setdefault("layer_end", stage.layer_end)
    return normalized


def _telemetry_service(topology: SparkTopology, report: dict[str, Any]):
    if report.get("service_id") is not None:
        return topology.pipeline_service_by_id(str(report["service_id"]))
    if report.get("profile_id") is not None:
        service = topology.pipeline_service_for_profile(str(report["profile_id"]))
        if service is None:
            raise ValueError(f"profile {report['profile_id']!r} is not a pipeline service")
        return service
    if report.get("model_id") is not None:
        matches = [service for service in topology.pipeline_services.values() if service.model_id == str(report["model_id"])]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"model {report['model_id']!r} is not a pipeline service")
        raise ValueError(f"model {report['model_id']!r} maps to multiple pipeline services; pass service_id")
    return None


def _pipeline_base_urls(topology: SparkTopology) -> dict[str, str]:
    urls: dict[str, str] = {}
    for service in topology.pipeline_services.values():
        urls[service.profile_id] = service.api_base_url
        urls[service.model_id] = service.api_base_url
        urls[service.service_id] = service.api_base_url
    return urls


def _batch_limits_by_service(topology: SparkTopology) -> dict[str, int]:
    return {service.service_id: int(service.scheduler.get("queue_limit") or service.max_batch_size) for service in topology.pipeline_services.values()}


def _refill_low_watermarks_by_service(topology: SparkTopology) -> dict[str, int]:
    return {service.service_id: int(service.scheduler.get("refill_low_watermark") or 0) for service in topology.pipeline_services.values()}


def _node_profile_ids(topology: SparkTopology, node_id: str) -> tuple[str, ...]:
    profile_ids: set[str] = set()
    for node in topology.nodes:
        if node.node_id == node_id:
            profile_ids.update(node.resident_profiles)
            break
    for service in topology.pipeline_profiles_for_node(node_id):
        profile_ids.add(service.profile_id)
    return tuple(sorted(profile_ids))


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length") or 0)
    if length <= 0:
        return {}
    data = handler.rfile.read(length)
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _write_json(handler: BaseHTTPRequestHandler, code: int, payload: dict[str, Any]) -> None:
    body = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    handler.send_response(code)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _one(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _required_query(query: dict[str, list[str]], key: str) -> str:
    value = _one(query, key)
    if value is None:
        raise ValueError(f"query parameter {key!r} is required")
    return value


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _body_float(body: dict[str, Any], key: str, default: float) -> float:
    if key not in body or body.get(key) is None:
        return float(default)
    return float(body[key])


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return int(default)
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return float(default)
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
