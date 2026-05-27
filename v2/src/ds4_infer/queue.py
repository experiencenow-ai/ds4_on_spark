from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Iterable
import uuid

from .profiles import ProfileRegistry
from .queue_policy import job_batch_id, request_priority, validated_priority
from .runners import Runner
from .schemas import InferenceRequest

QUEUE_FORMAT = "ds4-inference-queue-v1"
REQUEST_STATUS_FORMAT = "ds4-inference-request-status-v1"
BATCH_STATUS_FORMAT = "ds4-inference-batch-status-v1"
CPU_QUEUE_TIMEOUT_KEY = "__ds4_queue_timeout_s"
TERMINAL_STATES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class QueueClaim:
    request_id: str
    batch_id: str
    request_kind: str
    selected_profile_id: str
    selected_node_id: str | None
    lease_id: str
    request: InferenceRequest | None
    service_name: str | None = None
    payload: dict[str, Any] | None = None


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
                    selected_profile_id text not null, selected_node_id text, request_json text not null,
                    result_json text, error text, cancel_requested integer not null default 0,
                    kv_key text, kv_bytes integer not null default 0,
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
                create index if not exists requests_ready_idx on requests(state, selected_node_id, priority, ready_at, created_at);
                create index if not exists requests_queued_idx on requests(state, priority, created_at, request_id);
                create index if not exists requests_job_idx on requests(batch_id, state);
                """
            )

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
        ids: list[str] = []
        with closing(self._connect()) as conn, conn:
            conn.execute("insert into batches(batch_id, created_at, updated_at) values (?, ?, ?)", (batch_id, now, now))
            for req in request_list:
                profile = registry.resolve(capability=req.capability, chat=req.chat, job_class=req.job_class, model_pin=req.model_pin)
                prio = request_priority(req, priority_override=priority)
                kv_key, kv_bytes = _kv_need(req)
                conn.execute(
                    """
                    insert into requests(request_id,batch_id,request_kind,state,priority,immediate,selected_profile_id,
                        selected_node_id,request_json,kv_key,kv_bytes,created_at,updated_at)
                    values (?,?,'model','queued',?,?,?,?,?,?,?,?,?)
                    """,
                    (req.request_id, batch_id, prio, 1 if req.immediate else 0, profile.profile_id, None, json.dumps(req.raw, sort_keys=True), kv_key, kv_bytes, now, now),
                )
                self._event(conn, req.request_id, "submitted", "queued", {"batch_id": batch_id, "priority": prio, "node_binding": "lease"})
                profiles[profile.profile_id] = profiles.get(profile.profile_id, 0) + 1
                priorities[prio] = priorities.get(prio, 0) + 1
                ids.append(req.request_id)
            self._refresh_batch(conn, batch_id)
        return {"format": QUEUE_FORMAT, "state": "queued", "batch_id": batch_id, "job_id": batch_id, "request_ids": ids, "request_count": len(ids), "selected_profiles": profiles, "selected_nodes": {}, "selected_services": {}, "priority_counts": {str(k): v for k, v in sorted(priorities.items())}, "metadata": {"late_bound_count": len(ids)}}

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

    def work(self, *, registry: ProfileRegistry, runner: Runner, node_id: str | None = None, batch_id: str | None = None, limit: int = 1, concurrency: int = 1, worker_id: str | None = None, lease_ttl_s: int = 900, heartbeat_interval_s: float = 5.0, node_profile_ids: Iterable[str] | None = None, max_node_depth: int = 0, batch_linger_s: float = 0.0, kv_capacity_bytes: int = 0, on_result: Callable[[QueueClaim, dict[str, Any]], None] | None = None) -> dict[str, Any]:
        from .worker import BatchWorker
        return BatchWorker(queue=self, registry=registry, runner=runner, worker_id=worker_id, lease_ttl_s=lease_ttl_s, heartbeat_interval_s=heartbeat_interval_s).run_once(node_id=node_id, batch_id=batch_id, limit=limit, concurrency=concurrency, node_profile_ids=tuple(node_profile_ids or ()), max_node_depth=max_node_depth, batch_linger_s=batch_linger_s, kv_capacity_bytes=kv_capacity_bytes, on_result=on_result)

    def prepare_ready(self, *, node_id: str | None, eligible_profile_ids: Iterable[str], batch_id: str | None, limit: int, leased_by: str, lease_ttl_s: int, max_node_depth: int = 0, kv_capacity_bytes: int = 0) -> int:
        eligible = tuple(str(x) for x in eligible_profile_ids if str(x))
        now = time.time()
        made_ready = 0
        with closing(self._connect()) as conn, conn:
            while made_ready < limit:
                if node_id is not None and max_node_depth > 0 and _node_depth(conn, node_id) >= max_node_depth:
                    break
                row = _next_queued(conn, node_id=node_id, eligible=eligible, batch_id=batch_id)
                if row is None:
                    break
                if not self._reserve_kv(conn, row, node_id=node_id, capacity=kv_capacity_bytes, now=now):
                    break
                lease_id = f"{leased_by}:prefill:{uuid.uuid4().hex}"
                conn.execute(
                    """
                    update requests set state='ready', selected_node_id=coalesce(?, selected_node_id), ready_at=?, updated_at=?,
                        lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null
                    where request_id=? and state='queued'
                    """,
                    (node_id, now, now, row["request_id"]),
                )
                self._event(conn, str(row["request_id"]), "prefilled", "ready", {"batch_id": row["batch_id"], "node_id": node_id, "lease_id": lease_id})
                self._refresh_batch(conn, str(row["batch_id"]))
                made_ready += 1
        return made_ready

    def claim_ready_batch(self, *, node_id: str | None, batch_id: str | None, limit: int, leased_by: str, lease_ttl_s: int, batch_linger_s: float = 0.0) -> list[QueueClaim]:
        now = time.time()
        with closing(self._connect()) as conn, conn:
            rows = _ready_rows(conn, node_id=node_id, batch_id=batch_id, limit=limit)
            if not rows:
                return []
            if len(rows) < limit and batch_linger_s > 0:
                newest_ready = max(float(row["ready_at"] or row["updated_at"] or now) for row in rows)
                if (now - newest_ready) < batch_linger_s:
                    return []
            claims: list[QueueClaim] = []
            batch_ids: set[str] = set()
            for row in rows:
                lease_id = f"{leased_by}:run:{uuid.uuid4().hex}"
                updated = conn.execute(
                    """
                    update requests set state='running', lease_id=?, leased_by=?, lease_expires_at=?,
                        heartbeat_at=?, started_at=?, updated_at=?, attempt_count=attempt_count+1
                    where request_id=? and state='ready'
                    """,
                    (lease_id, leased_by, now + lease_ttl_s, now, now, now, row["request_id"]),
                ).rowcount
                if updated == 1:
                    batch_ids.add(str(row["batch_id"]))
                    self._event(conn, str(row["request_id"]), "started", "running", {"batch_id": row["batch_id"], "lease_id": lease_id, "node_id": row["selected_node_id"]})
                    claims.append(_claim(row, lease_id))
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
            self._event(conn, request_id, final, final, {"batch_id": row["batch_id"]})
            self._refresh_batch(conn, str(row["batch_id"]))
        self._write_notice(request_id, final, final_result)
        return True

    def cancel(self, *, request_id: str | None = None, batch_id: str | None = None, job_id: str | None = None, reason: str = "cancelled by operator") -> dict[str, Any]:
        batch_id = job_batch_id(batch_id=batch_id, job_id=job_id)
        if sum(x is not None for x in (request_id, batch_id)) != 1:
            raise ValueError("exactly one of request_id, batch_id, or job_id is required")
        now = time.time()
        cancelled: list[str] = []
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
                    skipped["running"] = skipped.get("running", 0) + 1
                    continue
                result = {"format": "ds4-inference-cancelled-v1", "request_id": rid, "status": "cancelled", "reason": reason}
                conn.execute("update requests set state='cancelled', result_json=?, error=?, completed_at=?, updated_at=? where request_id=?", (json.dumps(result, sort_keys=True), reason, now, now, rid))
                conn.execute("delete from kv_entries where request_id=?", (rid,))
                self._event(conn, rid, "cancelled", "cancelled", {"batch_id": row["batch_id"], "reason": reason})
                self._write_notice(rid, "cancelled", result)
                cancelled.append(rid)
            for bid in {str(row["batch_id"]) for row in rows}:
                self._refresh_batch(conn, bid)
        return {"format": QUEUE_FORMAT, "state": "cancelled" if cancelled and not skipped else "partial" if cancelled else "unchanged", "request_id": request_id, "batch_id": batch_id, "job_id": batch_id, "cancelled_count": len(cancelled), "cancelled_request_ids": cancelled, "skipped_state_counts": skipped}

    def requeue_expired_leases(self, *, max_attempts: int = 3, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        requeued = failed = 0
        with closing(self._connect()) as conn, conn:
            rows = conn.execute("select * from requests where state in ('prefilling','running') and lease_expires_at is not null and lease_expires_at <= ? order by lease_expires_at, request_id", (now,)).fetchall()
            for row in rows:
                attempts = int(row["attempt_count"] or 0)
                state = "failed" if attempts >= max_attempts else "queued"
                if state == "queued":
                    requeued += 1
                    conn.execute("delete from kv_entries where request_id=?", (row["request_id"],))
                    conn.execute("update requests set state='queued', selected_node_id=null, lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null, updated_at=? where request_id=?", (now, row["request_id"]))
                else:
                    failed += 1
                    result = _failure(str(row["request_id"]), f"lease expired after {attempts} attempts")
                    conn.execute("update requests set state='failed', result_json=?, error='lease_expired', completed_at=?, updated_at=?, lease_id=null, leased_by=null, lease_expires_at=null, heartbeat_at=null where request_id=?", (json.dumps(result, sort_keys=True), now, now, row["request_id"]))
                    self._write_notice(str(row["request_id"]), "failed", result)
                self._event(conn, str(row["request_id"]), "lease_expired", state, {"batch_id": row["batch_id"], "attempt_count": attempts})
                self._refresh_batch(conn, str(row["batch_id"]))
        return {"format": QUEUE_FORMAT, "state": "reaped" if requeued or failed else "idle", "requeued_count": requeued, "failed_count": failed}

    def heartbeat(self, *, lease_ids: Iterable[str], lease_ttl_s: int) -> int:
        ids = [str(lease_id) for lease_id in lease_ids if lease_id]
        if not ids:
            return 0
        now = time.time()
        with closing(self._connect()) as conn, conn:
            placeholders = ",".join("?" for _ in ids)
            return int(
                conn.execute(
                    f"update requests set heartbeat_at=?, lease_expires_at=?, updated_at=? where state='running' and lease_id in ({placeholders})",
                    (now, now + lease_ttl_s, now, *ids),
                ).rowcount
            )

    def status(self, *, request_id: str | None = None, batch_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
        batch_id = job_batch_id(batch_id=batch_id, job_id=job_id)
        with closing(self._connect()) as conn, conn:
            if request_id is not None:
                row = conn.execute("select * from requests where request_id=?", (request_id,)).fetchone()
                return {"format": REQUEST_STATUS_FORMAT, "request_id": request_id, "state": "unknown"} if row is None else _request_status(row)
            if batch_id is not None:
                self._refresh_batch(conn, batch_id)
                row = conn.execute("select * from batches where batch_id=?", (batch_id,)).fetchone()
                return {"format": BATCH_STATUS_FORMAT, "batch_id": batch_id, "job_id": batch_id, "state": "unknown"} if row is None else _batch_status(row)
            counts = {str(r["state"]): int(r["n"]) for r in conn.execute("select state,count(*) n from requests group by state order by state")}
            event = conn.execute("select max(event_id) newest from events").fetchone()
            return {"format": QUEUE_FORMAT, "state_counts": counts, "newest_event_id": int(event["newest"] or 0)}

    def poll(self, *, after_event_id: int = 0, limit: int = 100) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            rows = conn.execute("select * from events where event_id>? order by event_id limit ?", (after_event_id, limit)).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(str(row["payload_json"]))
            events.append(event)
        return {"format": QUEUE_FORMAT, "events": events, "newest_event_id": max([after_event_id] + [int(e["event_id"]) for e in events])}

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

    def _existing_submission(self, batch_id: str, requests: list[InferenceRequest], priority: int | None) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            rows = conn.execute("select request_id,priority,selected_profile_id from requests where batch_id=? order by request_id", (batch_id,)).fetchall()
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
        return {"format": QUEUE_FORMAT, "state": "queued", "batch_id": batch_id, "job_id": batch_id, "request_ids": existing, "request_count": len(existing), "selected_profiles": _count(row["selected_profile_id"] for row in rows), "selected_nodes": {}, "selected_services": {}, "priority_counts": {str(k): v for k, v in _count(int(row["priority"]) for row in rows).items()}}

    def _reserve_kv(self, conn: sqlite3.Connection, row: sqlite3.Row, *, node_id: str | None, capacity: int, now: float) -> bool:
        key = row["kv_key"]
        need = int(row["kv_bytes"] or 0)
        if not key or need <= 0:
            return True
        if node_id is None:
            return False
        if capacity > 0:
            used = int((conn.execute("select coalesce(sum(bytes),0) n from kv_entries where node_id=?", (node_id,)).fetchone() or {"n": 0})["n"])
            for victim in conn.execute("select * from kv_entries where node_id=? and state='idle' order by last_used_at, created_at", (node_id,)).fetchall():
                if used + need <= capacity:
                    break
                conn.execute("delete from kv_entries where node_id=? and kv_key=?", (node_id, victim["kv_key"]))
                used -= int(victim["bytes"] or 0)
            if used + need > capacity:
                return False
        conn.execute("insert or replace into kv_entries(node_id,kv_key,request_id,bytes,state,last_used_at,created_at,updated_at) values (?,?,?,?,?,?,?,?)", (node_id, key, row["request_id"], need, "ready", now, now, now))
        return True

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


def _ready_rows(conn: sqlite3.Connection, *, node_id: str | None, batch_id: str | None, limit: int) -> list[sqlite3.Row]:
    clauses = ["state='ready'"]
    params: list[Any] = []
    if node_id is not None:
        clauses.append("selected_node_id=?")
        params.append(node_id)
    if batch_id:
        clauses.append("batch_id=?")
        params.append(batch_id)
    first = conn.execute(f"select * from requests where {' and '.join(clauses)} order by priority, ready_at, created_at, request_id limit 1", tuple(params)).fetchone()
    if first is None:
        return []
    clauses.append("selected_profile_id=?")
    params.append(first["selected_profile_id"])
    params.append(limit)
    return conn.execute(f"select * from requests where {' and '.join(clauses)} order by priority, ready_at, created_at, request_id limit ?", tuple(params)).fetchall()


def _claim(row: sqlite3.Row, lease_id: str) -> QueueClaim:
    return QueueClaim(request_id=str(row["request_id"]), batch_id=str(row["batch_id"]), request_kind=str(row["request_kind"]), selected_profile_id=str(row["selected_profile_id"]), selected_node_id=str(row["selected_node_id"]) if row["selected_node_id"] else None, lease_id=lease_id, request=InferenceRequest.from_json(json.loads(str(row["request_json"]))) if row["request_kind"] == "model" else None, service_name=str(row["service_name"]) if row["service_name"] else None, payload=json.loads(str(row["request_json"])))


def _request_status(row: sqlite3.Row) -> dict[str, Any]:
    return {"format": REQUEST_STATUS_FORMAT, "request_id": row["request_id"], "batch_id": row["batch_id"], "job_id": row["batch_id"], "request_kind": row["request_kind"], "state": row["state"], "priority": int(row["priority"]), "immediate": bool(row["immediate"]), "selected_profile_id": row["selected_profile_id"], "selected_node_id": row["selected_node_id"], "service_name": row["service_name"], "lease_id": row["lease_id"], "leased_by": row["leased_by"], "lease_expires_at": row["lease_expires_at"], "heartbeat_at": row["heartbeat_at"], "attempt_count": int(row["attempt_count"] or 0), "cancel_requested": bool(row["cancel_requested"]), "created_at": row["created_at"], "updated_at": row["updated_at"], "ready_at": row["ready_at"], "started_at": row["started_at"], "completed_at": row["completed_at"], "error": row["error"], "kv_key": row["kv_key"], "kv_bytes": int(row["kv_bytes"] or 0)}


def _batch_status(row: sqlite3.Row) -> dict[str, Any]:
    return {"format": BATCH_STATUS_FORMAT, "batch_id": row["batch_id"], "job_id": row["batch_id"], "state": row["state"], "request_count": int(row["request_count"]), "queued_count": int(row["queued_count"]), "prefilling_count": int(row["prefilling_count"]), "ready_count": int(row["ready_count"]), "running_count": int(row["running_count"]), "completed_count": int(row["completed_count"]), "failed_count": int(row["failed_count"]), "cancelled_count": int(row["cancelled_count"])}


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


def _failure(request_id: str, error: str) -> dict[str, Any]:
    return {"format": "ds4-inference-failure-v1", "request_id": request_id, "status": "failed", "error": error}


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
