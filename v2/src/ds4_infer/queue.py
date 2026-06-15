from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
from math import ceil
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Iterable, Mapping
import uuid

from .external_kv_shards import external_kv_object_state_from_shards, update_external_kv_shard, validate_external_kv_shards
from .kv_cache import ensure_cache_refs_resolved, request_kv_cache_batch_key
from .profiles import ProfileRegistry
from .queue_policy import job_batch_id, request_priority, validated_priority
from .runners import Runner
from .schemas import InferenceRequest

QUEUE_FORMAT = "ds4-inference-queue-v1"
REQUEST_STATUS_FORMAT = "ds4-inference-request-status-v1"
BATCH_STATUS_FORMAT = "ds4-inference-batch-status-v1"
PIPELINE_STATUS_FORMAT = "ds4-pipeline-status-v1"
CPU_QUEUE_TIMEOUT_KEY = "__ds4_queue_timeout_s"
TERMINAL_STATES = {"completed", "failed", "cancelled"}
NODE_LOCAL_EXTERNAL_KV_ROUTING = {"sharding": "pipeline_layers", "control_node_id": "spark0", "data_plane": "node_local_shards", "spark0_aggregates_shards": False, "client_receives_shards": False}
NODE_LOCAL_EXTERNAL_KV_ARCHIVE = {"mode": "node_local_shards", "object_manifest_on_control_node_only": True, "shard_owner_is_node": True}


@dataclass(frozen=True)
class QueueClaim:
    request_id: str
    batch_id: str
    request_kind: str
    selected_profile_id: str
    selected_node_id: str | None
    lease_id: str
    attempt_count: int
    request: InferenceRequest | None
    service_name: str | None = None
    payload: dict[str, Any] | None = None
    selected_service_id: str | None = None
    selected_node_ids: tuple[str, ...] = ()
    selected_compute_domain: str | None = None
    compute_lease_id: str | None = None


