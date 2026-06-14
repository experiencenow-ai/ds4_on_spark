from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
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

from .api_chat_render import anthropic_messages_input_payload, openai_chat_input_payload
from .api_stream import openai_chat_stream_events, openai_completion_requests, openai_completion_stream_events, write_sse
from .builders import MODEL_ALIASES, resolve_model_alias
from .dispatcher_resident import PendingDispatcherCohort, ResidentServicePlan
from .dispatcher_resident import active_resident_service_ids as _active_resident_service_ids
from .dispatcher_resident import pending_claim_count as _pending_claim_count
from .dispatcher_resident import pending_claim_count_by_service as _pending_claim_count_by_service
from .dispatcher_resident import pending_cohort_details as _pending_cohort_details
from .dispatcher_resident import pending_claims as _pending_claims
from .dispatcher_resident import pending_cohort as _pending_cohort
from .dispatcher_resident import plan_uses_rolling_admission as _plan_uses_rolling_admission
from .dispatcher_resident import resident_service_order as _resident_service_order
from .dispatcher_resident import resident_service_plans as _resident_service_plans
from .dispatcher_resident import service_target_active as _service_target_active
from .deployment import deployment_readiness
from .env_utils import env_bool as _env_bool
from .jit_kv import JitKvCircuitBreaker
from .pipelines import pipeline_service_batch_limit
from .profiles import ModelProfile, ProfileRegistry
from .kv_cache import KV_CACHE_DIRECTIVE_FORMAT, KV_CACHE_PLAN_FORMAT, normalize_kv_cache_directive
from .resource_governor import GpuResourceGovernor, topology_governor_nodes
from .runners import FakeRunner, PipelineOpenAIRunner, Runner
from .queue import InferenceQueue, QueueClaim
from .schemas import InferenceRequest, REQUEST_FORMAT
from .topology import SparkTopology
from .worker import BatchWorker


@dataclass
class DispatcherRuntime:
    worker: BatchWorker
    executor: ThreadPoolExecutor
    pending: dict[Any, Any]
    entry_node_id: str
    node_profile_ids: tuple[str, ...]
    batch_limits_by_service: dict[str, int]
    kv_shard_layouts_by_profile: dict[str, Any]
    service_plans: dict[str, Any]
    next_heartbeat_at: float
    last_credit_at: float