class InferenceQueue:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "notices").mkdir(exist_ok=True)
        self.db_path = self.root / "queue.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma synchronous = normal")
        conn.execute("pragma temp_store = memory")
        conn.execute("pragma mmap_size = 268435456")
        conn.execute("pragma busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(
                """
                create table if not exists batches(
                    batch_id text primary key, state text not null default 'queued',
                    request_count integer not null default 0, queued_count integer not null default 0,
                    prefilling_count integer not null default 0, ready_count integer not null default 0,
                    running_count integer not null default 0, completed_count integer not null default 0,
                    failed_count integer not null default 0, cancelled_count integer not null default 0,
                    created_at real not null, updated_at real not null
                );
                create table if not exists requests(
                    request_id text primary key, batch_id text not null, request_kind text not null default 'model',
                    service_name text, state text not null, priority integer not null, immediate integer not null default 0,
                    selected_profile_id text not null, selected_node_id text, selected_service_id text,
                    selected_node_ids_json text, selected_compute_domain text, compute_lease_id text,
                    request_json text not null, request_json_hash text, result_json text, error text, cancel_requested integer not null default 0,
                    kv_key text, kv_bytes integer not null default 0, kv_shard_count integer not null default 0,
                    kv_shard_bytes integer not null default 0,
                    created_at real not null, updated_at real not null, ready_at real,
                    started_at real, completed_at real, lease_id text, leased_by text,
                    lease_expires_at real, heartbeat_at real, attempt_count integer not null default 0
                );
                create table if not exists events(
                    event_id integer primary key autoincrement, created_at real not null,
                    request_id text not null, event_type text not null, state text not null, payload_json text not null
                );
                create table if not exists kv_entries(
                    node_id text not null, kv_key text not null, request_id text not null,
                    bytes integer not null, state text not null, last_used_at real not null,
                    created_at real not null, updated_at real not null,
                    primary key(node_id, kv_key)
                );
                create table if not exists kv_shard_entries(
                    service_id text not null, node_id text not null, kv_key text not null, request_id text not null,
                    stage_index integer not null, stage_count integer not null,
                    layer_start integer, layer_end integer,
                    bytes integer not null, state text not null, last_used_at real not null,
                    created_at real not null, updated_at real not null,
                    primary key(service_id, node_id, kv_key)
                );
                create table if not exists compute_leases(
                    compute_domain text primary key, compute_lease_id text not null, service_id text,
                    leased_by text not null, lease_expires_at real not null, heartbeat_at real not null,
                    request_count integer not null, created_at real not null, updated_at real not null
                );
                create table if not exists pipeline_telemetry(
                    service_id text not null, node_id text not null, stage_index integer not null,
                    stage_count integer not null, layer_start integer, layer_end integer, layer_count integer,
                    kv_shard_bytes integer not null default 0, payload_json text not null,
                    reported_at real not null, primary key(service_id, node_id, stage_index)
                );
                create table if not exists kv_memory_objects(
                    namespace text not null, kv_key text not null, service_id text not null,
                    profile_id text, model_id text, owner text, content_hash text,
                    total_bytes integer not null default 0, total_tokens integer not null default 0,
                    state text not null, pin_count integer not null default 0, priority integer not null default 100,
                    ttl_expires_at real, metadata_json text not null,
                    created_at real not null, updated_at real not null, last_used_at real not null,
                    primary key(namespace, kv_key, service_id)
                );
                create table if not exists kv_memory_shards(
                    namespace text not null, kv_key text not null, service_id text not null,
                    node_id text not null, stage_index integer not null, stage_count integer not null,
                    layer_start integer, layer_end integer, bytes integer not null default 0,
                    state text not null, storage_uri text, gpu_resident integer not null default 0,
                    metadata_json text not null, created_at real not null, updated_at real not null, last_used_at real not null,
                    primary key(namespace, kv_key, service_id, node_id, stage_index)
                );
                create table if not exists kv_memory_leases(
                    lease_id text primary key, namespace text not null, kv_key text not null,
                    service_id text not null, mode text not null, owner text,
                    expires_at real not null, created_at real not null, updated_at real not null
                );
                create index if not exists requests_ready_idx on requests(state, selected_node_id, priority, ready_at, created_at);
                create index if not exists requests_queued_idx on requests(state, priority, created_at, request_id);
                create index if not exists requests_job_idx on requests(batch_id, state);
                create index if not exists requests_service_idx on requests(selected_service_id, state, priority, ready_at);
                create index if not exists kv_shards_node_idx on kv_shard_entries(service_id, node_id, state, last_used_at);
                create index if not exists kv_memory_objects_state_idx on kv_memory_objects(service_id, state, priority, last_used_at);
                create index if not exists kv_memory_shards_node_idx on kv_memory_shards(service_id, node_id, state, last_used_at);
                create index if not exists kv_memory_leases_expiry_idx on kv_memory_leases(service_id, expires_at);
                """
            )
            _ensure_request_columns(conn)
            _ensure_kv_shard_columns(conn)

    def submit_requests(self, *, requests: Iterable[InferenceRequest], registry: ProfileRegistry, topology: Any | None = None, batch_id: str | None = None, priority: int | None = None) -> dict[str, Any]:
        request_list = list(requests)
        if not request_list:
            raise ValueError("cannot submit an empty request set")
        batch_id = batch_id or "batch-" + uuid.uuid4().hex[:16]
        existing = self._existing_submission(batch_id, request_list, priority)
        if existing is not None:
            return existing
        now = time.time()
        profiles: dict[str, int] = {}
        priorities: dict[int, int] = {}
        nodes: dict[str, int] = {}
        services: dict[str, int] = {}
        late_bound_count = 0
        ids: list[str] = []
        current_load: dict[str, int] = {}
        bind_on_submit = bool(getattr(topology, "routing_policy", {}).get("bind_on_submit", False)) if topology is not None else False
        with closing(self._connect()) as conn, conn:
            conn.execute("insert into batches(batch_id, created_at, updated_at) values (?, ?, ?)", (batch_id, now, now))
            for req in request_list:
                ensure_cache_refs_resolved(req.input)
                profile = registry.resolve(capability=req.capability, chat=req.chat, job_class=req.job_class, model_pin=req.model_pin)
                prio = request_priority(req, priority_override=priority)
                kv_key, kv_bytes = _kv_need(req)
                assignment = topology.assign_profile(profile, immediate=req.immediate, current_load=current_load) if topology is not None else None
                selected_node_id = selected_service_id = selected_compute_domain = selected_node_ids_json = None
                kv_shard_count = kv_shard_bytes = 0
                if assignment is not None and (bind_on_submit or assignment.service_id is not None or assignment.reason == "resident_profile_group"):
                    selected_node_id = assignment.node_id
                    selected_service_id = assignment.service_id
                    selected_compute_domain = assignment.compute_domain
                    node_ids = tuple(assignment.node_ids or (assignment.node_id,))
                    selected_node_ids_json = json.dumps(list(node_ids), sort_keys=True)
                    if selected_node_id:
                        nodes[selected_node_id] = nodes.get(selected_node_id, 0) + 1
                        current_load[selected_node_id] = current_load.get(selected_node_id, 0) + 1
                    if selected_service_id:
                        services[selected_service_id] = services.get(selected_service_id, 0) + 1
                        kv_shard_count = len(node_ids)
                        kv_shard_bytes = int(ceil(kv_bytes / max(1, kv_shard_count))) if kv_bytes > 0 else 0
                else:
                    late_bound_count += 1
                request_json = _canonical_request_json(req.raw)
                request_json_hash = _request_json_hash(request_json)
                conn.execute(
                    """
                    insert into requests(request_id,batch_id,request_kind,state,priority,immediate,selected_profile_id,
                        selected_node_id,selected_service_id,selected_node_ids_json,selected_compute_domain,request_json,
                        request_json_hash,kv_key,kv_bytes,kv_shard_count,kv_shard_bytes,created_at,updated_at)
                    values (?,?,'model','queued',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        req.request_id,
                        batch_id,
                        prio,
                        1 if req.immediate else 0,
                        profile.profile_id,
                        selected_node_id,
                        selected_service_id,
                        selected_node_ids_json,
                        selected_compute_domain,
                        request_json,
                        request_json_hash,
                        kv_key,
                        kv_bytes,
                        kv_shard_count,
                        kv_shard_bytes,
                        now,
                        now,
                    ),
                )
                self._event(
                    conn,
                    req.request_id,
                    "submitted",
                    "queued",
                    {
                        "batch_id": batch_id,
                        "priority": prio,
                        "node_binding": "bound" if selected_node_id else "lease",
                        "selected_node_id": selected_node_id,
                        "selected_service_id": selected_service_id,
                        "selected_compute_domain": selected_compute_domain,
                    },
                )
                profiles[profile.profile_id] = profiles.get(profile.profile_id, 0) + 1
                priorities[prio] = priorities.get(prio, 0) + 1
                ids.append(req.request_id)
            self._refresh_batch(conn, batch_id)
        return {"format": QUEUE_FORMAT, "state": "queued", "batch_id": batch_id, "job_id": batch_id, "request_ids": ids, "request_count": len(ids), "selected_profiles": profiles, "selected_nodes": nodes, "selected_services": services, "priority_counts": {str(k): v for k, v in sorted(priorities.items())}, "metadata": {"late_bound_count": late_bound_count, "bound_count": len(ids) - late_bound_count}}

    def submit_cpu_requests(self, *, service: str, items: Iterable[dict[str, Any]], batch_id: str | None = None, immediate: bool = False, node_id: str | None = None, timeout_s: float | None = None, priority: int | None = None) -> dict[str, Any]:
        prio = validated_priority(priority, immediate=immediate)
        item_list = list(items)
        if not item_list:
            raise ValueError("cannot submit an empty CPU request set")
        batch_id = batch_id or "cpu-" + uuid.uuid4().hex[:16]
        now = time.time()
        ids: list[str] = []
        with closing(self._connect()) as conn, conn:
            conn.execute("insert into batches(batch_id, created_at, updated_at) values (?, ?, ?)", (batch_id, now, now))
            for item in item_list:
                request_id = str(item.get("custom_id") or item.get("request_id") or f"{batch_id}-{len(ids):06d}")
                payload = dict(item)
                if timeout_s is not None:
                    payload[CPU_QUEUE_TIMEOUT_KEY] = float(timeout_s)
                conn.execute(
                    """
                    insert into requests(request_id,batch_id,request_kind,service_name,state,priority,immediate,
                        selected_profile_id,selected_node_id,request_json,created_at,updated_at,ready_at)
                    values (?,?, 'cpu', ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (request_id, batch_id, service, prio, 1 if immediate else 0, f"cpu:{service}", node_id, json.dumps(payload, sort_keys=True), now, now, now),
                )
                self._event(conn, request_id, "submitted", "ready", {"batch_id": batch_id, "priority": prio, "service": service})
                ids.append(request_id)
            self._refresh_batch(conn, batch_id)
        return {"format": QUEUE_FORMAT, "state": "queued", "batch_id": batch_id, "job_id": batch_id, "request_ids": ids, "request_count": len(ids), "selected_profiles": {}, "selected_nodes": {node_id: len(ids)} if node_id else {}, "selected_services": {service: len(ids)}, "priority_counts": {str(prio): len(ids)}}

    def work(self, *, registry: ProfileRegistry, runner: Runner, node_id: str | None = None, batch_id: str | None = None, limit: int = 1, concurrency: int = 1, worker_id: str | None = None, lease_ttl_s: int = 900, heartbeat_interval_s: float = 5.0, node_profile_ids: Iterable[str] | None = None, max_node_depth: int = 0, batch_linger_s: float = 0.0, kv_capacity_bytes: int = 0, transport_max_attempts: int = 3, kv_shard_layouts_by_profile: Mapping[str, Any] | None = None, batch_limits_by_service: Mapping[str, int] | None = None, refill_low_watermarks_by_service: Mapping[str, int] | None = None, on_result: Callable[[QueueClaim, dict[str, Any]], None] | None = None) -> dict[str, Any]:
        from .worker import BatchWorker
        return BatchWorker(queue=self, registry=registry, runner=runner, worker_id=worker_id, lease_ttl_s=lease_ttl_s, heartbeat_interval_s=heartbeat_interval_s, transport_max_attempts=transport_max_attempts).run_once(node_id=node_id, batch_id=batch_id, limit=limit, concurrency=concurrency, node_profile_ids=tuple(node_profile_ids or ()), max_node_depth=max_node_depth, batch_linger_s=batch_linger_s, kv_capacity_bytes=kv_capacity_bytes, kv_shard_layouts_by_profile=kv_shard_layouts_by_profile or {}, batch_limits_by_service=batch_limits_by_service or {}, refill_low_watermarks_by_service=refill_low_watermarks_by_service or {}, on_result=on_result)

    def prepare_ready(self, *, node_id: str | None, eligible_profile_ids: Iterable[str], batch_id: str | None, limit: int, leased_by: str, lease_ttl_s: int, max_node_depth: int = 0, kv_capacity_bytes: int = 0, kv_shard_layouts_by_profile: Mapping[str, Any] | None = None, selected_service_id: str | None = None, share_compute_domain: bool = False) -> int:
        eligible = tuple(str(x) for x in eligible_profile_ids if str(x))
        now = time.time()
        made_ready = 0
        touched_batches: set[str] = set()
        kv_shard_layouts_by_profile = kv_shard_layouts_by_profile or {}
        with closing(self._connect()) as conn, conn:
            remaining = int(limit)
            if node_id is not None and max_node_depth > 0:
                remaining = min(remaining, max(0, int(max_node_depth) - _node_depth(conn, node_id)))
            if remaining <= 0:
                return 0
            rows = _queued_rows(conn, node_id=node_id, eligible=eligible, batch_id=batch_id, limit=remaining, selected_service_id=selected_service_id, ignore_compute_lease=share_compute_domain)
            for row in rows:
                bind_node_id = str(row["selected_node_id"] or node_id) if (row["selected_node_id"] or node_id) else None
                pipeline_layout = kv_shard_layouts_by_profile.get(str(row["selected_profile_id"]))
                if not self._reserve_kv(conn, row, node_id=bind_node_id, capacity=kv_capacity_bytes, now=now, pipeline_layout=pipeline_layout):
                    self._event(
                        conn,
                        str(row["request_id"]),
                        "kv_capacity_wait",
                        "queued",
                        {
                            "batch_id": row["batch_id"],
                            "node_id": bind_node_id,
                            "service_id": row["selected_service_id"],
                            "kv_capacity_bytes": kv_capacity_bytes,
                        },
                    )
                    continue
                lease_id = f"{leased_by}:prefill:{uuid.uuid4().hex}"
                node_ids_json = row["selected_node_ids_json"] or (json.dumps([bind_node_id]) if bind_node_id else None)
                updated = conn.execute(
                    """
                    update requests set state='ready', selected_node_id=coalesce(selected_node_id, ?),
                        selected_node_ids_json=coalesce(selected_node_ids_json, ?), ready_at=?, updated_at=?,
                        lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null
                    where request_id=? and state='queued'
                    """,
                    (bind_node_id, node_ids_json, now, now, row["request_id"]),
                ).rowcount
                if updated != 1:
                    continue
                self._event(conn, str(row["request_id"]), "prefilled", "ready", {"batch_id": row["batch_id"], "node_id": bind_node_id, "service_id": row["selected_service_id"], "lease_id": lease_id})
                touched_batches.add(str(row["batch_id"]))
                made_ready += 1
            for touched_batch_id in touched_batches:
                self._refresh_batch(conn, touched_batch_id)
        return made_ready

    def claim_ready_batch(self, *, node_id: str | None, batch_id: str | None, limit: int, leased_by: str, lease_ttl_s: int, batch_linger_s: float = 0.0, kv_shard_layouts_by_profile: Mapping[str, Any] | None = None, batch_limits_by_service: Mapping[str, int] | None = None, compute_lease_id: str | None = None, selected_service_id: str | None = None, share_compute_domain: bool = False, ready_shape_bucketing: bool = False, ready_shape_lookahead: int = 1) -> list[QueueClaim]:
        now = time.time()
        with closing(self._connect()) as conn, conn:
            rows = _ready_rows(conn, node_id=node_id, batch_id=batch_id, limit=limit, batch_limits_by_service=batch_limits_by_service or {}, selected_service_id=selected_service_id, ignore_compute_lease=share_compute_domain, ready_shape_bucketing=ready_shape_bucketing, ready_shape_lookahead=ready_shape_lookahead)
            if not rows:
                return []
            linger_limit = _service_batch_limit(rows[0]["selected_service_id"], batch_limits_by_service or {}, limit)
            if len(rows) < linger_limit and batch_linger_s > 0:
                newest_ready = max(float(row["ready_at"] or row["updated_at"] or now) for row in rows)
                if (now - newest_ready) < batch_linger_s:
                    return []
            if share_compute_domain:
                acquired_compute_lease_id = None
            else:
                acquired_compute_lease_id = self._extend_compute_lease(conn, rows=rows, compute_lease_id=compute_lease_id, leased_by=leased_by, lease_ttl_s=lease_ttl_s, now=now) if compute_lease_id else self._acquire_compute_lease(conn, rows=rows, leased_by=leased_by, lease_ttl_s=lease_ttl_s, now=now)
            new_compute_lease = (not share_compute_domain) and compute_lease_id is None and isinstance(acquired_compute_lease_id, str)
            if acquired_compute_lease_id is False:
                return []
            claims: list[QueueClaim] = []
            batch_ids: set[str] = set()
            for row in rows:
                lease_id = f"{leased_by}:run:{uuid.uuid4().hex}"
                updated = conn.execute(
                    """
                    update requests set state='running', lease_id=?, compute_lease_id=?, leased_by=?, lease_expires_at=?,
                        heartbeat_at=?, started_at=?, updated_at=?, attempt_count=attempt_count+1
                    where request_id=? and state='ready'
                    """,
                    (lease_id, acquired_compute_lease_id if isinstance(acquired_compute_lease_id, str) else None, leased_by, now + lease_ttl_s, now, now, now, row["request_id"]),
                ).rowcount
                if updated == 1:
                    batch_ids.add(str(row["batch_id"]))
                    self._event(conn, str(row["request_id"]), "started", "running", {"batch_id": row["batch_id"], "lease_id": lease_id, "node_id": row["selected_node_id"], "service_id": row["selected_service_id"], "compute_domain": row["selected_compute_domain"], "compute_lease_id": acquired_compute_lease_id if isinstance(acquired_compute_lease_id, str) else None})
                    claims.append(_claim(row, lease_id, acquired_compute_lease_id if isinstance(acquired_compute_lease_id, str) else None))
            if not claims and new_compute_lease:
                conn.execute("delete from compute_leases where compute_lease_id=?", (acquired_compute_lease_id,))
            for bid in batch_ids:
                self._refresh_batch(conn, bid)
            return claims

    def finish_request(self, *, request_id: str, lease_id: str, state: str, result: dict[str, Any], error: str | None = None) -> bool:
        if state not in TERMINAL_STATES:
            raise ValueError(f"unsupported terminal state: {state}")
        now = time.time()
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select * from requests where request_id=? and lease_id=? and state='running'", (request_id, lease_id)).fetchone()
            if row is None:
                return False
            final = "cancelled" if int(row["cancel_requested"] or 0) else state
            final_result = result if final != "cancelled" else dict(result, status="cancelled", ignored_result=True)
            conn.execute(
                """
                update requests set state=?, result_json=?, error=?, completed_at=?, updated_at=?,
                    lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null
                where request_id=? and lease_id=? and state='running'
                """,
                (final, json.dumps(final_result, sort_keys=True), None if final == "completed" else (error or final), now, now, request_id, lease_id),
            )
            if row["kv_key"]:
                conn.execute("update kv_entries set state='idle', last_used_at=?, updated_at=? where request_id=?", (now, now, request_id))
                conn.execute("update kv_shard_entries set state='idle', last_used_at=?, updated_at=? where request_id=?", (now, now, request_id))
            self._release_unused_compute_lease(conn, row["compute_lease_id"])
            self._event(conn, request_id, final, final, {"batch_id": row["batch_id"], "service_id": row["selected_service_id"]})
            self._refresh_batch(conn, str(row["batch_id"]))
        self._write_notice(request_id, final, final_result)
        return True

    def retry_transport_failure(self, *, request_id: str, lease_id: str, result: dict[str, Any], max_attempts: int) -> str:
        now = time.time()
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select * from requests where request_id=? and lease_id=? and state='running'", (request_id, lease_id)).fetchone()
            if row is None:
                return "lost"
            attempts = int(row["attempt_count"] or 0)
            error = _result_error(result) or "transport_failed"
            if int(row["cancel_requested"] or 0):
                final = dict(result, status="cancelled", ignored_result=True)
                conn.execute("update requests set state='cancelled', result_json=?, error=?, completed_at=?, updated_at=?, lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null where request_id=? and lease_id=? and state='running'", (json.dumps(final, sort_keys=True), "cancelled", now, now, request_id, lease_id))
                self._delete_request_kv(conn, request_id)
                self._release_unused_compute_lease(conn, row["compute_lease_id"])
                self._event(conn, request_id, "cancelled", "cancelled", {"batch_id": row["batch_id"], "after_transport_error": error})
                self._refresh_batch(conn, str(row["batch_id"]))
                self._write_notice(request_id, "cancelled", final)
                return "cancelled"
            if attempts < max_attempts:
                self._delete_request_kv(conn, request_id)
                conn.execute(
                    """
                    update requests set state='queued',
                        selected_node_id=case when selected_service_id is null then null else selected_node_id end,
                        selected_node_ids_json=case when selected_service_id is null then null else selected_node_ids_json end,
                        selected_compute_domain=case when selected_service_id is null then null else selected_compute_domain end,
                        ready_at=null, result_json=null, error=?, lease_id=null, compute_lease_id=null, leased_by=null,
                        lease_expires_at=null, heartbeat_at=null, updated_at=?
                    where request_id=? and lease_id=? and state='running'
                    """,
                    (error, now, request_id, lease_id),
                )
                self._release_unused_compute_lease(conn, row["compute_lease_id"])
                self._event(conn, request_id, "transport_requeued", "queued", {"batch_id": row["batch_id"], "attempt_count": attempts, "max_attempts": max_attempts, "error": error})
                self._refresh_batch(conn, str(row["batch_id"]))
                return "requeued"
            conn.execute("update requests set state='failed', result_json=?, error=?, completed_at=?, updated_at=?, lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null where request_id=? and lease_id=? and state='running'", (json.dumps(result, sort_keys=True), error, now, now, request_id, lease_id))
            self._delete_request_kv(conn, request_id)
            self._release_unused_compute_lease(conn, row["compute_lease_id"])
            self._event(conn, request_id, "failed", "failed", {"batch_id": row["batch_id"], "attempt_count": attempts, "error": error})
            self._refresh_batch(conn, str(row["batch_id"]))
        self._write_notice(request_id, "failed", result)
        return "failed"

    def cancel(self, *, request_id: str | None = None, batch_id: str | None = None, job_id: str | None = None, reason: str = "cancelled by operator", force_running: bool = False) -> dict[str, Any]:
        batch_id = job_batch_id(batch_id=batch_id, job_id=job_id)
        if sum(x is not None for x in (request_id, batch_id)) != 1:
            raise ValueError("exactly one of request_id, batch_id, or job_id is required")
        now = time.time()
        cancelled: list[str] = []
        cancel_requested: list[str] = []
        skipped: dict[str, int] = {}
        with closing(self._connect()) as conn, conn:
            rows = conn.execute("select * from requests where request_id=?" if request_id else "select * from requests where batch_id=? order by request_id", (request_id or batch_id,)).fetchall()
            for row in rows:
                rid = str(row["request_id"])
                state = str(row["state"])
                if state in TERMINAL_STATES:
                    skipped[state] = skipped.get(state, 0) + 1
                    continue
                if state == "running":
                    conn.execute("update requests set cancel_requested=1, updated_at=? where request_id=?", (now, rid))
                    cancel_requested.append(rid)
                    continue
                result = {"format": "ds4-inference-cancelled-v1", "request_id": rid, "status": "cancelled", "reason": reason}
                conn.execute("update requests set state='cancelled', result_json=?, error=?, completed_at=?, updated_at=? where request_id=?", (json.dumps(result, sort_keys=True), reason, now, now, rid))
                self._delete_request_kv(conn, rid)
                self._release_unused_compute_lease(conn, row["compute_lease_id"])
                self._event(conn, rid, "cancelled", "cancelled", {"batch_id": row["batch_id"], "reason": reason})
                self._write_notice(rid, "cancelled", result)
                cancelled.append(rid)
            for bid in {str(row["batch_id"]) for row in rows}:
                self._refresh_batch(conn, bid)
        state = "cancelled" if cancelled and not skipped and not cancel_requested else "partial" if cancelled or cancel_requested else "unchanged"
        return {
            "format": QUEUE_FORMAT,
            "state": state,
            "request_id": request_id,
            "batch_id": batch_id,
            "job_id": batch_id,
            "cancelled_count": len(cancelled),
            "cancelled_request_ids": cancelled,
            "running_cancel_requested_count": len(cancel_requested),
            "running_cancel_requested_ids": cancel_requested,
            "skipped_state_counts": skipped,
        }

    def requeue_expired_leases(self, *, max_attempts: int = 3, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        requeued = failed = 0
        with closing(self._connect()) as conn, conn:
            conn.execute("delete from compute_leases where lease_expires_at <= ? and compute_lease_id not in (select coalesce(compute_lease_id, '') from requests where state='running')", (now,))
            rows = conn.execute("select * from requests where state in ('prefilling','running') and lease_expires_at is not null and lease_expires_at <= ? order by lease_expires_at, request_id", (now,)).fetchall()
            for row in rows:
                attempts = int(row["attempt_count"] or 0)
                state = "failed" if attempts >= max_attempts else "queued"
                if state == "queued":
                    requeued += 1
                    self._delete_request_kv(conn, str(row["request_id"]))
                    conn.execute("update requests set state='queued', selected_node_id=case when selected_service_id is null then null else selected_node_id end, selected_node_ids_json=case when selected_service_id is null then null else selected_node_ids_json end, selected_compute_domain=case when selected_service_id is null then null else selected_compute_domain end, lease_id=null, compute_lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null, updated_at=? where request_id=?", (now, row["request_id"]))
                else:
                    failed += 1
                    result = _failure(str(row["request_id"]), f"lease expired after {attempts} attempts")
                    conn.execute("update requests set state='failed', result_json=?, error='lease_expired', completed_at=?, updated_at=?, lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null where request_id=?", (json.dumps(result, sort_keys=True), now, now, row["request_id"]))
                    self._write_notice(str(row["request_id"]), "failed", result)
                self._release_unused_compute_lease(conn, row["compute_lease_id"])
                self._event(conn, str(row["request_id"]), "lease_expired", state, {"batch_id": row["batch_id"], "attempt_count": attempts})
                self._refresh_batch(conn, str(row["batch_id"]))
        return {"format": QUEUE_FORMAT, "state": "reaped" if requeued or failed else "idle", "requeued_count": requeued, "failed_count": failed}

    def recover_jit_kv_startup(self, *, stale_s: float = 0.0, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with closing(self._connect()) as conn, conn:
            wait_released = self._release_prefilling_locked(conn, reason="startup_recovery", stale_s=stale_s, now=now)
            objects_recovered, shards_recovered = self._recover_prefetch_manifests_locked(conn, stale_s=stale_s, now=now)
        return {
            "format": QUEUE_FORMAT,
            "state": "recovered" if wait_released or objects_recovered or shards_recovered else "idle",
            "wait_released": wait_released,
            "objects_recovered": objects_recovered,
            "shards_recovered": shards_recovered,
        }

    def release_jit_kv_waits(self, *, reason: str = "jit_kv_circuit_open", now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with closing(self._connect()) as conn, conn:
            wait_released = self._release_prefilling_locked(conn, reason=reason, stale_s=0.0, now=now)
        return {"format": QUEUE_FORMAT, "state": "released" if wait_released else "idle", "wait_released": wait_released}

    def heartbeat(self, *, lease_ids: Iterable[str], lease_ttl_s: int) -> int:
        ids = [str(lease_id) for lease_id in lease_ids if lease_id]
        if not ids:
            return 0
        now = time.time()
        with closing(self._connect()) as conn, conn:
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(f"select distinct compute_lease_id from requests where state='running' and lease_id in ({placeholders}) and compute_lease_id is not null", tuple(ids)).fetchall()
            compute_lease_ids = [str(row["compute_lease_id"]) for row in rows if row["compute_lease_id"]]
            count = int(
                conn.execute(
                    f"update requests set heartbeat_at=?, lease_expires_at=?, updated_at=? where state='running' and lease_id in ({placeholders})",
                    (now, now + lease_ttl_s, now, *ids),
                ).rowcount
            )
            if compute_lease_ids:
                compute_placeholders = ",".join("?" for _ in compute_lease_ids)
                conn.execute(
                    f"update compute_leases set heartbeat_at=?, lease_expires_at=?, updated_at=? where compute_lease_id in ({compute_placeholders})",
                    (now, now + lease_ttl_s, now, *compute_lease_ids),
                )
            return count

    def status(self, *, request_id: str | None = None, batch_id: str | None = None, job_id: str | None = None, refresh: bool = True) -> dict[str, Any]:
        batch_id = job_batch_id(batch_id=batch_id, job_id=job_id)
        with closing(self._connect()) as conn, conn:
            if request_id is not None:
                row = conn.execute("select * from requests where request_id=?", (request_id,)).fetchone()
                return {"format": REQUEST_STATUS_FORMAT, "request_id": request_id, "state": "unknown"} if row is None else _request_status(row)
            if batch_id is not None:
                if refresh:
                    self._refresh_batch(conn, batch_id)
                row = conn.execute("select * from batches where batch_id=?", (batch_id,)).fetchone()
                return {"format": BATCH_STATUS_FORMAT, "batch_id": batch_id, "job_id": batch_id, "state": "unknown"} if row is None else _batch_status(row)
            counts = {str(r["state"]): int(r["n"]) for r in conn.execute("select state,count(*) n from requests group by state order by state")}
            event = conn.execute("select max(event_id) newest from events").fetchone()
            leases = [dict(row) for row in conn.execute("select * from compute_leases order by compute_domain")]
            return {"format": QUEUE_FORMAT, "state_counts": counts, "newest_event_id": int(event["newest"] or 0), "active_compute_leases": leases, "pipeline_status": self._pipeline_status_locked(conn)}

    def service_state_counts(self) -> dict[str, Any]:
        terminal = set(TERMINAL_STATES)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                select coalesce(selected_service_id,'unassigned') service_id,state,count(*) n
                from requests
                group by coalesce(selected_service_id,'unassigned'),state
                order by service_id,state
                """
            ).fetchall()
        by_service: dict[str, dict[str, int]] = {}
        unfinished: dict[str, int] = {}
        running: dict[str, int] = {}
        for row in rows:
            service_id = str(row["service_id"] or "unassigned")
            state = str(row["state"])
            count = int(row["n"])
            by_service.setdefault(service_id, {})[state] = count
            if state not in terminal:
                unfinished[service_id] = int(unfinished.get(service_id, 0)) + count
            if state == "running":
                running[service_id] = count
        return {
            "format": QUEUE_FORMAT,
            "state_counts_by_service": by_service,
            "unfinished_by_service": unfinished,
            "running_by_service": running,
        }

    def usage(self, *, window_s: float = 300.0, now: float | None = None, limit: int = 10000) -> dict[str, Any]:
        window = max(1.0, min(86400.0, float(window_s)))
        end_ts = time.time() if now is None else float(now)
        start_ts = end_ts - window
        row_limit = max(1, min(100000, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                select request_id,result_json,completed_at from requests
                where state='completed' and completed_at is not null and completed_at>=? and completed_at<=?
                order by completed_at desc limit ?
                """,
                (start_ts,end_ts,row_limit),
            ).fetchall()
        prompt = 0
        completion = 0
        total = 0
        usage_count = 0
        for row in rows:
            try:
                result = json.loads(str(row["result_json"])) if row["result_json"] else {}
            except Exception:
                result = {}
            p, c, t = _result_usage_tokens(result if isinstance(result, dict) else {})
            prompt += p
            completion += c
            total += t
            if p > 0 or c > 0 or t > 0:
                usage_count += 1
        return {
            "format": QUEUE_FORMAT,
            "window_s": window,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "completed_count": len(rows),
            "usage_count": usage_count,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "prompt_tok_s": round(prompt / window,6),
            "completion_tok_s": round(completion / window,6),
            "total_tok_s": round(total / window,6),
        }

    def unfinished_request_count(self, request_ids: Iterable[str]) -> int:
        ids = tuple(str(request_id) for request_id in request_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        terminal = tuple(sorted(TERMINAL_STATES))
        terminal_placeholders = ",".join("?" for _ in terminal)
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"select count(*) n from requests where request_id in ({placeholders}) and state not in ({terminal_placeholders})",
                ids + terminal,
            ).fetchone()
        return int(row["n"] if row else 0)

    def poll(self, *, after_event_id: int = 0, limit: int = 100) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            rows = conn.execute("select * from events where event_id>? order by event_id limit ?", (after_event_id, limit)).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(str(row["payload_json"]))
            events.append(event)
        return {"format": QUEUE_FORMAT, "events": events, "newest_event_id": max([after_event_id] + [int(e["event_id"]) for e in events])}

    def stream_delta(self, *, request_id: str, text: str, payload: dict[str, Any] | None = None) -> None:
        if not text:
            return
        data = dict(payload or {})
        data["text"] = text
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select state from requests where request_id=?", (request_id,)).fetchone()
            state = str(row["state"] if row else "running")
            self._event(conn, request_id, "delta", state, data)

    def collect(self, *, request_id: str | None = None, batch_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
        batch_id = job_batch_id(batch_id=batch_id, job_id=job_id)
        if sum(x is not None for x in (request_id, batch_id)) != 1:
            raise ValueError("exactly one of request_id, batch_id, or job_id is required")
        with closing(self._connect()) as conn:
            rows = conn.execute("select * from requests where request_id=?" if request_id else "select * from requests where batch_id=? order by request_id", (request_id or batch_id,)).fetchall()
        results = [{"request": _request_status(row), "result": json.loads(str(row["result_json"])) if row["result_json"] else None} for row in rows]
        if request_id:
            return results[0] if results else {"format": QUEUE_FORMAT, "request_id": request_id, "state": "unknown"}
        return {"format": QUEUE_FORMAT, "batch_id": batch_id, "job_id": batch_id, "results": results}

    def record_pipeline_telemetry(self, report: dict[str, Any]) -> dict[str, Any]:
        if isinstance(report.get("stages"), list):
            results = []
            for item in report["stages"]:
                if not isinstance(item, dict):
                    raise ValueError("pipeline telemetry stages must be objects")
                merged = dict(report)
                merged.pop("stages", None)
                merged.update(item)
                results.append(self.record_pipeline_telemetry(merged))
            return {"format": PIPELINE_STATUS_FORMAT, "state": "reported", "stage_count": len(results), "results": results}
        if isinstance(report.get("payload"), dict):
            payload = dict(report["payload"])
        elif report.get("payload_json") is not None:
            raw_payload = report.get("payload_json")
            payload = json.loads(str(raw_payload)) if isinstance(raw_payload, str) else raw_payload
            if not isinstance(payload, dict):
                raise ValueError("pipeline telemetry payload_json must decode to an object")
        else:
            payload = {
                key: value
                for key, value in report.items()
                if key not in {"service_id", "node_id", "stage_index", "stage_count", "layer_start", "layer_end", "kv_shard_bytes", "reported_at"}
            }
        return self.report_pipeline_telemetry(
            service_id=str(report["service_id"]),
            node_id=str(report["node_id"]),
            stage_index=int(report["stage_index"]),
            stage_count=int(report["stage_count"]),
            layer_start=int(report["layer_start"]) if report.get("layer_start") is not None else None,
            layer_end=int(report["layer_end"]) if report.get("layer_end") is not None else None,
            kv_shard_bytes=int(report.get("kv_shard_bytes", 0) or 0),
            payload=payload,
            reported_at=float(report["reported_at"]) if report.get("reported_at") is not None else None,
        )

    def report_pipeline_telemetry(self, *, service_id: str, node_id: str, stage_index: int, stage_count: int, layer_start: int | None = None, layer_end: int | None = None, kv_shard_bytes: int = 0, payload: dict[str, Any] | None = None, reported_at: float | None = None) -> dict[str, Any]:
        if stage_index < 0 or stage_count < 1 or stage_index >= stage_count:
            raise ValueError("invalid pipeline stage index/count")
        layer_count = None if layer_start is None or layer_end is None else int(layer_end) - int(layer_start)
        now = time.time() if reported_at is None else float(reported_at)
        body = dict(payload or {})
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                insert or replace into pipeline_telemetry(service_id,node_id,stage_index,stage_count,layer_start,layer_end,layer_count,kv_shard_bytes,payload_json,reported_at)
                values (?,?,?,?,?,?,?,?,?,?)
                """,
                (service_id, node_id, stage_index, stage_count, layer_start, layer_end, layer_count, max(0, int(kv_shard_bytes)), json.dumps(body, sort_keys=True), now),
            )
        return {"format": PIPELINE_STATUS_FORMAT, "state": "reported", "service_id": service_id, "node_id": node_id, "stage_index": stage_index, "reported_at": now}

    def pipeline_status(self, *, service_id: str | None = None) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            return self._pipeline_status_locked(conn, service_id=service_id)

    def _pipeline_status_locked(self, conn: sqlite3.Connection, *, service_id: str | None = None) -> dict[str, Any]:
        params: tuple[Any, ...] = (service_id,) if service_id else ()
        where = "where service_id=?" if service_id else ""
        rows = conn.execute(f"select * from pipeline_telemetry {where} order by service_id, stage_index, node_id", params).fetchall()
        kv_rows = conn.execute(f"""
            select service_id,node_id,stage_index,stage_count,min(layer_start) layer_start,max(layer_end) layer_end,
                   count(*) entries,coalesce(sum(bytes),0) bytes
            from kv_shard_entries {where}
            group by service_id,node_id,stage_index,stage_count
            order by service_id,stage_index,node_id
        """, params).fetchall()
        leases = conn.execute("select * from compute_leases order by compute_domain").fetchall()
        return {
            "format": PIPELINE_STATUS_FORMAT,
            "service_id": service_id,
            "stages": [_telemetry_status(row) for row in rows],
            "kv_shards": [dict(row) for row in kv_rows],
            "active_compute_leases": [dict(row) for row in leases],
        }

    def upsert_external_kv_object(
        self,
        *,
        namespace: str,
        kv_key: str,
        service_id: str,
        profile_id: str | None = None,
        model_id: str | None = None,
        owner: str | None = None,
        content_hash: str | None = None,
        total_bytes: int = 0,
        total_tokens: int = 0,
        state: str = "declared",
        pin_count: int = 0,
        priority: int = 100,
        ttl_s: float | None = None,
        metadata: dict[str, Any] | None = None,
        shards: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        service_id = _require_service_id(service_id)
        now = time.time()
        ttl_expires_at = None if ttl_s is None else now + max(0.0, float(ttl_s))
        shard_list = [dict(shard) for shard in shards]
        validate_external_kv_shards(shard_list, total_bytes=total_bytes)
        _validate_external_kv_partition_fingerprint(metadata or {}, shard_list)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                insert into kv_memory_objects(namespace,kv_key,service_id,profile_id,model_id,owner,content_hash,total_bytes,total_tokens,state,pin_count,priority,ttl_expires_at,metadata_json,created_at,updated_at,last_used_at)
                values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(namespace,kv_key,service_id) do update set
                    profile_id=excluded.profile_id, model_id=excluded.model_id, owner=excluded.owner,
                    content_hash=excluded.content_hash, total_bytes=excluded.total_bytes, total_tokens=excluded.total_tokens,
                    state=excluded.state, pin_count=excluded.pin_count, priority=excluded.priority,
                    ttl_expires_at=excluded.ttl_expires_at, metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at, last_used_at=excluded.last_used_at
                """,
                (
                    namespace,
                    kv_key,
                    service_id,
                    profile_id,
                    model_id,
                    owner,
                    content_hash,
                    max(0, int(total_bytes)),
                    max(0, int(total_tokens)),
                    state,
                    max(0, int(pin_count)),
                    int(priority),
                    ttl_expires_at,
                    json.dumps(dict(metadata or {}), sort_keys=True),
                    now,
                    now,
                    now,
                ),
            )
            conn.execute("delete from kv_memory_shards where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id))
            for shard in shard_list:
                conn.execute(
                    """
                    insert into kv_memory_shards(namespace,kv_key,service_id,node_id,stage_index,stage_count,layer_start,layer_end,bytes,state,storage_uri,gpu_resident,metadata_json,created_at,updated_at,last_used_at)
                    values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        namespace,
                        kv_key,
                        service_id,
                        str(shard["node_id"]),
                        int(shard.get("stage_index", 0) or 0),
                        int(shard.get("stage_count", len(shard_list)) or len(shard_list)),
                        int(shard["layer_start"]) if shard.get("layer_start") is not None else None,
                        int(shard["layer_end"]) if shard.get("layer_end") is not None else None,
                        max(0, int(shard.get("bytes", 0) or 0)),
                        str(shard.get("state") or state),
                        str(shard["storage_uri"]) if shard.get("storage_uri") is not None else None,
                        1 if bool(shard.get("gpu_resident", False)) else 0,
                        json.dumps(dict(shard.get("metadata") or {}), sort_keys=True),
                        now,
                        now,
                        now,
                    ),
                )
        return self.external_kv_lookup(namespace=namespace, kv_key=kv_key, service_id=service_id)

    def external_kv_lookup(self, *, namespace: str, kv_key: str, service_id: str | None = None) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        with closing(self._connect()) as conn:
            conn.execute("delete from kv_memory_leases where expires_at <= ?", (time.time(),))
            object_rows = _external_kv_object_rows(conn, namespace=namespace, kv_key=kv_key, service_id=service_id)
            objects = [_external_kv_manifest(conn, row) for row in object_rows]
        if service_id is not None:
            return objects[0] if objects else {"format": "ds4-external-kv-cache-object-v1", "state": "missing", "namespace": namespace, "kv_key": kv_key, "service_id": service_id}
        return {"format": "ds4-external-kv-cache-lookup-v1", "namespace": namespace, "kv_key": kv_key, "objects": objects, "state": "found" if objects else "missing"}

    def external_kv_list(
        self,
        *,
        namespace: str = "default",
        service_id: str | None = None,
        owner: str | None = None,
        state: str | None = None,
        prefix: str | None = None,
        include_shards: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        clauses = ["namespace=?"]
        params: list[Any] = [namespace]
        if service_id is not None:
            clauses.append("service_id=?")
            params.append(str(service_id))
        if owner is not None:
            clauses.append("owner=?")
            params.append(str(owner))
        if state is not None:
            clauses.append("state=?")
            params.append(str(state))
        if prefix is not None:
            clauses.append("kv_key like ?")
            params.append(str(prefix) + "%")
        params.append(max(1, min(10000, int(limit))))
        with closing(self._connect()) as conn:
            conn.execute("delete from kv_memory_leases where expires_at <= ?", (time.time(),))
            rows = conn.execute(
                f"select * from kv_memory_objects where {' and '.join(clauses)} order by priority, last_used_at desc, updated_at desc limit ?",
                tuple(params),
            ).fetchall()
            objects = [_external_kv_manifest(conn, row) if include_shards else _external_kv_object_summary(row) for row in rows]
        return {
            "format": "ds4-external-kv-cache-list-v1",
            "namespace": namespace,
            "service_id": service_id,
            "owner": owner,
            "state": state,
            "prefix": prefix,
            "objects": objects,
            "count": len(objects),
        }

    def external_kv_touch(
        self,
        *,
        namespace: str,
        kv_key: str,
        service_id: str,
        owner: str | None = None,
        state: str | None = None,
        priority: int | None = None,
        ttl_s: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        service_id = _require_service_id(service_id)
        now = time.time()
        ttl_expires_at = None if ttl_s is None else now + max(0.0, float(ttl_s))
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select * from kv_memory_objects where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchone()
            if row is None:
                raise ValueError("external KV object is missing")
            existing = json.loads(str(row["metadata_json"] or "{}"))
            if metadata:
                existing.update(metadata)
            clauses = ["metadata_json=?", "updated_at=?", "last_used_at=?"]
            params: list[Any] = [json.dumps(existing, sort_keys=True), now, now]
            if owner is not None:
                clauses.append("owner=?")
                params.append(str(owner))
            if state is not None:
                clauses.append("state=?")
                params.append(str(state))
            if priority is not None:
                clauses.append("priority=?")
                params.append(int(priority))
            if ttl_s is not None:
                clauses.append("ttl_expires_at=?")
                params.append(ttl_expires_at)
            params.extend([namespace, kv_key, service_id])
            conn.execute(f"update kv_memory_objects set {', '.join(clauses)} where namespace=? and kv_key=? and service_id=?", tuple(params))
            conn.execute("update kv_memory_shards set updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (now, now, namespace, kv_key, service_id))
        return self.external_kv_lookup(namespace=namespace, kv_key=kv_key, service_id=service_id)

    def external_kv_lease(self, *, namespace: str, kv_key: str, service_id: str, owner: str | None = None, mode: str = "read", ttl_s: float = 300.0) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        service_id = _require_service_id(service_id)
        if mode not in {"read", "write", "prefetch", "pin"}:
            raise ValueError("unsupported external KV lease mode")
        now = time.time()
        lease_id = f"kvlease-{uuid.uuid4().hex}"
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select * from kv_memory_objects where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchone()
            if row is None:
                raise ValueError("external KV object is missing")
            conn.execute("delete from kv_memory_leases where expires_at <= ?", (now,))
            conn.execute(
                "insert into kv_memory_leases(lease_id,namespace,kv_key,service_id,mode,owner,expires_at,created_at,updated_at) values (?,?,?,?,?,?,?,?,?)",
                (lease_id, namespace, kv_key, service_id, mode, owner, now + max(1.0, float(ttl_s)), now, now),
            )
            conn.execute("update kv_memory_objects set last_used_at=?, updated_at=? where namespace=? and kv_key=? and service_id=?", (now, now, namespace, kv_key, service_id))
            conn.execute("update kv_memory_shards set last_used_at=?, updated_at=? where namespace=? and kv_key=? and service_id=?", (now, now, namespace, kv_key, service_id))
            manifest = _external_kv_manifest(conn, row)
        manifest["lease"] = {"lease_id": lease_id, "mode": mode, "owner": owner, "expires_at": now + max(1.0, float(ttl_s))}
        return manifest

    def external_kv_release(self, *, lease_id: str) -> dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            deleted = conn.execute("delete from kv_memory_leases where lease_id=?", (str(lease_id),)).rowcount
        return {"format": "ds4-external-kv-cache-lease-v1", "lease_id": str(lease_id), "released": bool(deleted)}

    def external_kv_transition(self, *, namespace: str, kv_key: str, service_id: str, state: str, shard_state: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        service_id = _require_service_id(service_id)
        now = time.time()
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select * from kv_memory_objects where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchone()
            if row is None:
                raise ValueError("external KV object is missing")
            existing = json.loads(str(row["metadata_json"] or "{}"))
            if metadata:
                existing.update(metadata)
            conn.execute("update kv_memory_objects set state=?, metadata_json=?, updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (state, json.dumps(existing, sort_keys=True), now, now, namespace, kv_key, service_id))
            if shard_state is not None:
                conn.execute("update kv_memory_shards set state=?, updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (shard_state, now, now, namespace, kv_key, service_id))
        return self.external_kv_lookup(namespace=namespace, kv_key=kv_key, service_id=service_id)

    def external_kv_pin(self, *, namespace: str, kv_key: str, service_id: str, delta: int) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        service_id = _require_service_id(service_id)
        now = time.time()
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select pin_count from kv_memory_objects where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchone()
            if row is None:
                raise ValueError("external KV object is missing")
            pin_count = max(0, int(row["pin_count"] or 0) + int(delta))
            conn.execute("update kv_memory_objects set pin_count=?, updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (pin_count, now, now, namespace, kv_key, service_id))
        return self.external_kv_lookup(namespace=namespace, kv_key=kv_key, service_id=service_id)

    def external_kv_evict(self, *, namespace: str, kv_key: str, service_id: str, reason: str | None = None) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        service_id = _require_service_id(service_id)
        now = time.time()
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select pin_count from kv_memory_objects where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchone()
            if row is None:
                return {"format": "ds4-external-kv-cache-object-v1", "state": "missing", "namespace": namespace, "kv_key": kv_key, "service_id": service_id}
            if int(row["pin_count"] or 0) > 0:
                raise ValueError("cannot evict a pinned external KV object")
            metadata = {"evicted_reason": reason or "operator"}
            conn.execute("update kv_memory_objects set state='evicted', metadata_json=?, updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (json.dumps(metadata, sort_keys=True), now, now, namespace, kv_key, service_id))
            conn.execute("update kv_memory_shards set state='evicted', gpu_resident=0, updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (now, now, namespace, kv_key, service_id))
        return self.external_kv_lookup(namespace=namespace, kv_key=kv_key, service_id=service_id)

    def external_kv_commit_shards(self, *, namespace: str, kv_key: str, service_id: str, object_state: str = "available", shard_state: str = "ready_on_ssd", shard_updates: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        kv_key = _require_kv_key(kv_key)
        service_id = _require_service_id(service_id)
        now = time.time()
        updates = [dict(item) for item in shard_updates]
        with closing(self._connect()) as conn, conn:
            row = conn.execute("select * from kv_memory_objects where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchone()
            if row is None:
                raise ValueError("external KV object is missing")
            if not updates:
                conn.execute("update kv_memory_shards set state=?, updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (shard_state, now, now, namespace, kv_key, service_id))
            for update in updates:
                changed = update_external_kv_shard(conn, namespace=namespace, kv_key=kv_key, service_id=service_id, update=update, default_state=shard_state, now=now)
                if changed != 1 and (update.get("node_id") is not None or update.get("stage_index") is not None):
                    raise ValueError(f"expected exactly one external KV shard update, changed {changed}")
            object_state = external_kv_object_state_from_shards(conn, namespace=namespace, kv_key=kv_key, service_id=service_id, requested_state=object_state)
            conn.execute("update kv_memory_objects set state=?, total_bytes=(select coalesce(sum(bytes),0) from kv_memory_shards where namespace=? and kv_key=? and service_id=?), updated_at=?, last_used_at=? where namespace=? and kv_key=? and service_id=?", (object_state, namespace, kv_key, service_id, now, now, namespace, kv_key, service_id))
        return self.external_kv_lookup(namespace=namespace, kv_key=kv_key, service_id=service_id)


    def _existing_submission(self, batch_id: str, requests: list[InferenceRequest], priority: int | None) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            rows = conn.execute("select request_id,priority,selected_profile_id,selected_node_id,selected_service_id,request_json,request_json_hash from requests where batch_id=? order by request_id", (batch_id,)).fetchall()
        if not rows:
            return None
        ids = sorted(req.request_id for req in requests)
        existing = sorted(str(row["request_id"]) for row in rows)
        if ids != existing:
            raise ValueError(f"batch_id already exists with different requests: {batch_id}")
        expected = {req.request_id: request_priority(req, priority_override=priority) for req in requests}
        existing_priorities = {str(row["request_id"]): int(row["priority"]) for row in rows}
        mismatches = sorted(rid for rid, prio in expected.items() if existing_priorities.get(rid) != prio)
        if mismatches:
            raise ValueError(f"batch_id already exists with different priority for requests: {mismatches}")
        expected_hashes = {req.request_id: _request_json_hash(_canonical_request_json(req.raw)) for req in requests}
        existing_hashes: dict[str, str] = {}
        for row in rows:
            stored = row["request_json_hash"]
            if not stored:
                stored = _request_json_hash(_canonical_existing_request_json(str(row["request_json"])))
            existing_hashes[str(row["request_id"])] = str(stored)
        payload_mismatches = sorted(rid for rid, digest in expected_hashes.items() if existing_hashes.get(rid) != digest)
        if payload_mismatches:
            raise ValueError(f"batch_id already exists with different request payloads: {payload_mismatches}")
        return {"format": QUEUE_FORMAT, "state": "queued", "batch_id": batch_id, "job_id": batch_id, "request_ids": existing, "request_count": len(existing), "selected_profiles": _count(row["selected_profile_id"] for row in rows), "selected_nodes": _count(row["selected_node_id"] for row in rows if row["selected_node_id"]), "selected_services": _count(row["selected_service_id"] for row in rows if row["selected_service_id"]), "priority_counts": {str(k): v for k, v in _count(int(row["priority"]) for row in rows).items()}}

    def _reserve_kv(self, conn: sqlite3.Connection, row: sqlite3.Row, *, node_id: str | None, capacity: int, now: float, pipeline_layout: Any | None = None) -> bool:
        key = row["kv_key"]
        need = int(row["kv_bytes"] or 0)
        if not key or need <= 0:
            return True
        service_id = str(row["selected_service_id"] or "")
        node_ids = _row_node_ids(row, fallback_node_id=node_id)
        if service_id and len(node_ids) > 1:
            return self._reserve_pipeline_kv(conn, row, service_id=service_id, node_ids=node_ids, key=str(key), need=need, capacity=capacity, now=now, pipeline_layout=pipeline_layout)
        return self._reserve_legacy_kv(conn, row, node_id=node_id, key=str(key), need=need, capacity=capacity, now=now)

    def _reserve_legacy_kv(self, conn: sqlite3.Connection, row: sqlite3.Row, *, node_id: str | None, key: str, need: int, capacity: int, now: float) -> bool:
        if node_id is None:
            return False
        victims = _kv_victims_to_fit(conn, table="kv_entries", service_id=None, node_id=node_id, need=need, capacity=capacity)
        if victims is None:
            return False
        for victim in victims:
            conn.execute("delete from kv_entries where node_id=? and kv_key=?", (node_id, victim))
        conn.execute("insert or replace into kv_entries(node_id,kv_key,request_id,bytes,state,last_used_at,created_at,updated_at) values (?,?,?,?,?,?,?,?)", (node_id, key, row["request_id"], need, "ready", now, now, now))
        return True

    def _reserve_pipeline_kv(self, conn: sqlite3.Connection, row: sqlite3.Row, *, service_id: str, node_ids: tuple[str, ...], key: str, need: int, capacity: int, now: float, pipeline_layout: Any | None = None) -> bool:
        if pipeline_layout is not None and hasattr(pipeline_layout, "cache_shards"):
            shards = list(pipeline_layout.cache_shards(request_id=str(row["request_id"]), kv_key=key, total_bytes=need))
        else:
            shard_bytes = int(row["kv_shard_bytes"] or ceil(need / max(1, len(node_ids))))
            shards = [
                {
                    "service_id": service_id,
                    "node_id": stage_node,
                    "stage_index": stage_index,
                    "stage_count": len(node_ids),
                    "layer_start": None,
                    "layer_end": None,
                    "bytes": shard_bytes,
                }
                for stage_index, stage_node in enumerate(node_ids)
            ]
        if not shards:
            return True
        evictions: list[tuple[str, list[str]]] = []
        for shard in shards:
            node_id = str(shard["node_id"])
            shard_bytes = max(0, int(shard.get("bytes", 0) or 0))
            victims = _kv_victims_to_fit(conn, table="kv_shard_entries", service_id=service_id, node_id=node_id, need=shard_bytes, capacity=capacity)
            if victims is None:
                return False
            evictions.append((node_id, victims))
        for node_id, victims in evictions:
            for victim in victims:
                conn.execute("delete from kv_shard_entries where service_id=? and node_id=? and kv_key=?", (service_id, node_id, victim))
        stage_count = max(1, len(shards))
        shard_bytes_values: list[int] = []
        for shard in shards:
            node_id = str(shard["node_id"])
            shard_bytes = max(0, int(shard.get("bytes", 0) or 0))
            shard_bytes_values.append(shard_bytes)
            conn.execute(
                """
                insert or replace into kv_shard_entries(service_id,node_id,kv_key,request_id,stage_index,stage_count,layer_start,layer_end,bytes,state,last_used_at,created_at,updated_at)
                values (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    service_id,
                    node_id,
                    key,
                    row["request_id"],
                    int(shard.get("stage_index", 0) or 0),
                    int(shard.get("stage_count", stage_count) or stage_count),
                    int(shard["layer_start"]) if shard.get("layer_start") is not None else None,
                    int(shard["layer_end"]) if shard.get("layer_end") is not None else None,
                    shard_bytes,
                    "ready",
                    now,
                    now,
                    now,
                ),
            )
        conn.execute("update requests set kv_shard_count=?, kv_shard_bytes=? where request_id=?", (stage_count, max(shard_bytes_values) if shard_bytes_values else 0, row["request_id"]))
        return True

    def _acquire_compute_lease(self, conn: sqlite3.Connection, *, rows: list[sqlite3.Row], leased_by: str, lease_ttl_s: int, now: float) -> str | None | bool:
        domain = str(rows[0]["selected_compute_domain"] or "")
        if not domain:
            return None
        conn.execute("delete from compute_leases where lease_expires_at <= ?", (now,))
        service_id = str(rows[0]["selected_service_id"] or "") or None
        existing = conn.execute("select * from compute_leases where compute_domain=?", (domain,)).fetchone()
        if existing is not None:
            existing_service_id = str(existing["service_id"] or "") or None
            if existing_service_id == service_id and str(existing["leased_by"]) == leased_by:
                if _compute_lease_should_drain(conn, existing, now=now):
                    return False
                conn.execute(
                    """
                    update compute_leases set lease_expires_at=?, heartbeat_at=?, request_count=request_count+?, updated_at=?
                    where compute_domain=? and compute_lease_id=?
                    """,
                    (now + lease_ttl_s, now, len(rows), now, domain, existing["compute_lease_id"]),
                )
                return str(existing["compute_lease_id"])
            return False
        compute_lease_id = f"{leased_by}:compute:{uuid.uuid4().hex}"
        conn.execute(
            """
            insert into compute_leases(compute_domain,compute_lease_id,service_id,leased_by,lease_expires_at,heartbeat_at,request_count,created_at,updated_at)
            values (?,?,?,?,?,?,?,?,?)
            """,
            (domain, compute_lease_id, service_id, leased_by, now + lease_ttl_s, now, len(rows), now, now),
        )
        return compute_lease_id

    def _extend_compute_lease(self, conn: sqlite3.Connection, *, rows: list[sqlite3.Row], compute_lease_id: str | None, leased_by: str, lease_ttl_s: int, now: float) -> str | None | bool:
        domain = str(rows[0]["selected_compute_domain"] or "")
        if not domain:
            return None
        if not compute_lease_id:
            return False
        row = conn.execute("select * from compute_leases where compute_lease_id=? and lease_expires_at>?", (compute_lease_id, now)).fetchone()
        if row is None:
            return False
        service_id = str(rows[0]["selected_service_id"] or "")
        if str(row["compute_domain"] or "") != domain:
            return False
        if str(row["leased_by"] or "") != leased_by:
            return False
        if str(row["service_id"] or "") != service_id:
            return False
        if _compute_lease_should_drain(conn, row, now=now):
            return False
        conn.execute(
            """
            update compute_leases set lease_expires_at=?, heartbeat_at=?, request_count=request_count+?,
                updated_at=? where compute_lease_id=?
            """,
            (now + lease_ttl_s, now, len(rows), now, compute_lease_id),
        )
        return compute_lease_id

    def _release_unused_compute_lease(self, conn: sqlite3.Connection, compute_lease_id: Any) -> None:
        if not compute_lease_id:
            return
        row = conn.execute("select count(*) n from requests where state='running' and compute_lease_id=?", (compute_lease_id,)).fetchone()
        if int(row["n"] if row else 0) == 0:
            conn.execute("delete from compute_leases where compute_lease_id=?", (compute_lease_id,))

    def _release_prefilling_locked(self, conn: sqlite3.Connection, *, reason: str, stale_s: float, now: float) -> int:
        clauses = ["state='prefilling'"]
        params: list[Any] = []
        if stale_s > 0:
            clauses.append("updated_at<=?")
            params.append(now - float(stale_s))
        rows = conn.execute(f"select request_id,batch_id,compute_lease_id from requests where {' and '.join(clauses)} order by updated_at,request_id", tuple(params)).fetchall()
        if not rows:
            return 0
        request_ids = [str(row["request_id"]) for row in rows]
        placeholders = ",".join("?" for _ in request_ids)
        conn.execute(
            f"""
            update requests set state='queued',
                selected_node_id=case when selected_service_id is null then null else selected_node_id end,
                selected_node_ids_json=case when selected_service_id is null then null else selected_node_ids_json end,
                selected_compute_domain=case when selected_service_id is null then null else selected_compute_domain end,
                lease_id=null, compute_lease_id=null, leased_by=null, lease_expires_at=null,
                heartbeat_at=null, ready_at=null, updated_at=?
            where request_id in ({placeholders})
            """,
            tuple([now] + request_ids),
        )
        for row in rows:
            self._event(conn, str(row["request_id"]), "jit_kv_recovered", "queued", {"batch_id": row["batch_id"], "reason": reason})
            self._release_unused_compute_lease(conn, row["compute_lease_id"])
        for batch_id in sorted({str(row["batch_id"]) for row in rows}):
            self._refresh_batch(conn, batch_id)
        return len(rows)

    def _recover_prefetch_manifests_locked(self, conn: sqlite3.Connection, *, stale_s: float, now: float) -> tuple[int, int]:
        states = ("prefetch_requested", "prefetch_inflight")
        placeholders = ",".join("?" for _ in states)
        stale_clause = ""
        object_params: list[Any] = list(states)
        shard_params: list[Any] = list(states)
        if stale_s > 0:
            stale_clause = " and updated_at<=?"
            object_params.append(now - float(stale_s))
            shard_params.append(now - float(stale_s))
        object_rows = conn.execute(f"select namespace,kv_key,service_id from kv_memory_objects where state in ({placeholders}){stale_clause}", tuple(object_params)).fetchall()
        shard_rows = conn.execute(f"select namespace,kv_key,service_id,node_id,stage_index from kv_memory_shards where state in ({placeholders}){stale_clause}", tuple(shard_params)).fetchall()
        conn.execute(f"update kv_memory_objects set state='declared', updated_at=?, last_used_at=? where state in ({placeholders}){stale_clause}", tuple([now, now] + object_params))
        conn.execute(f"update kv_memory_shards set state='declared', gpu_resident=0, updated_at=?, last_used_at=? where state in ({placeholders}){stale_clause}", tuple([now, now] + shard_params))
        return len(object_rows), len(shard_rows)

    def _delete_request_kv(self, conn: sqlite3.Connection, request_id: str) -> None:
        conn.execute("delete from kv_entries where request_id=?", (request_id,))
        conn.execute("delete from kv_shard_entries where request_id=?", (request_id,))

    def _refresh_batch(self, conn: sqlite3.Connection, batch_id: str) -> None:
        counts = {str(row["state"]): int(row["n"]) for row in conn.execute("select state,count(*) n from requests where batch_id=? group by state", (batch_id,))}
        total = sum(counts.values())
        terminal = counts.get("completed", 0) + counts.get("failed", 0) + counts.get("cancelled", 0)
        state = "completed" if total and counts.get("completed", 0) == total else "cancelled" if total and counts.get("cancelled", 0) == total else "completed_with_failures" if total and terminal == total and counts.get("failed", 0) else "completed_with_cancelled" if total and terminal == total else "running" if counts.get("running", 0) else "ready" if counts.get("ready", 0) else "prefilling" if counts.get("prefilling", 0) else "queued"
        conn.execute(
            "update batches set state=?, updated_at=?, request_count=?, queued_count=?, prefilling_count=?, ready_count=?, running_count=?, completed_count=?, failed_count=?, cancelled_count=? where batch_id=?",
            (state, time.time(), total, counts.get("queued", 0), counts.get("prefilling", 0), counts.get("ready", 0), counts.get("running", 0), counts.get("completed", 0), counts.get("failed", 0), counts.get("cancelled", 0), batch_id),
        )

    def _event(self, conn: sqlite3.Connection, request_id: str, event_type: str, state: str, payload: dict[str, Any]) -> None:
        conn.execute("insert into events(created_at,request_id,event_type,state,payload_json) values (?,?,?,?,?)", (time.time(), request_id, event_type, state, json.dumps(payload, sort_keys=True)))

    def _write_notice(self, request_id: str, state: str, result: dict[str, Any]) -> None:
        (self.root / "notices" / f"{request_id}.json").write_text(json.dumps({"format": QUEUE_FORMAT, "request_id": request_id, "state": state, "result": result}, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_request_columns(conn: sqlite3.Connection) -> None:
    existing = {str(row["name"]) for row in conn.execute("pragma table_info(requests)")}
    columns = {
        "selected_service_id": "text",
        "selected_node_ids_json": "text",
        "selected_compute_domain": "text",
        "compute_lease_id": "text",
        "request_json_hash": "text",
        "kv_shard_count": "integer not null default 0",
        "kv_shard_bytes": "integer not null default 0",
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"alter table requests add column {name} {ddl}")


def _ensure_kv_shard_columns(conn: sqlite3.Connection) -> None:
    existing = {str(row["name"]) for row in conn.execute("pragma table_info(kv_shard_entries)")}
    columns = {
        "layer_start": "integer",
        "layer_end": "integer",
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"alter table kv_shard_entries add column {name} {ddl}")


def _canonical_request_json(raw: dict[str, Any]) -> str:
    return json.dumps(raw, sort_keys=True, separators=(",", ":"))


def _canonical_existing_request_json(raw: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(value, dict):
        return _canonical_request_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _request_json_hash(request_json: str) -> str:
    return "sha256:" + hashlib.sha256(request_json.encode("utf-8")).hexdigest()


def _compute_lease_quantum_s() -> float:
    try:
        return max(0.0, float(os.environ.get("DS4_COMPUTE_LEASE_QUANTUM_S", "0") or "0"))
    except ValueError:
        return 0.0


def _compute_lease_should_prefer(conn: sqlite3.Connection, lease: sqlite3.Row, *, now: float) -> bool:
    return not _compute_lease_should_drain(conn, lease, now=now)


def _compute_lease_should_drain(conn: sqlite3.Connection, lease: sqlite3.Row, *, now: float) -> bool:
    quantum_s = _compute_lease_quantum_s()
    if quantum_s <= 0:
        return False
    created_at = float(lease["created_at"] or now)
    if (now - created_at) < quantum_s:
        return False
    service_id = str(lease["service_id"] or "")
    domain = str(lease["compute_domain"] or "")
    if not service_id or not domain:
        return False
    row = conn.execute(
        """
        select 1 from requests
        where state in ('queued','ready')
          and selected_compute_domain=?
          and coalesce(selected_service_id,'') != ?
        limit 1
        """,
        (domain, service_id),
    ).fetchone()
    return row is not None


def _queued_rows(conn: sqlite3.Connection, *, node_id: str | None, eligible: tuple[str, ...], batch_id: str | None, limit: int, selected_service_id: str | None = None, ignore_compute_lease: bool = False) -> list[sqlite3.Row]:
    clauses = ["state='queued'"]
    params: list[Any] = []
    if node_id is not None:
        clauses.append("(selected_node_id is null or selected_node_id=?)")
        params.append(node_id)
    if eligible:
        clauses.append("selected_profile_id in (%s)" % ",".join("?" for _ in eligible))
        params.extend(eligible)
    if batch_id:
        clauses.append("batch_id=?")
        params.append(batch_id)
    if selected_service_id is not None:
        clauses.append("selected_service_id=?")
        params.append(selected_service_id)
    elif not batch_id and not ignore_compute_lease:
        now = time.time()
        existing_lease = conn.execute("select * from compute_leases where lease_expires_at > ? order by created_at limit 1", (now,)).fetchone()
        if existing_lease is not None and _compute_lease_should_prefer(conn, existing_lease, now=now):
            if existing_lease["service_id"]:
                clauses.append("selected_service_id=?")
                params.append(existing_lease["service_id"])
            if existing_lease["compute_domain"]:
                clauses.append("selected_compute_domain=?")
                params.append(existing_lease["compute_domain"])
    params.append(max(1, int(limit)))
    return conn.execute(f"select * from requests where {' and '.join(clauses)} order by priority, created_at, request_id limit ?", tuple(params)).fetchall()



def _normalize_namespace(namespace: str | None) -> str:
    namespace = str(namespace or "default")
    if not namespace:
        raise ValueError("namespace is required")
    return namespace


def _require_kv_key(kv_key: str | None) -> str:
    kv_key = str(kv_key or "")
    if not kv_key:
        raise ValueError("kv_key is required")
    return kv_key


def _require_service_id(service_id: str | None) -> str:
    service_id = str(service_id or "")
    if not service_id:
        raise ValueError("service_id is required")
    return service_id


def _external_kv_object_rows(conn: sqlite3.Connection, *, namespace: str, kv_key: str, service_id: str | None = None) -> list[sqlite3.Row]:
    if service_id is None:
        return conn.execute("select * from kv_memory_objects where namespace=? and kv_key=? order by service_id", (namespace, kv_key)).fetchall()
    return conn.execute("select * from kv_memory_objects where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchall()


def _validate_external_kv_partition_fingerprint(metadata: Mapping[str, Any], shards: list[dict[str, Any]]) -> None:
    expected = _metadata_partition_fingerprint(metadata)
    if expected is None:
        return
    mismatches = []
    for shard in shards:
        actual = _metadata_partition_fingerprint(dict(shard.get("metadata") or {}))
        if actual is not None and actual != expected:
            mismatches.append({"node_id": shard.get("node_id"), "stage_index": shard.get("stage_index"), "fingerprint": actual})
    if mismatches:
        raise ValueError(f"external KV shard layer partition fingerprint mismatch: {mismatches}")


def _metadata_partition_fingerprint(metadata: Mapping[str, Any]) -> str | None:
    value = metadata.get("layer_partition_fingerprint")
    if isinstance(value, str) and value:
        return value
    contract = metadata.get("kv_cache_contract")
    if isinstance(contract, dict):
        value = contract.get("fingerprint")
        if isinstance(value, str) and value:
            return value
    return None


def _external_kv_object_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "format": "ds4-external-kv-cache-object-summary-v1",
        "namespace": row["namespace"],
        "kv_key": row["kv_key"],
        "service_id": row["service_id"],
        "profile_id": row["profile_id"],
        "model_id": row["model_id"],
        "owner": row["owner"],
        "content_hash": row["content_hash"],
        "total_bytes": int(row["total_bytes"] or 0),
        "total_tokens": int(row["total_tokens"] or 0),
        "state": row["state"],
        "pin_count": int(row["pin_count"] or 0),
        "priority": int(row["priority"] or 0),
        "ttl_expires_at": row["ttl_expires_at"],
        "metadata": json.loads(str(row["metadata_json"] or "{}")),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_used_at": row["last_used_at"],
    }


def _external_kv_manifest(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    now = time.time()
    conn.execute("delete from kv_memory_leases where expires_at <= ?", (now,))
    shards = conn.execute(
        """
        select * from kv_memory_shards
        where namespace=? and kv_key=? and service_id=?
        order by stage_index, node_id
        """,
        (row["namespace"], row["kv_key"], row["service_id"]),
    ).fetchall()
    leases = conn.execute(
        """
        select lease_id,mode,owner,expires_at,created_at from kv_memory_leases
        where namespace=? and kv_key=? and service_id=?
        order by created_at
        """,
        (row["namespace"], row["kv_key"], row["service_id"]),
    ).fetchall()
    return {
        "format": "ds4-external-kv-cache-object-v1",
        "namespace": row["namespace"],
        "kv_key": row["kv_key"],
        "service_id": row["service_id"],
        "profile_id": row["profile_id"],
        "model_id": row["model_id"],
        "owner": row["owner"],
        "content_hash": row["content_hash"],
        "total_bytes": int(row["total_bytes"] or 0),
        "total_tokens": int(row["total_tokens"] or 0),
        "state": row["state"],
        "pin_count": int(row["pin_count"] or 0),
        "priority": int(row["priority"] or 0),
        "ttl_expires_at": row["ttl_expires_at"],
        "metadata": json.loads(str(row["metadata_json"] or "{}")),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_used_at": row["last_used_at"],
        "routing": dict(NODE_LOCAL_EXTERNAL_KV_ROUTING),
        "archive": dict(NODE_LOCAL_EXTERNAL_KV_ARCHIVE),
        "shards": [_external_kv_shard_status(shard) for shard in shards],
        "leases": [dict(lease) for lease in leases],
    }


def _external_kv_shard_status(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "namespace": row["namespace"],
        "kv_key": row["kv_key"],
        "service_id": row["service_id"],
        "node_id": row["node_id"],
        "stage_index": int(row["stage_index"]),
        "stage_count": int(row["stage_count"]),
        "layer_start": row["layer_start"],
        "layer_end": row["layer_end"],
        "bytes": int(row["bytes"] or 0),
        "state": row["state"],
        "storage_uri": row["storage_uri"],
        "gpu_resident": bool(row["gpu_resident"]),
        "metadata": json.loads(str(row["metadata_json"] or "{}")),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_used_at": row["last_used_at"],
    }

def _next_queued(conn: sqlite3.Connection, *, node_id: str | None, eligible: tuple[str, ...], batch_id: str | None) -> sqlite3.Row | None:
    clauses = ["state='queued'"]
    params: list[Any] = []
    if node_id is not None:
        clauses.append("(selected_node_id is null or selected_node_id=?)")
        params.append(node_id)
    if eligible:
        clauses.append("selected_profile_id in (%s)" % ",".join("?" for _ in eligible))
        params.extend(eligible)
    if batch_id:
        clauses.append("batch_id=?")
        params.append(batch_id)
    return conn.execute(f"select * from requests where {' and '.join(clauses)} order by priority, created_at, request_id limit 1", tuple(params)).fetchone()


def _ready_rows(conn: sqlite3.Connection, *, node_id: str | None, batch_id: str | None, limit: int, batch_limits_by_service: Mapping[str, int] | None = None, selected_service_id: str | None = None, ignore_compute_lease: bool = False, ready_shape_bucketing: bool = False, ready_shape_lookahead: int = 1) -> list[sqlite3.Row]:
    clauses = ["state='ready'"]
    params: list[Any] = []
    if node_id is not None:
        clauses.append("selected_node_id=?")
        params.append(node_id)
    if batch_id:
        clauses.append("batch_id=?")
        params.append(batch_id)
    if selected_service_id is not None:
        clauses.append("selected_service_id=?")
        params.append(selected_service_id)
    elif not batch_id and not ignore_compute_lease:
        now = time.time()
        existing_lease = conn.execute("select * from compute_leases where lease_expires_at > ? order by created_at limit 1", (now,)).fetchone()
        if existing_lease is not None and _compute_lease_should_prefer(conn, existing_lease, now=now):
            if existing_lease["service_id"]:
                clauses.append("selected_service_id=?")
                params.append(existing_lease["service_id"])
            if existing_lease["compute_domain"]:
                clauses.append("selected_compute_domain=?")
                params.append(existing_lease["compute_domain"])
    first = conn.execute(f"select * from requests where {' and '.join(clauses)} order by priority, ready_at, created_at, request_id limit 1", tuple(params)).fetchone()
    if first is None:
        return []
    service_id = _ready_row_scope(clauses, params, first, shape_bucket=ready_shape_bucketing)
    service_limit = _service_batch_limit(service_id, batch_limits_by_service or {}, limit)
    query_limit = service_limit
    if ready_shape_bucketing:
        query_limit = max(service_limit, service_limit * max(1, int(ready_shape_lookahead)))
    params.append(query_limit)
    rows = conn.execute(f"select * from requests where {' and '.join(clauses)} order by priority, ready_at, created_at, request_id limit ?", tuple(params)).fetchall()
    if ready_shape_bucketing:
        return _ready_shape_bucket(rows, service_limit)
    return rows


def _ready_row_scope(clauses: list[str], params: list[Any], first: sqlite3.Row, *, shape_bucket: bool) -> Any:
    clauses.append("selected_profile_id=?")
    params.append(first["selected_profile_id"])
    service_id = first["selected_service_id"]
    if service_id is None:
        clauses.append("selected_service_id is null")
    else:
        clauses.append("selected_service_id=?")
        params.append(service_id)
    compute_domain = first["selected_compute_domain"]
    if compute_domain is None:
        clauses.append("selected_compute_domain is null")
    else:
        clauses.append("selected_compute_domain=?")
        params.append(compute_domain)
    if shape_bucket:
        clauses.append("priority=?")
        params.append(first["priority"])
    return service_id


def _ready_shape_bucket(rows: list[sqlite3.Row], limit: int) -> list[sqlite3.Row]:
    buckets: dict[str, list[sqlite3.Row]] = {}
    first_indexes: dict[str, int] = {}
    for index, row in enumerate(rows):
        key = _ready_shape_key(row)
        if key not in buckets:
            buckets[key] = []
            first_indexes[key] = index
        buckets[key].append(row)
    if not buckets:
        return []
    best = max(buckets, key=lambda key: (min(len(buckets[key]), limit), -first_indexes[key]))
    return buckets[best][:limit]


def _ready_shape_key(row: sqlite3.Row) -> str:
    try:
        raw = json.loads(str(row["request_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return "_invalid"
    if not isinstance(raw, dict):
        return "_invalid"
    input_data = raw.get("input") if isinstance(raw.get("input"), dict) else {}
    openai = input_data.get("openai") if isinstance(input_data.get("openai"), dict) else {}
    extra_body = input_data.get("openai_extra_body") if isinstance(input_data.get("openai_extra_body"), dict) else {}
    benchmark_shape = input_data.get("benchmark_shape") if isinstance(input_data.get("benchmark_shape"), dict) else {}
    shape = {
        "benchmark_output_tokens": benchmark_shape.get("output_tokens"),
        "chat": raw.get("chat"),
        "max_output_tokens": raw.get("max_output_tokens"),
        "openai": openai,
        "openai_extra_body": extra_body,
        "temperature": raw.get("temperature"),
        "thinking_budget_tokens": raw.get("thinking_budget_tokens"),
        "top_p": raw.get("top_p"),
    }
    return json.dumps(shape, sort_keys=True, separators=(",", ":"), default=str)


def _service_batch_limit(service_id: Any, batch_limits_by_service: Mapping[str, int], default_limit: int) -> int:
    limit = max(1, int(default_limit))
    if service_id is None:
        return limit
    configured = batch_limits_by_service.get(str(service_id))
    if configured is None:
        return limit
    return min(limit, max(1, int(configured)))


def _claim(row: sqlite3.Row, lease_id: str, compute_lease_id: str | None) -> QueueClaim:
    return QueueClaim(
        request_id=str(row["request_id"]),
        batch_id=str(row["batch_id"]),
        request_kind=str(row["request_kind"]),
        selected_profile_id=str(row["selected_profile_id"]),
        selected_node_id=str(row["selected_node_id"]) if row["selected_node_id"] else None,
        lease_id=lease_id,
        attempt_count=int(row["attempt_count"] or 0) + 1,
        request=InferenceRequest.from_json(json.loads(str(row["request_json"]))) if row["request_kind"] == "model" else None,
        service_name=str(row["service_name"]) if row["service_name"] else None,
        payload=json.loads(str(row["request_json"])),
        selected_service_id=str(row["selected_service_id"]) if row["selected_service_id"] else None,
        selected_node_ids=_row_node_ids(row, fallback_node_id=row["selected_node_id"]),
        selected_compute_domain=str(row["selected_compute_domain"]) if row["selected_compute_domain"] else None,
        compute_lease_id=compute_lease_id,
    )


def _request_status(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "format": REQUEST_STATUS_FORMAT,
        "request_id": row["request_id"],
        "batch_id": row["batch_id"],
        "job_id": row["batch_id"],
        "request_kind": row["request_kind"],
        "state": row["state"],
        "priority": int(row["priority"]),
        "immediate": bool(row["immediate"]),
        "selected_profile_id": row["selected_profile_id"],
        "selected_node_id": row["selected_node_id"],
        "selected_node_ids": list(_row_node_ids(row, fallback_node_id=row["selected_node_id"])),
        "selected_service_id": row["selected_service_id"],
        "selected_compute_domain": row["selected_compute_domain"],
        "compute_lease_id": row["compute_lease_id"],
        "service_name": row["service_name"],
        "lease_id": row["lease_id"],
        "leased_by": row["leased_by"],
        "lease_expires_at": row["lease_expires_at"],
        "heartbeat_at": row["heartbeat_at"],
        "attempt_count": int(row["attempt_count"] or 0),
        "cancel_requested": bool(row["cancel_requested"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "ready_at": row["ready_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "error": row["error"],
        "kv_key": row["kv_key"],
        "kv_bytes": int(row["kv_bytes"] or 0),
        "kv_shard_count": int(row["kv_shard_count"] or 0),
        "kv_shard_bytes": int(row["kv_shard_bytes"] or 0),
    }


def _usage_int(value: Any) -> int:
    try:
        return max(0,int(value or 0))
    except Exception:
        return 0


def _result_usage_tokens(result: dict[str, Any]) -> tuple[int, int, int]:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    prompt = _usage_int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    completion = _usage_int(usage.get("output_tokens", usage.get("completion_tokens", 0)))
    total = _usage_int(usage.get("total_tokens", 0))
    if total == 0 and (prompt > 0 or completion > 0):
        total = prompt + completion
    return prompt, completion, total


def _batch_status(row: sqlite3.Row) -> dict[str, Any]:
    return {"format": BATCH_STATUS_FORMAT, "batch_id": row["batch_id"], "job_id": row["batch_id"], "state": row["state"], "request_count": int(row["request_count"]), "queued_count": int(row["queued_count"]), "prefilling_count": int(row["prefilling_count"]), "ready_count": int(row["ready_count"]), "running_count": int(row["running_count"]), "completed_count": int(row["completed_count"]), "failed_count": int(row["failed_count"]), "cancelled_count": int(row["cancelled_count"])}


def _telemetry_status(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(str(row["payload_json"])) if row["payload_json"] else {}
    return {
        "service_id": row["service_id"],
        "node_id": row["node_id"],
        "stage_index": int(row["stage_index"]),
        "stage_count": int(row["stage_count"]),
        "layer_start": row["layer_start"],
        "layer_end": row["layer_end"],
        "layer_count": row["layer_count"],
        "kv_shard_bytes": int(row["kv_shard_bytes"] or 0),
        "reported_at": row["reported_at"],
        "payload": payload,
    }


def _node_depth(conn: sqlite3.Connection, node_id: str) -> int:
    row = conn.execute("select count(*) n from requests where request_kind='model' and state in ('prefilling','ready','running') and selected_node_id=?", (node_id,)).fetchone()
    return int(row["n"] if row else 0)


def _kv_need(request: InferenceRequest) -> tuple[str | None, int]:
    meta = request.raw.get("metadata") if isinstance(request.raw.get("metadata"), dict) else {}
    key = request.input.get("kv_cache_key") or meta.get("kv_cache_key") or request.input.get("shared_prefix_hash") or request.input.get("skeleton_hash")
    bytes_value = request.input.get("kv_bytes_estimate", meta.get("kv_bytes_estimate", 0))
    try:
        bytes_int = max(0, int(bytes_value or 0))
    except (TypeError, ValueError):
        bytes_int = 0
    return (str(key) if key else None), bytes_int


def request_batch_key(request: InferenceRequest, profile: Any, assignment: Any | None) -> str:
    prefix_key = str(request.input.get("shared_prefix_hash") or request.input.get("skeleton_hash") or "no_prefix")
    kv_key = request_kv_cache_batch_key(request.input)
    if kv_key is not None:
        prefix_key = prefix_key + "|kv=" + kv_key
    return "|".join(
        [
            str(getattr(assignment, "node_id", None) or "unassigned"),
            str(profile.profile_id),
            "chat" if request.chat else "completion",
            request.job_class,
            input_bucket(request),
            output_bucket(request.max_output_tokens),
            thinking_bucket(request.thinking_budget_tokens),
            prefix_key,
            "immediate" if request.immediate else "queued",
        ]
    )


def input_bucket(request: InferenceRequest) -> str:
    text = "\n".join(str(request.input.get(key, "")) for key in ("shared_prefix", "suffix", "prompt"))
    byte_count = len(text.encode("utf-8"))
    if byte_count <= 4096:
        return "in_0_4k"
    if byte_count <= 16384:
        return "in_4k_16k"
    if byte_count <= 65536:
        return "in_16k_64k"
    return "in_64k_plus"


def output_bucket(max_output_tokens: int) -> str:
    if max_output_tokens <= 256:
        return "out_0_256"
    if max_output_tokens <= 768:
        return "out_257_768"
    if max_output_tokens <= 2048:
        return "out_769_2048"
    return "out_2049_plus"


def thinking_bucket(thinking_budget_tokens: int) -> str:
    if thinking_budget_tokens <= 0:
        return "think_none"
    if thinking_budget_tokens <= 512:
        return "think_1_512"
    if thinking_budget_tokens <= 2048:
        return "think_513_2048"
    return "think_2049_plus"


def _row_node_ids(row: sqlite3.Row, *, fallback_node_id: Any) -> tuple[str, ...]:
    raw = row["selected_node_ids_json"] if "selected_node_ids_json" in row.keys() else None
    if raw:
        try:
            parsed = json.loads(str(raw))
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            values = tuple(str(item) for item in parsed if str(item))
            if values:
                return values
    return (str(fallback_node_id),) if fallback_node_id else ()


def _kv_victims_to_fit(conn: sqlite3.Connection, *, table: str, service_id: str | None, node_id: str, need: int, capacity: int) -> list[str] | None:
    if capacity <= 0:
        return []
    if table == "kv_shard_entries":
        row = conn.execute("select coalesce(sum(bytes),0) n from kv_shard_entries where service_id=? and node_id=?", (service_id, node_id)).fetchone()
        used = int(row["n"] if row else 0)
        victims = conn.execute("select kv_key,bytes from kv_shard_entries where service_id=? and node_id=? and state='idle' order by last_used_at, created_at", (service_id, node_id)).fetchall()
    else:
        row = conn.execute("select coalesce(sum(bytes),0) n from kv_entries where node_id=?", (node_id,)).fetchone()
        used = int(row["n"] if row else 0)
        victims = conn.execute("select kv_key,bytes from kv_entries where node_id=? and state='idle' order by last_used_at, created_at", (node_id,)).fetchall()
    out: list[str] = []
    for victim in victims:
        if used + need <= capacity:
            break
        out.append(str(victim["kv_key"]))
        used -= int(victim["bytes"] or 0)
    if used + need > capacity:
        return None
    return out


def _failure(request_id: str, error: str) -> dict[str, Any]:
    return {"format": "ds4-inference-failure-v1", "request_id": request_id, "status": "failed", "error": error}


def _result_error(result: dict[str, Any]) -> str:
    transport = result.get("transport")
    if isinstance(transport, dict) and transport.get("error"):
        return str(transport.get("error"))
    if result.get("error"):
        return str(result.get("error"))
    output = result.get("output")
    if isinstance(output, dict) and output.get("text"):
        try:
            parsed = json.loads(str(output.get("text")))
        except json.JSONDecodeError:
            return str(output.get("text"))[:4000]
        if isinstance(parsed, dict) and parsed.get("error"):
            return str(parsed.get("error"))
    return ""


def _count(values: Iterable[Any]) -> dict[Any, int]:
    out: dict[Any, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def queue_depths(db_path: str | Path, *, request_kind: str | None = None) -> dict[str, int]:
    if not Path(db_path).exists():
        return {}
    clauses = ["state in ('prefilling','ready','running')", "selected_node_id is not null"]
    params: list[Any] = []
    if request_kind:
        clauses.append("request_kind=?")
        params.append(request_kind)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"select selected_node_id,count(*) n from requests where {' and '.join(clauses)} group by selected_node_id", tuple(params)).fetchall()
    return {str(row["selected_node_id"]): int(row["n"]) for row in rows}