API_TERMINAL_STATES = {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}


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
        self.dispatcher_resident_multimodel = _env_bool("DS4_API_RESIDENT_MULTIMODEL", True)
        topology_default_window = _topology_dispatch_window(self.topology_path)
        self.dispatcher_window = max(1, _env_int("DS4_API_DISPATCH_WINDOW", topology_default_window))
        self.dispatcher_refill_batch = max(1, _env_int("DS4_API_DISPATCH_REFILL_BATCH", self.dispatcher_window))
        self.dispatcher_cohort_workers = max(1, _env_int("DS4_API_DISPATCH_COHORT_WORKERS", _topology_dispatch_cohort_workers(self.topology_path)))
        self.dispatcher_idle_sleep_s = max(0.001, _env_float("DS4_API_DISPATCH_IDLE_SLEEP_S", 0.005))
        self.dispatcher_batch_linger_s = max(0.0, _env_float("DS4_API_DISPATCH_BATCH_LINGER_S", 0.03))
        self.dispatcher_lease_ttl_s = max(1, _env_int("DS4_API_DISPATCH_LEASE_TTL_S", 900))
        self.dispatcher_heartbeat_s = max(0.25, _env_float("DS4_API_DISPATCH_HEARTBEAT_S", 2.0))
        self.dispatcher_transport_timeout_s = max(1, _env_int("DS4_API_TRANSPORT_TIMEOUT_S", 3600))
        self.dispatcher_transport_max_attempts = max(1, _env_int("DS4_API_TRANSPORT_MAX_ATTEMPTS", 1))
        self.dispatcher_kv_capacity_bytes = max(0, _env_int("DS4_API_DISPATCH_KV_CAPACITY_BYTES", 0))
        topology = self._topology()
        active_service_ids = _active_resident_service_ids(topology)
        entry_node_id = str(topology.routing_policy.get("queue_entry_node_id") or "spark0")
        self.dispatcher_resource_governor = GpuResourceGovernor.from_env(nodes=topology_governor_nodes(topology, active_service_ids=active_service_ids), local_node_id=entry_node_id)
        self.jit_kv_circuit = JitKvCircuitBreaker(
            enabled=_env_bool("DS4_API_JIT_KV_CIRCUIT_BREAKER", True),
            window_s=_env_float("DS4_API_JIT_KV_CIRCUIT_WINDOW_S", 60.0),
            min_samples=_env_int("DS4_API_JIT_KV_CIRCUIT_MIN_SAMPLES", 8),
            failure_ratio=_env_float("DS4_API_JIT_KV_CIRCUIT_FAILURE_RATIO", 0.5),
            cooldown_s=_env_float("DS4_API_JIT_KV_CIRCUIT_COOLDOWN_S", 120.0),
        )
        self.jit_kv_startup_recovery: dict[str, Any] = {"wait_released": 0, "objects_recovered": 0, "shards_recovered": 0}
        self._jit_kv_last_gate_open_until = 0.0
        self.dispatcher_stop = threading.Event()
        self.dispatcher_thread: threading.Thread | None = None
        self.dispatcher_lock = threading.Lock()
        self.dispatcher_state: dict[str, Any] = self._initial_dispatcher_state()
        if _env_bool("DS4_API_JIT_KV_RECOVER_ON_STARTUP", True):
            self.jit_kv_startup_recovery = self.queue.recover_jit_kv_startup(stale_s=_env_float("DS4_API_JIT_KV_RECOVERY_STALE_S", 0.0))

    def handle_get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        if path in {"/health", "/ds4/health"}:
            return 200, {"ok": True, "service": "ds4-coordinator-api", "entry_node_id": self._topology().routing_policy.get("queue_entry_node_id", "spark0"), "dispatcher": self.dispatcher_status()}
        if path == "/v1/models":
            return 200, _openai_models(self._registry(), self._topology())
        if path == "/ds4/dispatcher/status":
            return 200, self.dispatcher_status()
        if path in {"/ds4/deployment/readiness", "/ds4/deploy/readiness"}:
            payload = deployment_readiness(
                topology=self._topology(),
                dispatcher_window=self.dispatcher_window,
                dispatcher_refill_batch=self.dispatcher_refill_batch,
                dispatcher_cohort_workers=self.dispatcher_cohort_workers,
                resident_multimodel=self.dispatcher_resident_multimodel,
            )
            return (200 if payload["ready"] else 503), payload
        if path == "/ds4/queue/status":
            return 200, self.queue.status(request_id=_one(query, "request_id"), batch_id=_one(query, "batch_id"), job_id=_one(query, "job_id"), refresh=_query_bool(query, "refresh", False))
        if path == "/ds4/queue/usage":
            return 200, self.queue.usage(window_s=_query_float(query, "window_s", 300.0))
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
            requests = [InferenceRequest.from_json(_prepare_queue_request_json(item)) for item in raw_requests]
            return 200, self.queue.submit_requests(requests=requests, registry=self._registry(), topology=self._topology(), batch_id=_optional_str(body.get("batch_id")), priority=_optional_int(body.get("priority")))
        if path == "/ds4/queue/work":
            return 200, self._work_once(body)
        if path == "/ds4/queue/cancel":
            return 200, self.queue.cancel(request_id=_optional_str(body.get("request_id")), batch_id=_optional_str(body.get("batch_id")), job_id=_optional_str(body.get("job_id")), reason=str(body.get("reason") or "cancelled by operator"), force_running=bool(body.get("force_running")))
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
            metadata = {"prefetch": dict(body), "execution": "control_plane_only"}
            try:
                contract = self._topology().pipeline_service_by_id(service_id).kv_cache_contract()
                metadata.setdefault("kv_cache_contract", contract)
                metadata.setdefault("layer_partition_fingerprint", contract["fingerprint"])
            except ValueError:
                pass
            manifest = self.queue.external_kv_transition(namespace=str(body.get("namespace") or "default"), kv_key=str(body["kv_key"]), service_id=service_id, state="prefetch_requested", shard_state="prefetch_requested", metadata=metadata)
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
        registry = self._registry()
        topology = self._topology()
        profile = _resolve_profile(registry, topology, _optional_str(body.get("model")))
        request_id = str(body.get("request_id") or f"chatcmpl-{uuid.uuid4().hex}")
        batch_id = str(body.get("batch_id") or request_id)
        metadata = dict(body.get("metadata") or {})
        thinking_budget = _thinking_budget_tokens(body, metadata)
        input_payload = openai_chat_input_payload(body, profile=profile, metadata=metadata, thinking_budget_tokens=thinking_budget)
        raw_request = _make_inference_request_json(
            request_id=request_id,
            profile=profile,
            chat=True,
            input_payload=_input_with_api_kv(input_payload, body, profile, topology),
            output_contract=_openai_output_contract(body),
            max_tokens=int(body.get("max_completion_tokens") or body.get("max_tokens") or 1024),
            temperature=float(body.get("temperature") or 0.0),
            job_class=str(body.get("ds4_job_class") or metadata.get("job_class") or "analysis"),
            capability=_optional_str(body.get("ds4_capability") or metadata.get("capability")),
            thinking_budget_tokens=thinking_budget,
        )
        submitted = self.queue.submit_requests(requests=[InferenceRequest.from_json(raw_request)], registry=registry, topology=topology, batch_id=batch_id, priority=_optional_int(body.get("priority")))
        if _is_async_request(body):
            return 202, _async_queue_response("openai_chat", request_id, batch_id, submitted)
        result = self._run_until_collected(batch_id=batch_id, request_id=request_id, timeout_s=float(body.get("ds4_timeout_s") or self.sync_timeout_s))
        error = _openai_result_error(result)
        if error is not None:
            return 502, error
        return 200, _openai_chat_response(request_id=request_id, model=str(body.get("model") or profile.model_id), result=result)

    def _handle_openai_completion(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        registry = self._registry()
        topology = self._topology()
        profile, base_request_id, batch_id, requests = openai_completion_requests(body, registry, topology)
        submitted = self.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id=batch_id, priority=_optional_int(body.get("priority")))
        if _is_async_request(body):
            response = _async_queue_response("openai_completion", base_request_id, batch_id, submitted)
            response["request_ids"] = [request.request_id for request in requests]
            return 202, response
        if body.get("stream"):
            return 400, {"error": "stream=true must be handled by the streaming response path"}
        timeout_s = float(body.get("ds4_timeout_s") or self.sync_timeout_s)
        if len(requests) == 1:
            result = self._run_until_collected(batch_id=batch_id, request_id=requests[0].request_id, timeout_s=timeout_s)
            error = _openai_result_error(result)
            if error is not None:
                return 502, error
            return 200, _openai_completion_response(request_id=requests[0].request_id, model=str(body.get("model") or profile.model_id), result=result)
        result = self._run_batch_until_collected(batch_id=batch_id, timeout_s=timeout_s)
        error = _openai_batch_error(result)
        if error is not None:
            return 502, error
        return 200, _openai_completion_batch_response(request_id=base_request_id, model=str(body.get("model") or profile.model_id), result=result)

    def _handle_anthropic_messages(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if body.get("stream"):
            return 400, {"error": "stream=true is not implemented in the spark0 coordinator yet"}
        registry = self._registry()
        topology = self._topology()
        profile = _resolve_profile(registry, topology, _optional_str(body.get("model")))
        request_id = str(body.get("request_id") or f"msg_{uuid.uuid4().hex}")
        batch_id = str(body.get("batch_id") or request_id)
        metadata = dict(body.get("metadata") or {})
        thinking_budget = _thinking_budget_tokens(body, metadata)
        input_payload = anthropic_messages_input_payload(body, profile=profile, metadata=metadata, thinking_budget_tokens=thinking_budget)
        raw_request = _make_inference_request_json(
            request_id=request_id,
            profile=profile,
            chat=True,
            input_payload=_input_with_api_kv(input_payload, body, profile, topology),
            output_contract={"format": "text"},
            max_tokens=int(body.get("max_tokens") or 1024),
            temperature=float(body.get("temperature") or 0.0),
            job_class=str(body.get("ds4_job_class") or metadata.get("job_class") or "analysis"),
            capability=_optional_str(body.get("ds4_capability") or metadata.get("capability")),
            thinking_budget_tokens=thinking_budget,
        )
        submitted = self.queue.submit_requests(requests=[InferenceRequest.from_json(raw_request)], registry=registry, topology=topology, batch_id=batch_id, priority=_optional_int(body.get("priority")))
        if _is_async_request(body):
            return 202, _async_queue_response("anthropic_messages", request_id, batch_id, submitted)
        result = self._run_until_collected(batch_id=batch_id, request_id=request_id, timeout_s=float(body.get("ds4_timeout_s") or self.sync_timeout_s))
        error = _openai_result_error(result)
        if error is not None:
            return 502, error
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
        metadata = dict(body.get("metadata") or {})
        contract = service.kv_cache_contract()
        metadata.setdefault("kv_cache_contract", contract)
        metadata.setdefault("layer_partition_fingerprint", contract["fingerprint"])
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
            metadata=metadata,
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
        contract = service.kv_cache_contract()
        metadata.setdefault("kv_cache_contract", contract)
        metadata.setdefault("layer_partition_fingerprint", contract["fingerprint"])
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
        limit = int(body.get("limit") or self.dispatcher_refill_batch or self.dispatcher_window)
        concurrency = int(body.get("concurrency") or body.get("limit") or limit)
        return self.queue.work(
            registry=registry,
            runner=runner,
            node_id=entry_node_id,
            batch_id=_optional_str(body.get("batch_id")),
            limit=limit,
            concurrency=concurrency,
            worker_id=str(body.get("worker_id") or "spark0-api-pipeline-worker"),
            lease_ttl_s=int(body.get("lease_ttl_s") or 900),
            heartbeat_interval_s=float(body.get("heartbeat_interval_s") or 5.0),
            node_profile_ids=_node_profile_ids(topology, entry_node_id),
            max_node_depth=int(body.get("max_node_depth") or 0),
            batch_linger_s=_body_float(body, "batch_linger_s", self.dispatcher_batch_linger_s),
            kv_capacity_bytes=int(body.get("kv_capacity_bytes") or self.dispatcher_kv_capacity_bytes),
            transport_max_attempts=int(body.get("transport_max_attempts") or self.dispatcher_transport_max_attempts),
            kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
            batch_limits_by_service=_batch_limits_by_service(topology),
            refill_low_watermarks_by_service=_refill_low_watermarks_by_service(topology),
        )

    def _run_until_collected(self, *, batch_id: str, request_id: str, timeout_s: float) -> dict[str, Any]:
        deadline = time.time() + max(0.1, timeout_s)
        idle_sleep = self.poll_interval_s
        while time.time() < deadline:
            status = self.queue.status(batch_id=batch_id, refresh=False)
            state = str(status.get("state") or "")
            if state in {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}:
                return self.queue.collect(request_id=request_id)
            if not self.dispatcher_enabled or self.dispatcher_thread is None:
                self._work_once({"batch_id": batch_id})
            elif not self._dispatcher_is_active():
                return {"request": {"request_id": request_id, "state": "failed"}, "result": {"status": "failed", "error": "coordinator dispatcher is not running"}}
            time.sleep(idle_sleep)
        return {"request": {"request_id": request_id, "state": "failed"}, "result": {"status": "failed", "error": "coordinator sync timeout"}}

    def _run_batch_until_collected(self, *, batch_id: str, timeout_s: float) -> dict[str, Any]:
        deadline = time.time() + max(0.1, timeout_s)
        idle_sleep = self.poll_interval_s
        while time.time() < deadline:
            status = self.queue.status(batch_id=batch_id, refresh=False)
            state = str(status.get("state") or "")
            if state in {"completed", "completed_with_failures", "completed_with_cancelled", "cancelled", "failed"}:
                return self.queue.collect(batch_id=batch_id)
            if not self.dispatcher_enabled or self.dispatcher_thread is None:
                self._work_once({"batch_id": batch_id})
            elif not self._dispatcher_is_active():
                return {"format": "ds4-inference-queue-v1", "batch_id": batch_id, "state": "failed", "results": [], "error": "coordinator dispatcher is not running"}
            time.sleep(idle_sleep)
        return {"format": "ds4-inference-queue-v1", "batch_id": batch_id, "state": "failed", "results": [], "error": "coordinator sync timeout"}

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
            state = dict(self.dispatcher_state)
        try:
            queue_status = self.queue.status(refresh=False)
            service_counts = self.queue.service_state_counts()
            state["queue_state_counts"] = dict(queue_status.get("state_counts") or {})
            state["queue_state_counts_by_service"] = dict(service_counts.get("state_counts_by_service") or {})
            state["queue_unfinished_by_service"] = dict(service_counts.get("unfinished_by_service") or {})
            state["queue_running_by_service"] = dict(service_counts.get("running_by_service") or {})
            state["queue_status_newest_event_id"] = int(queue_status.get("newest_event_id") or 0)
        except Exception as exc:
            state["queue_status_error"] = str(exc)
        state.update(self.jit_kv_circuit.status())
        state["jit_kv_startup_recovery"] = dict(self.jit_kv_startup_recovery)
        return state

    def _dispatcher_is_active(self) -> bool:
        return bool(self.dispatcher_enabled and self.dispatcher_thread is not None and self.dispatcher_thread.is_alive())

    def _initial_dispatcher_state(self) -> dict[str, Any]:
        return {
            "enabled": self.dispatcher_enabled,
            "running": False,
            "window": self.dispatcher_window,
            "refill_batch": self.dispatcher_refill_batch,
            "cohort_workers": self.dispatcher_cohort_workers,
            "resident_multimodel": self.dispatcher_resident_multimodel,
            "pending": 0,
            "pending_cohorts": 0,
            "pending_by_service": {},
            "pending_cohort_details": [],
            "started_at": None,
            "last_work_at": None,
            "last_error": None,
            "worked_count": 0,
            "claimed_count": 0,
            "submitted_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "retried_count": 0,
            "requeued_count": 0,
            "idle_count": 0,
            "resource_governor_throttle_count": 0,
            "transport_timeout_s": self.dispatcher_transport_timeout_s,
            "transport_max_attempts": self.dispatcher_transport_max_attempts,
            "kv_capacity_bytes": self.dispatcher_kv_capacity_bytes,
            "kv_admission_unlimited": self.dispatcher_kv_capacity_bytes <= 0,
            "kv_admission_warning": "unlimited_kv_admission" if self.dispatcher_kv_capacity_bytes <= 0 else None,
            "auto_kv_cache_enabled": _env_bool("DS4_PIPELINE_AUTO_KV_CACHE", False),
            "auto_kv_cache_service_ids": sorted(_csv_env("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")),
            "resource_governor": self.dispatcher_resource_governor.status(),
            "last_summary": None,
            "last_claimed_cohort_size": 0,
            "largest_claimed_cohort_size": 0,
            "last_claimed_service_id": None,
            "last_claimed_cohort_by_service": {},
            "jit_kv_startup_recovery": dict(self.jit_kv_startup_recovery),
            **self.jit_kv_circuit.status(),
        }

    def _dispatcher_note(self, **updates: Any) -> None:
        with self.dispatcher_lock:
            self.dispatcher_state.update(updates)

    def _dispatcher_count(self, **increments: int) -> None:
        with self.dispatcher_lock:
            for key, delta in increments.items():
                self.dispatcher_state[key] = int(self.dispatcher_state.get(key) or 0) + int(delta)

    def _dispatcher_loop(self) -> None:
        self._dispatcher_note(running=True, started_at=time.time(), last_error=None)
        runtime = self._dispatcher_runtime()
        try:
            while not self.dispatcher_stop.is_set():
                progressed = self._dispatcher_tick(runtime)
                if progressed:
                    continue
                wait_s = self._dispatcher_wait_s()
                if runtime.pending:
                    done, _ = wait(list(runtime.pending.keys()), timeout=wait_s, return_when=FIRST_COMPLETED)
                    if done:
                        continue
                else:
                    self._dispatcher_count(idle_count=1)
                    self.dispatcher_stop.wait(wait_s)
        except Exception as exc:
            self._dispatcher_note(last_error=str(exc))
            raise
        finally:
            self._dispatcher_shutdown(runtime)

    def _dispatcher_runtime(self) -> DispatcherRuntime:
        topology = self._topology()
        registry = self._registry()
        runner = self._runner(topology, timeout_s=self.dispatcher_transport_timeout_s)
        worker = BatchWorker(
            queue=self.queue,
            registry=registry,
            runner=runner,
            worker_id="spark0-api-continuous-dispatcher",
            lease_ttl_s=self.dispatcher_lease_ttl_s,
            heartbeat_interval_s=self.dispatcher_heartbeat_s,
            transport_max_attempts=self.dispatcher_transport_max_attempts,
        )
        entry_node_id = str(topology.routing_policy.get("queue_entry_node_id") or "spark0")
        return DispatcherRuntime(
            worker=worker,
            executor=ThreadPoolExecutor(max_workers=self.dispatcher_cohort_workers, thread_name_prefix="ds4-vllm-cohort"),
            pending={},
            entry_node_id=entry_node_id,
            node_profile_ids=_node_profile_ids(topology, entry_node_id),
            batch_limits_by_service=_batch_limits_by_service(topology),
            kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
            service_plans=_resident_service_plans(topology, entry_node_id=entry_node_id, default_batch_linger_s=self.dispatcher_batch_linger_s),
            next_heartbeat_at=time.time() + self.dispatcher_heartbeat_s,
            last_credit_at=time.time(),
        )

    def _dispatcher_tick(self, runtime: DispatcherRuntime) -> bool:
        completed, failed, retried = self._dispatcher_finish_done(runtime.worker, runtime.pending, block=False)
        if completed or failed or retried:
            self._dispatcher_count(completed_count=completed, failed_count=failed, retried_count=retried, requeued_count=retried)
        self._release_jit_kv_waits_if_circuit_open()
        now = time.time()
        elapsed = max(0.0, now - runtime.last_credit_at)
        for plan in runtime.service_plans.values():
            plan.credit(elapsed)
        runtime.last_credit_at = now
        if runtime.pending and now >= runtime.next_heartbeat_at:
            runtime.worker._heartbeat(_pending_claims(runtime.pending))
            runtime.next_heartbeat_at = now + self.dispatcher_heartbeat_s
        submitted = self._dispatcher_refill(
            worker=runtime.worker,
            executor=runtime.executor,
            pending=runtime.pending,
            entry_node_id=runtime.entry_node_id,
            node_profile_ids=runtime.node_profile_ids,
            batch_limits_by_service=runtime.batch_limits_by_service,
            kv_shard_layouts_by_profile=runtime.kv_shard_layouts_by_profile,
            service_plans=runtime.service_plans,
        )
        if submitted:
            self._dispatcher_count(worked_count=1, claimed_count=submitted, submitted_count=submitted)
            self._dispatcher_note(last_work_at=time.time(), pending=_pending_claim_count(runtime.pending), pending_cohorts=len(runtime.pending), pending_cohort_details=_pending_cohort_details(runtime.pending), last_error=None)
            return True
        self._dispatcher_note(pending=_pending_claim_count(runtime.pending), pending_cohorts=len(runtime.pending), pending_cohort_details=_pending_cohort_details(runtime.pending), last_error=None)
        return bool(completed or failed or retried)

    def _dispatcher_shutdown(self, runtime: DispatcherRuntime) -> None:
        self.dispatcher_stop.set()
        while runtime.pending:
            completed, failed, retried = self._dispatcher_finish_done(runtime.worker, runtime.pending, block=True)
            self._dispatcher_count(completed_count=completed, failed_count=failed, retried_count=retried, requeued_count=retried)
        runtime.executor.shutdown(wait=True, cancel_futures=False)
        self._dispatcher_note(running=False, pending=0, pending_cohorts=0, pending_cohort_details=[])

    def _release_jit_kv_waits_if_circuit_open(self) -> None:
        status = self.jit_kv_circuit.status()
        open_until = status.get("jit_kv_circuit_open_until")
        if open_until is None:
            return
        open_until_f = float(open_until)
        if open_until_f == self._jit_kv_last_gate_open_until:
            return
        released = self.queue.release_jit_kv_waits(reason="jit_kv_circuit_open")
        count = int(released.get("wait_released") or 0)
        self.jit_kv_circuit.record_gate_release(count)
        self._jit_kv_last_gate_open_until = open_until_f
        self._dispatcher_note(jit_kv_last_gate_release=released)

    def _dispatcher_refill(
        self,
        *,
        worker: BatchWorker,
        executor: ThreadPoolExecutor,
        pending: dict[Any, Any],
        entry_node_id: str,
        node_profile_ids: tuple[str, ...],
        batch_limits_by_service: dict[str, int],
        kv_shard_layouts_by_profile: dict[str, Any],
        service_plans: dict[str, ResidentServicePlan] | None = None,
    ) -> int:
        if not self._dispatcher_resource_allows_refill():
            return 0
        service_plans = service_plans or {}
        if self.dispatcher_resident_multimodel and service_plans:
            return self._dispatcher_refill_resident_multimodel(
                worker=worker,
                executor=executor,
                pending=pending,
                entry_node_id=entry_node_id,
                node_profile_ids=node_profile_ids,
                batch_limits_by_service=batch_limits_by_service,
                kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
                service_plans=service_plans,
            )
        return self._dispatcher_refill_exclusive(
            worker=worker,
            executor=executor,
            pending=pending,
            entry_node_id=entry_node_id,
            node_profile_ids=node_profile_ids,
            batch_limits_by_service=batch_limits_by_service,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
        )

    def _dispatcher_resource_allows_refill(self) -> bool:
        decision = self.dispatcher_resource_governor.before_refill()
        self._dispatcher_note(resource_governor=decision.status)
        if decision.allow_refill:
            return True
        self._dispatcher_count(resource_governor_throttle_count=1)
        return False

    def _dispatcher_wait_s(self) -> float:
        remaining = self.dispatcher_resource_governor.cooldown_remaining_s()
        if remaining <= 0.0:
            return self.dispatcher_idle_sleep_s
        return max(self.dispatcher_idle_sleep_s, min(remaining, max(self.dispatcher_idle_sleep_s, 1.0)))

    def _dispatcher_refill_exclusive(
        self,
        *,
        worker: BatchWorker,
        executor: ThreadPoolExecutor,
        pending: dict[Any, Any],
        entry_node_id: str,
        node_profile_ids: tuple[str, ...],
        batch_limits_by_service: dict[str, int],
        kv_shard_layouts_by_profile: dict[str, Any],
    ) -> int:
        available = self.dispatcher_window - _pending_claim_count(pending)
        if available <= 0:
            return 0
        limit = min(available, self.dispatcher_refill_batch)
        self.queue.requeue_expired_leases()
        self.queue.prepare_ready(
            node_id=entry_node_id,
            eligible_profile_ids=node_profile_ids,
            batch_id=None,
            limit=limit,
            leased_by=worker.worker_id,
            lease_ttl_s=worker.lease_ttl_s,
            max_node_depth=0,
            kv_capacity_bytes=self.dispatcher_kv_capacity_bytes,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
        )
        claims = self.queue.claim_ready_batch(
            node_id=entry_node_id,
            batch_id=None,
            limit=limit,
            leased_by=worker.worker_id,
            lease_ttl_s=worker.lease_ttl_s,
            batch_linger_s=self.dispatcher_batch_linger_s,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
            batch_limits_by_service=batch_limits_by_service,
        )
        if not claims:
            return 0
        self._dispatcher_submit_cohort(executor=executor, worker=worker, pending=pending, claims=claims)
        return len(claims)

    def _dispatcher_refill_resident_multimodel(
        self,
        *,
        worker: BatchWorker,
        executor: ThreadPoolExecutor,
        pending: dict[Any, Any],
        entry_node_id: str,
        node_profile_ids: tuple[str, ...],
        batch_limits_by_service: dict[str, int],
        kv_shard_layouts_by_profile: dict[str, Any],
        service_plans: dict[str, ResidentServicePlan],
    ) -> int:
        global_available = self.dispatcher_window - _pending_claim_count(pending)
        if global_available <= 0:
            return 0
        self.queue.requeue_expired_leases()
        active_by_service = _pending_claim_count_by_service(pending)
        submitted = 0
        made_ready = 0
        attempted = 0
        for plan in _resident_service_order(service_plans, active_by_service):
            if global_available <= 0 or submitted >= self.dispatcher_refill_batch:
                break
            limit = self._resident_refill_limit(plan, active_by_service, submitted, global_available)
            if limit <= 0:
                continue
            attempted += 1
            made_ready += self._resident_prepare_ready(worker, plan, entry_node_id, node_profile_ids, limit, kv_shard_layouts_by_profile)
            claims = self._resident_claim_ready(worker, plan, entry_node_id, limit, kv_shard_layouts_by_profile, batch_limits_by_service)
            if not claims:
                continue
            claimed = len(claims)
            self._dispatcher_submit_cohort(
                executor=executor,
                worker=worker,
                pending=pending,
                claims=claims,
                rolling_refill=_plan_uses_rolling_admission(plan),
                entry_node_id=entry_node_id,
                node_profile_ids=node_profile_ids,
                batch_limits_by_service=batch_limits_by_service,
                kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
                low_watermark=plan.low_watermark,
            )
            plan.charge(claimed)
            submitted += claimed
            global_available -= claimed
            active_by_service[plan.service_id] = int(active_by_service.get(plan.service_id, 0)) + claimed
        self._dispatcher_note_resident(pending, service_plans, attempted=attempted, made_ready=made_ready)
        return submitted

    def _resident_refill_limit(self, plan: ResidentServicePlan, active_by_service: dict[str, int], submitted: int, global_available: int) -> int:
        active = int(active_by_service.get(plan.service_id, 0))
        service_available = max(0, int(plan.queue_depth_target) - active)
        if service_available <= 0:
            return 0
        if active > int(plan.low_watermark):
            return 0
        return min(
            service_available,
            max(1, int(plan.max_cohort_size)),
            max(1, int(self.dispatcher_refill_batch) - submitted),
            global_available,
        )

    def _resident_prepare_ready(self, worker: BatchWorker, plan: ResidentServicePlan, entry_node_id: str, node_profile_ids: tuple[str, ...], limit: int, kv_shard_layouts_by_profile: dict[str, Any]) -> int:
        return self.queue.prepare_ready(
            node_id=entry_node_id,
            eligible_profile_ids=node_profile_ids,
            batch_id=None,
            limit=limit,
            leased_by=worker.worker_id,
            lease_ttl_s=worker.lease_ttl_s,
            max_node_depth=0,
            kv_capacity_bytes=self.dispatcher_kv_capacity_bytes,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
            selected_service_id=plan.service_id,
            share_compute_domain=True,
        )

    def _resident_claim_ready(self, worker: BatchWorker, plan: ResidentServicePlan, entry_node_id: str, limit: int, kv_shard_layouts_by_profile: dict[str, Any], batch_limits_by_service: dict[str, int]) -> list[QueueClaim]:
        return self.queue.claim_ready_batch(
            node_id=entry_node_id,
            batch_id=None,
            limit=limit,
            leased_by=worker.worker_id,
            lease_ttl_s=worker.lease_ttl_s,
            batch_linger_s=plan.batch_linger_s,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
            batch_limits_by_service=batch_limits_by_service,
            selected_service_id=plan.service_id,
            share_compute_domain=True,
        )

    def _dispatcher_note_resident(self, pending: dict[Any, Any], service_plans: dict[str, ResidentServicePlan], *, attempted: int, made_ready: int) -> None:
        self._dispatcher_note(
            pending_by_service=_pending_claim_count_by_service(pending),
            pending_cohort_details=_pending_cohort_details(pending),
            resident_service_targets={sid: plan.target_active for sid, plan in service_plans.items()},
            resident_service_queue_depth_targets={sid: plan.queue_depth_target for sid, plan in service_plans.items()},
            resident_service_low_watermarks={sid: plan.low_watermark for sid, plan in service_plans.items()},
            resident_service_admission_modes={sid: plan.admission_mode for sid, plan in service_plans.items()},
            resident_service_deficits={sid: round(plan.deficit, 3) for sid, plan in service_plans.items()},
            resident_refill_attempted_services=attempted,
            resident_prefilled_count=made_ready,
        )

    def _dispatcher_submit_cohort(
        self,
        *,
        executor: ThreadPoolExecutor,
        worker: BatchWorker,
        pending: dict[Any, Any],
        claims: list[QueueClaim],
        rolling_refill: bool = False,
        entry_node_id: str | None = None,
        node_profile_ids: tuple[str, ...] = (),
        batch_limits_by_service: dict[str, int] | None = None,
        kv_shard_layouts_by_profile: dict[str, Any] | None = None,
        low_watermark: int = 0,
    ) -> None:
        admission_mode = "rolling_refill" if rolling_refill else "cohort"
        cohort = PendingDispatcherCohort.from_claims(list(claims), admission_mode=admission_mode)
        if rolling_refill:
            future = executor.submit(
                _dispatcher_run_resident_rolling_claims,
                worker,
                claims,
                len(claims),
                cohort.mark_finished,
                entry_node_id,
                node_profile_ids,
                self.dispatcher_kv_capacity_bytes,
                kv_shard_layouts_by_profile or {},
                batch_limits_by_service or {},
                low_watermark,
            )
        else:
            future = executor.submit(_dispatcher_run_claims, worker, claims, len(claims), cohort.mark_finished)
        pending[future] = cohort
        largest = max(int(self.dispatcher_state.get("largest_claimed_cohort_size") or 0), len(claims))
        last_by_service = dict(self.dispatcher_state.get("last_claimed_cohort_by_service") or {})
        if cohort.service_id:
            last_by_service[str(cohort.service_id)] = len(claims)
        self._dispatcher_note(
            last_claimed_cohort_size=len(claims),
            largest_claimed_cohort_size=largest,
            last_claimed_service_id=cohort.service_id,
            last_claimed_cohort_by_service=last_by_service,
        )

    def _dispatcher_finish_done(self, worker: BatchWorker, pending: dict[Any, Any], *, block: bool) -> tuple[int, int, int]:
        if not pending:
            return (0, 0, 0)
        if block:
            done, _ = wait(list(pending.keys()), timeout=None, return_when=FIRST_COMPLETED)
        else:
            done = {future for future in pending if future.done()}
        completed = failed = retried = 0
        for future in list(done):
            cohort = _pending_cohort(pending.pop(future))
            claims = cohort.claims
            try:
                pairs = future.result()
            except Exception as exc:
                pairs = [(claim, _dispatcher_transport_failure(claim, str(exc))) for claim in cohort.active_claims()]
            if len(pairs) == 1 and pairs[0][0] is _DISPATCHER_BATCH_FINISHED:
                summary = pairs[0][1]
                completed += int(summary.get("completed") or 0)
                failed += int(summary.get("failed") or 0)
                retried += int(summary.get("retried") or 0)
                claimed_extra = max(0, int(summary.get("claimed") or 0) - len(claims))
                if claimed_extra:
                    self._dispatcher_count(claimed_count=claimed_extra, submitted_count=claimed_extra)
                self._dispatcher_note(last_summary=summary)
                continue
            for claim, result in pairs:
                item_completed, item_failed, item_retried = worker._finish_pair(claim, result, None)
                completed += item_completed
                failed += item_failed
                retried += item_retried
        return completed, failed, retried

    def _registry(self) -> ProfileRegistry:
        return ProfileRegistry.load(self.profiles_dir)

    def _topology(self) -> SparkTopology:
        return SparkTopology.load(self.topology_path)

    def _runner(self, topology: SparkTopology, *, timeout_s: int) -> Runner:
        if self.runner_kind == "fake":
            return FakeRunner()
        return PipelineOpenAIRunner(timeout_s=int(timeout_s), base_urls=_pipeline_base_urls(topology), jit_kv_circuit=self.jit_kv_circuit)


def serve(*, host: str, port: int, queue_dir: str | Path, profiles_dir: str | Path, topology_path: str | Path, runner_kind: str = "pipeline", sync_timeout_s: float | None = None) -> None:
    if sync_timeout_s is None:
        sync_timeout_s = _default_sync_timeout_s()
    api = CoordinatorApi(queue_dir=queue_dir, profiles_dir=profiles_dir, topology_path=topology_path, runner_kind=runner_kind, sync_timeout_s=sync_timeout_s)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            code, payload = api.handle_get(parsed.path, parse_qs(parsed.query))
            _write_json(self, code, payload)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                body = _read_json(self)
                if parsed.path == "/v1/completions" and body.get("stream"):
                    write_sse(self, openai_completion_stream_events(api, body))
                    return
                if parsed.path == "/v1/chat/completions" and body.get("stream"):
                    write_sse(self, openai_chat_stream_events(api, body))
                    return
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
    parser.add_argument("--sync-timeout-s", type=float, default=None)
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, queue_dir=args.queue_dir, profiles_dir=args.profiles_dir, topology_path=args.topology, runner_kind=args.runner_kind, sync_timeout_s=args.sync_timeout_s)
    return 0


def _topology_dispatch_window(topology_path: Path) -> int:
    try:
        topology = SparkTopology.load(topology_path)
    except Exception:
        return 64
    coordinator = topology.routing_policy.get("resident_coordinator_defaults") if isinstance(topology.routing_policy, dict) else {}
    if isinstance(coordinator, dict) and coordinator.get("dispatch_window") is not None:
        return max(1, int(coordinator["dispatch_window"]))
    active = _active_resident_service_ids(topology)
    values: list[int] = []
    for service in topology.pipeline_services.values():
        if active is not None and service.service_id not in active:
            continue
        try:
            values.append(_service_dispatch_batch_limit(service))
        except Exception:
            continue
    return max(64, sum(values) if values else 0)


def _topology_dispatch_cohort_workers(topology_path: Path) -> int:
    try:
        topology = SparkTopology.load(topology_path)
    except Exception:
        return 4
    coordinator = topology.routing_policy.get("resident_coordinator_defaults") if isinstance(topology.routing_policy, dict) else {}
    if isinstance(coordinator, dict):
        raw = coordinator.get("dispatch_cohort_workers") or coordinator.get("dispatch_window")
        if raw is not None:
            return max(1, int(raw))
    active = _active_resident_service_ids(topology)
    count = sum(1 for service in topology.pipeline_services.values() if active is None or service.service_id in active)
    return max(4, min(32, count * 4))


def _default_sync_timeout_s() -> float:
    return _env_float("DS4_API_SYNC_TIMEOUT_S", 3600.0)


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
    thinking_budget_tokens: int = 0,
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
        "thinking_budget_tokens": max(0, int(thinking_budget_tokens)),
        "temperature": float(temperature),
        "input": input_payload,
        "output_contract": output_contract,
        "model_pin": {"profile_id": profile.profile_id},
        "raw": {},
    }


def _input_with_api_kv(input_payload: dict[str, Any], body: dict[str, Any], profile: ModelProfile, topology: SparkTopology) -> dict[str, Any]:
    out = dict(input_payload)
    openai = {key: body[key] for key in OPENAI_REQUEST_FIELDS if key in body and body[key] is not None}
    extra_body = body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}
    openai.update({key: extra_body[key] for key in OPENAI_REQUEST_FIELDS if key in extra_body and extra_body[key] is not None})
    if openai:
        out["openai"] = {**dict(out.get("openai") or {}), **openai}
    if extra_body:
        excluded_extra_keys = {"ds4_async", *OPENAI_REQUEST_FIELDS}
        preserved_extra = {key: value for key, value in extra_body.items() if key not in excluded_extra_keys}
        if preserved_extra:
            out["openai_extra_body"] = {**dict(out.get("openai_extra_body") or {}), **preserved_extra}
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
        out["kv_cache_plan"] = _plan_with_source_provenance(dict(raw), out)
        return out
    if raw.get("format") == KV_CACHE_DIRECTIVE_FORMAT or has_kv_cache:
        directive = dict(raw)
        directive.setdefault("format", KV_CACHE_DIRECTIVE_FORMAT)
        out["kv_cache"] = directive
        out["kv_cache_plan"] = _plan_with_source_provenance(normalize_kv_cache_directive(directive), out)
        return out
    out["external_kv"] = dict(raw)
    out["kv_cache_plan"] = _external_kv_plan(raw, profile=profile, topology=topology, source_input=out)
    out["kv_cache_key"] = str(raw["kv_key"])
    if raw.get("total_bytes") is not None or raw.get("bytes") is not None:
        out["kv_bytes_estimate"] = int(raw.get("total_bytes") or raw.get("bytes") or 0)
    return out


def _thinking_budget_tokens(body: dict[str, Any], metadata: dict[str, Any] | None = None) -> int:
    extra_body = body.get("extra_body") if isinstance(body.get("extra_body"), dict) else {}
    for container in (body, extra_body, metadata or {}):
        for key in ("thinking_budget_tokens", "thinking_token_budget"):
            value = container.get(key) if isinstance(container, dict) else None
            if value is None:
                continue
            return max(0, int(value))
    return 0


def _prepare_queue_request_json(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("queue request must be an object")
    raw = dict(item)
    input_payload = raw.get("input")
    if not isinstance(input_payload, dict):
        return raw
    out = dict(input_payload)
    directive = out.get("kv_cache")
    if isinstance(directive, dict):
        plan = normalize_kv_cache_directive(directive)
        existing = out.get("kv_cache_plan")
        if existing is not None and existing != plan:
            raise ValueError("input.kv_cache_plan conflicts with input.kv_cache")
        out["kv_cache_plan"] = _plan_with_source_provenance(plan, out)
        cache_key = plan.get("cache_id") or plan.get("prefix_hash")
        if cache_key and out.get("kv_cache_key") is None:
            out["kv_cache_key"] = str(cache_key)
        for endpoint_name in ("load", "store"):
            endpoint = plan.get(endpoint_name)
            if isinstance(endpoint, dict) and endpoint.get("bytes") is not None and out.get("kv_bytes_estimate") is None:
                out["kv_bytes_estimate"] = int(endpoint.get("bytes") or 0)
                break
    elif isinstance(out.get("kv_cache_plan"), dict):
        out["kv_cache_plan"] = _plan_with_source_provenance(dict(out["kv_cache_plan"]), out)
    raw["input"] = out
    return raw


def _external_kv_plan(raw: dict[str, Any], *, profile: ModelProfile, topology: SparkTopology, source_input: dict[str, Any] | None = None) -> dict[str, Any]:
    kv_key = str(raw.get("kv_key") or "")
    if not kv_key:
        raise ValueError("external_kv shorthand requires kv_key")
    namespace = str(raw.get("namespace") or "default")
    service_id = _optional_str(raw.get("service_id"))
    service = None
    if service_id is None:
        service = topology.pipeline_service_for_profile(profile.profile_id)
        service_id = service.service_id if service is not None else None
    else:
        try:
            service = topology.pipeline_service_by_id(service_id)
        except ValueError:
            service = None
    model_fingerprint = dict(raw.get("model_fingerprint") or {})
    if service is not None:
        contract = service.kv_cache_contract()
        model_fingerprint.setdefault("kv_cache_contract", contract)
        model_fingerprint.setdefault("layer_partition_fingerprint", contract["fingerprint"])
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
    miss_policy = str(raw.get("miss_policy") or "compute")
    store_mode = str(raw.get("store_mode") or raw.get("store_policy") or "")
    if not store_mode:
        store_mode = "write_back" if miss_policy == "compute_and_store" else "skip"
    if store_mode == "skip":
        store = {"mode": "skip", "transport": "none"}
    else:
        store = {
            "mode": store_mode,
            "transport": "external_manifest",
            "namespace": namespace,
            "kv_key": kv_key,
            "service_id": service_id,
        }
    operation = "load_store" if load["mode"] != "skip" and store["mode"] != "skip" else ("store" if store["mode"] != "skip" else "load")
    plan = {
        "format": KV_CACHE_PLAN_FORMAT,
        "backend": str(raw.get("backend") or "auto"),
        "cache_id": kv_key,
        "prefix_hash": _optional_str(raw.get("prefix_hash")),
        "load": load,
        "store": store,
        "miss_policy": miss_policy,
        "route_affinity": str(raw.get("route_affinity") or "required"),
        "model_fingerprint": model_fingerprint,
        "operation": operation,
    }
    plan["batch_key_hash"] = "sha256:" + hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return _plan_with_source_provenance(plan, source_input)


def _plan_with_source_provenance(plan: dict[str, Any], source_input: dict[str, Any] | None) -> dict[str, Any]:
    source = _kv_source_provenance(source_input or {})
    if source:
        out = dict(plan)
        out["source_provenance"] = source
        return out
    return plan


def _kv_source_provenance(input_payload: dict[str, Any]) -> dict[str, Any]:
    prompt = input_payload.get("rendered_prompt")
    if not isinstance(prompt, str) or not prompt:
        prompt = input_payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return {}
    prompt_bytes = prompt.encode("utf-8")
    source: dict[str, Any] = {
        "format": "ds4-kv-source-provenance-v1",
        "source_type": "rendered_prompt" if input_payload.get("rendered_prompt") == prompt else "prompt",
        "prompt_sha256": "sha256:" + hashlib.sha256(prompt_bytes).hexdigest(),
        "prompt_bytes": len(prompt_bytes),
        "prompt_text": prompt,
    }
    if input_payload.get("estimated_prompt_tokens") is not None:
        source["estimated_prompt_tokens"] = int(input_payload.get("estimated_prompt_tokens") or 0)
    token_ids = input_payload.get("original_tokens")
    if isinstance(token_ids, list) and all(isinstance(item, int) for item in token_ids):
        source["original_tokens"] = list(token_ids)
        source["original_token_count"] = len(token_ids)
        source["original_tokens_sha256"] = "sha256:" + hashlib.sha256(json.dumps(token_ids, separators=(",", ":")).encode("utf-8")).hexdigest()
    return source


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
    for alias, profile_id in sorted(MODEL_ALIASES.items()):
        try:
            profile = registry.get(profile_id)
        except ValueError:
            continue
        if alias in seen:
            continue
        seen.add(alias)
        data.append({"id": alias, "object": "model", "owned_by": "ds4", "ds4_profile_id": profile.profile_id, "ds4_model_alias": True})
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
        aliased = resolve_model_alias(model)
        if aliased != model:
            profile = registry.get(aliased)
            if topology.pipeline_service_for_profile(profile.profile_id) is not None:
                return profile
            active = _active_profile_for_model(registry, topology, profile.model_id)
            if active is not None:
                return active
            return profile
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
        raise ValueError(f"model/profile {model_id!r} resolved to {profile.profile_id!r}, but that profile is not a configured pipeline service")
    default_profile = registry.resolve(capability="efficient", chat=True, job_class="analysis")
    default_service = topology.pipeline_service_for_profile(default_profile.profile_id)
    if default_service is None:
        active_default = _active_profile_for_model(registry, topology, default_profile.model_id)
        if active_default is not None:
            default_service = topology.pipeline_service_for_profile(active_default.profile_id)
    if default_service is None:
        raise ValueError("no default pipeline service is configured")
    return default_service


def _active_profile_for_model(registry: ProfileRegistry, topology: SparkTopology, model_id: str) -> ModelProfile | None:
    active = _active_resident_service_ids(topology)
    candidates: list[ModelProfile] = []
    for service in topology.pipeline_services.values():
        if active is not None and service.service_id not in active:
            continue
        if service.model_id != model_id:
            continue
        try:
            candidates.append(registry.get(service.profile_id))
        except ValueError:
            continue
    if not candidates:
        return None
    return sorted(candidates, key=lambda profile: int(profile.routing.get("rank", 1000)))[0]


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


def _openai_result_error(result: dict[str, Any]) -> dict[str, Any] | None:
    text, status = _result_text_and_status(result)
    if status == "completed":
        return None
    return {
        "error": {
            "message": text or status,
            "type": "ds4_transport_error",
            "code": status,
        },
        "ds4": {"request": result.get("request"), "status": status},
    }


def _openai_batch_error(result: dict[str, Any]) -> dict[str, Any] | None:
    rows = result.get("results") if isinstance(result.get("results"), list) else []
    failed = []
    for index, row in enumerate(rows):
        item = row if isinstance(row, dict) else {}
        text, status = _result_text_and_status(item)
        if status != "completed":
            failed.append({"index": index, "status": status, "message": text or status})
    state = str(result.get("state") or "")
    if not failed and state not in {"failed", "cancelled", "completed_with_failures", "completed_with_cancelled"}:
        return None
    return {
        "error": {
            "message": f"DS4 batch completed with {len(failed)} failed result(s)" if failed else f"DS4 batch state {state}",
            "type": "ds4_transport_error",
            "code": state or "failed",
        },
        "ds4": {
            "batch_id": result.get("batch_id"),
            "state": state,
            "result_count": len(rows),
            "failed": failed[:16],
            "failed_count": len(failed),
        },
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


def _openai_completion_batch_response(*, request_id: str, model: str, result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("results") if isinstance(result.get("results"), list) else []
    choices = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for index, row in enumerate(rows):
        item = row if isinstance(row, dict) else {}
        text, status = _result_text_and_status(item)
        item_usage = _result_usage(item)
        usage["prompt_tokens"] += int(item_usage.get("prompt_tokens", 0) or 0)
        usage["completion_tokens"] += int(item_usage.get("completion_tokens", 0) or 0)
        usage["total_tokens"] += int(item_usage.get("total_tokens", 0) or 0)
        choices.append({"index": index, "text": text, "finish_reason": "stop" if status == "completed" else "error"})
    return {
        "id": request_id,
        "object": "text_completion",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
        "usage": usage,
        "ds4": {"batch_id": result.get("batch_id"), "state": result.get("state"), "result_count": len(rows)},
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
    prompt_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    completion_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    total_tokens = int(usage.get("total_tokens", 0) or 0)
    if total_tokens == 0 and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens}


def _anthropic_usage(result: dict[str, Any]) -> dict[str, int]:
    usage = _result_usage(result)
    return {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]}


def _async_queue_response(kind: str, request_id: str, batch_id: str, submitted: dict[str, Any]) -> dict[str, Any]:
    return {"format": "ds4-async-api-response-v1", "api": kind, "request_id": request_id, "batch_id": batch_id, "job_id": batch_id, "queue": submitted}


def _completion_prompt_items(prompt: Any) -> list[str]:
    if isinstance(prompt, list) and all(isinstance(item, str) for item in prompt):
        return [str(item) for item in prompt]
    if isinstance(prompt, str):
        return [prompt]
    return [json.dumps(prompt, sort_keys=True)]


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
    limits = {service.service_id: _service_dispatch_batch_limit(service) for service in topology.pipeline_services.values()}
    overrides = {}
    raw_overrides = os.environ.get("DS4_API_BATCH_LIMITS_JSON")
    if raw_overrides:
        try:
            parsed = json.loads(raw_overrides)
        except json.JSONDecodeError:
            parsed = {}
        overrides = parsed if isinstance(parsed, dict) else {}
    if not overrides:
        return limits
    for service in topology.pipeline_services.values():
        for key in (service.service_id, service.profile_id, service.model_id):
            if key in overrides:
                limits[service.service_id] = max(1, int(overrides[key]))
                break
    return limits


def _service_dispatch_batch_limit(service: Any) -> int:
    scheduler = getattr(service, "scheduler", {}) or {}
    if isinstance(scheduler, dict):
        for key in ("dispatch_batch_limit", "max_dispatch_cohort", "queue_depth_target", "vllm_queue_depth_target"):
            value = scheduler.get(key)
            if value is not None:
                return max(1, int(value))
    return pipeline_service_batch_limit(service)


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


def _query_bool(query: dict[str, list[str]], key: str, default: bool) -> bool:
    value = _one(query, key)
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _query_float(query: dict[str, list[str]], key: str, default: float) -> float:
    value = _one(query, key)
    if value is None or value == "":
        return float(default)
    return float(value)


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _body_float(body: dict[str, Any], key: str, default: float) -> float:
    if key not in body or body.get(key) is None:
        return float(default)
    return float(body[key])


_DISPATCHER_BATCH_FINISHED: Any = object()


def _dispatcher_run_claims(worker: BatchWorker, claims: list[QueueClaim], concurrency: int, mark_finished: Callable[[str], None] | None = None) -> list[tuple[Any, dict[str, Any]]]:
    if not claims:
        return []
    if claims[0].request_kind == "cpu":
        return worker._run_cpu_claims(claims, max(1, concurrency))
    if _dispatcher_can_batch_models(worker, claims):
        if hasattr(worker.runner, "run_many_on_node_incremental"):
            completed, failed, retried = worker._run_model_batch_incremental(claims, max(1, concurrency), None, on_item_finished=mark_finished)
            return [(_DISPATCHER_BATCH_FINISHED, {"completed": completed, "failed": failed, "retried": retried})]
        return worker._run_model_batch(claims, max(1, concurrency))
    out: list[tuple[QueueClaim, dict[str, Any]]] = []
    max_workers = max(1, min(max(1, concurrency), len(claims)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker._run_one, claim): claim for claim in claims}
        for future in as_completed(futures):
            claim = futures[future]
            try:
                out.append((claim, future.result()))
            except Exception as exc:
                out.append((claim, _dispatcher_transport_failure(claim, str(exc))))
    return out


def _dispatcher_run_resident_rolling_claims(
    worker: BatchWorker,
    claims: list[QueueClaim],
    concurrency: int,
    mark_finished: Callable[[str], None] | None,
    entry_node_id: str | None,
    node_profile_ids: tuple[str, ...],
    kv_capacity_bytes: int,
    kv_shard_layouts_by_profile: dict[str, Any],
    batch_limits_by_service: dict[str, int],
    low_watermark: int,
) -> list[tuple[Any, dict[str, Any]]]:
    if not claims:
        return []
    if claims[0].request_kind == "cpu":
        return _dispatcher_run_claims(worker, claims, concurrency, mark_finished)
    try:
        completed, failed, retried, claimed, prefilled = worker.run_resident_refill_stream(
            claims,
            max(1, concurrency),
            None,
            node_id=entry_node_id,
            node_profile_ids=node_profile_ids,
            max_node_depth=0,
            kv_capacity_bytes=kv_capacity_bytes,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
            batch_limits_by_service=batch_limits_by_service,
            refill_low_watermark=max(1, int(low_watermark)),
            on_item_finished=mark_finished,
        )
    except Exception as exc:
        return [(claim, _dispatcher_transport_failure(claim, str(exc))) for claim in claims]
    return [
        (
            _DISPATCHER_BATCH_FINISHED,
            {
                "completed": completed,
                "failed": failed,
                "retried": retried,
                "claimed": claimed,
                "prefilled": prefilled,
                "dispatch_mode": "rolling_refill",
            },
        )
    ]


def _dispatcher_can_batch_models(worker: BatchWorker, claims: list[QueueClaim]) -> bool:
    if not claims or claims[0].request_kind != "model" or not hasattr(worker.runner, "run_many_on_node"):
        return False
    first = claims[0]
    return all(
        claim.request_kind == "model"
        and claim.selected_profile_id == first.selected_profile_id
        and claim.selected_node_id == first.selected_node_id
        and claim.selected_service_id == first.selected_service_id
        for claim in claims
    )


def _dispatcher_transport_failure(claim: QueueClaim, error: str) -> dict[str, Any]:
    return {
        "format": "ds4-inference-failure-v1",
        "request_id": claim.request_id,
        "status": "transport_failed",
        "error": error,
    }


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


def _csv_env(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    return {item.strip() for item in raw.replace(";", ",").split(",") if item.strip()}


if __name__ == "__main__":
    raise SystemExit(main())
