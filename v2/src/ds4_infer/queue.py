from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any, Callable, Iterable

from .builders import new_id, safe_request_id
from .profiles import ModelProfile, ProfileRegistry
from .runners import Runner
from .schemas import InferenceRequest, make_result
from .topology import SparkAssignment, SparkTopology

QUEUE_FORMAT = "ds4-inference-queue-v1"
REQUEST_STATUS_FORMAT = "ds4-inference-request-status-v1"
REQUEST_NOTICE_FORMAT = "ds4-inference-completion-notice-v1"
BATCH_STATUS_FORMAT = "ds4-inference-batch-status-v1"
PREFIX_GROUP_FORMAT = "ds4-prefix-group-v1"
PREFIX_WARM_REPORT_FORMAT = "ds4-prefix-warm-report-v1"
PREFIX_WARM_STATUS_FORMAT = "ds4-prefix-warm-status-v1"
TERMINAL_STATES = {"completed", "failed", "cancelled"}
CPU_QUEUE_TIMEOUT_KEY = "__ds4_queue_timeout_s"
REQUEST_COLUMNS_SQL = """
create table if not exists requests(
    request_id text primary key,
    batch_id text not null,
    request_kind text not null default 'model',
    service_name text,
    state text not null,
    priority integer not null,
    immediate integer not null,
    batch_key text not null,
    selected_profile_id text not null,
    selected_node_id text,
    request_json text not null,
    result_json text,
    error text,
    created_at real not null,
    updated_at real not null,
    started_at real,
    completed_at real,
    lease_id text,
    leased_by text,
    lease_expires_at real,
    heartbeat_at real,
    attempt_count integer not null default 0
)
"""
QUEUE_SCHEMA_SQL = (
    """
    create table if not exists batches(
        batch_id text primary key,
        state text not null default 'queued',
        created_at real not null,
        updated_at real not null,
        request_count integer not null default 0,
        queued_count integer not null default 0,
        running_count integer not null default 0,
        completed_count integer not null default 0,
        failed_count integer not null default 0,
        cancelled_count integer not null default 0
    )
    """,
    REQUEST_COLUMNS_SQL,
    "create index if not exists idx_requests_state_node_key "
    "on requests(state, selected_node_id, batch_key, priority, created_at)",
    "create index if not exists idx_requests_lease on requests(state, lease_expires_at, lease_id)",
    "create index if not exists idx_requests_batch on requests(batch_id, state)",
    """
    create table if not exists events(
        event_id integer primary key autoincrement,
        created_at real not null,
        request_id text not null,
        event_type text not null,
        state text not null,
        payload_json text not null
    )
    """,
    """
    create table if not exists prefix_warms(
        warm_key text primary key,
        skeleton_hash text not null,
        shared_prefix_hash text not null,
        profile_id text not null,
        node_id text,
        chat integer not null,
        shared_prefix_bytes integer not null,
        request_count integer not null,
        state text not null,
        warmed_at real,
        updated_at real not null,
        result_json text,
        error text
    )
    """,
)


@dataclass(frozen=True)
class QueueSubmission:
    batch_id: str
    request_ids: tuple[str, ...]
    selected_profiles: dict[str, int]
    selected_nodes: dict[str, int]
    selected_services: dict[str, int] | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "format": QUEUE_FORMAT,
            "batch_id": self.batch_id,
            "state": "queued",
            "request_count": len(self.request_ids),
            "request_ids": list(self.request_ids),
            "selected_profiles": self.selected_profiles,
            "selected_nodes": self.selected_nodes,
            "selected_services": self.selected_services or {},
        }


@dataclass(frozen=True)
class QueueClaim:
    request_id: str
    batch_id: str
    batch_key: str
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
        self.db_path = self.root / "queue.sqlite3"
        self.notices_dir = self.root / "notices"
        self.notices_dir.mkdir(parents=True, exist_ok=True)
        self._connect().close()

    def submit_requests(
        self,
        *,
        requests: Iterable[InferenceRequest],
        registry: ProfileRegistry,
        topology: SparkTopology | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        request_list = list(requests)
        if not request_list:
            raise ValueError("cannot submit an empty request set")
        batch_id = batch_id or new_id("batch")
        request_ids: list[str] = []
        selected_profiles: dict[str, int] = {}
        selected_nodes: dict[str, int] = {}
        node_load = self._queued_and_running_node_load()
        now = time.time()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "insert into batches(batch_id, created_at, updated_at) values (?, ?, ?)",
                (batch_id, now, now),
            )
            for request in request_list:
                profile = registry.resolve(
                    capability=request.capability,
                    chat=request.chat,
                    job_class=request.job_class,
                    model_pin=request.model_pin,
                )
                assignment = None
                if topology is not None:
                    assignment = topology.assign_profile(profile, immediate=request.immediate, current_load=node_load)
                    node_load[assignment.node_id] = node_load.get(assignment.node_id, 0) + 1
                    selected_nodes[assignment.node_id] = selected_nodes.get(assignment.node_id, 0) + 1
                selected_profiles[profile.profile_id] = selected_profiles.get(profile.profile_id, 0) + 1
                batch_key = request_batch_key(request, profile, assignment)
                conn.execute(
                    """
                    insert into requests(
                        request_id, batch_id, request_kind, service_name, state, priority, immediate, batch_key,
                        selected_profile_id, selected_node_id, request_json,
                        created_at, updated_at
                    ) values (?, ?, 'model', null, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.request_id,
                        batch_id,
                        0 if request.immediate else 10,
                        1 if request.immediate else 0,
                        batch_key,
                        profile.profile_id,
                        assignment.node_id if assignment is not None else None,
                        json.dumps(request.raw, sort_keys=True),
                        now,
                        now,
                    ),
                )
                self._insert_event(
                    conn,
                    request.request_id,
                    "submitted",
                    "queued",
                    {
                        "batch_id": batch_id,
                        "batch_key": batch_key,
                        "selected_profile_id": profile.profile_id,
                        "selected_node_id": assignment.node_id if assignment is not None else None,
                    },
                )
                request_ids.append(request.request_id)
            self._refresh_batch_row(conn, batch_id)
        return QueueSubmission(
            batch_id=batch_id,
            request_ids=tuple(request_ids),
            selected_profiles=selected_profiles,
            selected_nodes=selected_nodes,
        ).to_public_dict()

    def submit_cpu_requests(
        self,
        *,
        service: str,
        items: Iterable[dict[str, Any]],
        batch_id: str | None = None,
        immediate: bool = False,
        node_id: str | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        batch_id = batch_id or new_id("cpu-batch")
        service, item_list = _validated_cpu_items(service, items, timeout_s)
        now = time.time()
        request_ids: list[str] = []
        batch_key = cpu_batch_key(service=service, node_id=node_id, immediate=immediate, timeout_s=timeout_s)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "insert into batches(batch_id, created_at, updated_at) values (?, ?, ?)",
                (batch_id, now, now),
            )
            for request_id, item in _cpu_request_rows(service, item_list, timeout_s):
                self._insert_cpu_request(
                    conn,
                    request_id=request_id,
                    batch_id=batch_id,
                    service=service,
                    item=item,
                    immediate=immediate,
                    batch_key=batch_key,
                    node_id=node_id,
                    now=now,
                )
                event = {"batch_id": batch_id, "batch_key": batch_key, "service": service, "selected_node_id": node_id}
                self._insert_event(conn, request_id, "submitted", "queued", event)
                request_ids.append(request_id)
            self._refresh_batch_row(conn, batch_id)
        return QueueSubmission(
            batch_id=batch_id,
            request_ids=tuple(request_ids),
            selected_profiles={},
            selected_nodes={node_id: len(request_ids)} if node_id else {},
            selected_services={service: len(request_ids)},
        ).to_public_dict()

    def _insert_cpu_request(
        self,
        conn: sqlite3.Connection,
        *,
        request_id: str,
        batch_id: str,
        service: str,
        item: dict[str, Any],
        immediate: bool,
        batch_key: str,
        node_id: str | None,
        now: float,
    ) -> None:
        conn.execute(
            """
            insert into requests(
                request_id, batch_id, request_kind, service_name, state, priority, immediate, batch_key,
                selected_profile_id, selected_node_id, request_json, created_at, updated_at
            ) values (?, ?, 'cpu', ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                batch_id,
                service,
                0 if immediate else 10,
                1 if immediate else 0,
                batch_key,
                f"cpu:{service}",
                node_id,
                json.dumps(item, sort_keys=True),
                now,
                now,
            ),
        )

    def work(
        self,
        *,
        registry: ProfileRegistry,
        runner: Runner,
        node_id: str | None = None,
        batch_id: str | None = None,
        batch_key: str | None = None,
        limit: int = 1,
        concurrency: int = 1,
        worker_id: str | None = None,
        lease_ttl_s: int = 900,
        heartbeat_interval_s: float = 5.0,
        warm_prefixes: bool = False,
        warm_min_group_size: int = 2,
        warm_max_output_tokens: int = 1,
        on_result: Callable[[QueueClaim, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        from .worker import BatchWorker

        warm_report = None
        if warm_prefixes:
            warm_report = self.warm_prefixes(
                registry=registry,
                runner=runner,
                node_id=node_id,
                batch_id=batch_id,
                batch_key=batch_key,
                min_group_size=warm_min_group_size,
                max_output_tokens=warm_max_output_tokens,
            )
        worker = BatchWorker(
            queue=self,
            registry=registry,
            runner=runner,
            worker_id=worker_id,
            lease_ttl_s=lease_ttl_s,
            heartbeat_interval_s=heartbeat_interval_s,
        )
        result = worker.run_once(
            node_id=node_id,
            batch_id=batch_id,
            batch_key=batch_key,
            limit=limit,
            concurrency=concurrency,
            on_result=on_result,
        )
        if warm_report is not None:
            result["prefix_warm"] = warm_report
        return result

    def claim_requests(
        self,
        *,
        node_id: str | None = None,
        batch_id: str | None = None,
        batch_key: str | None = None,
        limit: int = 1,
        leased_by: str,
        lease_ttl_s: int = 900,
    ) -> list[QueueClaim]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if lease_ttl_s < 1:
            raise ValueError("lease_ttl_s must be positive")
        now = time.time()
        conn = self._connect()
        claims: list[QueueClaim] = []
        try:
            conn.execute("begin immediate")
            selected_key = batch_key or self._select_next_batch_key(conn, node_id=node_id, batch_id=batch_id)
            if selected_key is None:
                conn.commit()
                return []
            rows = self._select_work_rows(conn, node_id=node_id, batch_id=batch_id, batch_key=selected_key, limit=limit)
            batch_ids = set()
            for row in rows:
                request_id = str(row["request_id"])
                lease_id = f"{leased_by}:{uuid.uuid4().hex}"
                updated = self._lease_row(
                    conn,
                    request_id=request_id,
                    lease_id=lease_id,
                    leased_by=leased_by,
                    lease_ttl_s=lease_ttl_s,
                    now=now,
                )
                if updated != 1:
                    continue
                batch_ids.add(str(row["batch_id"]))
                event = {"batch_id": row["batch_id"], "batch_key": row["batch_key"], "lease_id": lease_id, "leased_by": leased_by}
                self._insert_event(conn, request_id, "started", "running", event)
                claims.append(_row_claim(row, request_id=request_id, lease_id=lease_id))
            for batch_id_value in batch_ids:
                self._refresh_batch_row(conn, batch_id_value)
            conn.commit()
            return claims
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _lease_row(
        self,
        conn: sqlite3.Connection,
        *,
        request_id: str,
        lease_id: str,
        leased_by: str,
        lease_ttl_s: int,
        now: float,
    ) -> int:
        return conn.execute(
            """
            update requests
            set state = 'running', lease_id = ?, leased_by = ?, lease_expires_at = ?,
                heartbeat_at = ?, attempt_count = attempt_count + 1,
                started_at = ?, updated_at = ?
            where request_id = ? and state = 'queued'
            """,
            (lease_id, leased_by, now + lease_ttl_s, now, now, now, request_id),
        ).rowcount

    def finish_request(
        self,
        *,
        request_id: str,
        lease_id: str,
        state: str,
        result: dict[str, Any],
        error: str | None = None,
    ) -> bool:
        if state not in TERMINAL_STATES:
            raise ValueError(f"unsupported terminal state: {state}")
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("begin immediate")
            updated = conn.execute(
                """
                update requests
                set state = ?, result_json = ?, error = ?, completed_at = ?, updated_at = ?,
                    lease_id = null, leased_by = null, lease_expires_at = null, heartbeat_at = null
                where request_id = ? and lease_id = ? and state = 'running'
                """,
                (state, json.dumps(result, sort_keys=True), error, now, now, request_id, lease_id),
            ).rowcount
            if updated != 1:
                conn.rollback()
                return False
            row = conn.execute(
                "select batch_id, batch_key from requests where request_id = ?",
                (request_id,),
            ).fetchone()
            payload = {"batch_id": row["batch_id"], "batch_key": row["batch_key"]} if row is not None else {}
            self._insert_event(conn, request_id, state, state, payload)
            if row is not None:
                self._refresh_batch_row(conn, str(row["batch_id"]))
            conn.commit()
            self._write_notice(request_id, state, result)
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def heartbeat(self, *, lease_ids: Iterable[str], lease_ttl_s: int = 900) -> int:
        lease_list = [lease_id for lease_id in lease_ids if lease_id]
        if not lease_list:
            return 0
        now = time.time()
        with closing(self._connect()) as conn, conn:
            updated = 0
            for lease_id in lease_list:
                updated += conn.execute(
                    """
                    update requests
                    set heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                    where lease_id = ? and state = 'running'
                    """,
                    (now, now + lease_ttl_s, now, lease_id),
                ).rowcount
            return updated

    def requeue_expired_leases(self, *, max_attempts: int = 3, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        conn = self._connect()
        requeued = failed = 0
        notices: list[tuple[str, dict[str, Any]]] = []
        try:
            conn.execute("begin immediate")
            rows = conn.execute(
                """
                select * from requests
                where state = 'running' and lease_expires_at is not null and lease_expires_at <= ?
                order by lease_expires_at asc, request_id asc
                """,
                (now,),
            ).fetchall()
            batch_ids = set()
            for row in rows:
                batch_id_value, outcome = self._expire_running_row(
                    conn,
                    row=row,
                    max_attempts=max_attempts,
                    now=now,
                    notices=notices,
                )
                batch_ids.add(batch_id_value)
                requeued += 1 if outcome == "queued" else 0
                failed += 1 if outcome == "failed" else 0
            for batch_id_value in batch_ids:
                self._refresh_batch_row(conn, batch_id_value)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        for request_id, failure in notices:
            self._write_notice(request_id, "failed", failure)
        return {
            "format": QUEUE_FORMAT,
            "requeued_count": requeued,
            "failed_count": failed,
            "state": "reaped" if requeued or failed else "idle",
        }

    def warm_prefixes(
        self,
        *,
        registry: ProfileRegistry,
        runner: Runner,
        node_id: str | None = None,
        batch_id: str | None = None,
        batch_key: str | None = None,
        min_group_size: int = 2,
        max_output_tokens: int = 1,
        force: bool = False,
    ) -> dict[str, Any]:
        if min_group_size < 1:
            raise ValueError("min_group_size must be positive")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        warmed = failed = skipped = 0
        public_groups: list[dict[str, Any]] = []
        with closing(self._connect()) as conn, conn:
            groups = self._prefix_groups(conn, node_id=node_id, batch_id=batch_id, batch_key=batch_key, min_group_size=min_group_size)
            statuses = {group["warm_key"]: self._prefix_warm_status(conn, group["warm_key"]) for group in groups}
        for group in groups:
            status = statuses[group["warm_key"]]
            if status is not None and status["state"] == "warm" and not force:
                skipped += 1
                public_groups.append(_public_prefix_group(group, state="warm", skipped=True, status=status))
                continue
            with closing(self._connect()) as conn, conn:
                self._record_prefix_warm(conn, group, state="warming", result=None, error=None)
            try:
                profile = registry.get(group["profile_id"])
                request = _warm_request_from_group(group, max_output_tokens=max_output_tokens)
                result = _run_warm_request(runner, request, profile, group["node_id"])
                state = "warm" if result.get("status") == "completed" else "failed"
                with closing(self._connect()) as conn, conn:
                    self._record_prefix_warm(conn, group, state=state, result=result, error=None if state == "warm" else str(result.get("status", "failed")))
                if state == "warm":
                    warmed += 1
                else:
                    failed += 1
                public_groups.append(_public_prefix_group(group, state=state, skipped=False, result=result))
            except Exception as exc:
                failed += 1
                result = {
                    "format": "ds4-prefix-warm-failure-v1",
                    "status": "failed",
                    "error": str(exc),
                }
                with closing(self._connect()) as conn, conn:
                    self._record_prefix_warm(conn, group, state="failed", result=result, error=str(exc))
                public_groups.append(_public_prefix_group(group, state="failed", skipped=False, result=result))
        return {
            "format": PREFIX_WARM_REPORT_FORMAT,
            "state": "completed" if failed == 0 else "completed_with_failures",
            "group_count": len(public_groups),
            "warmed_count": warmed,
            "failed_count": failed,
            "skipped_count": skipped,
            "groups": public_groups,
        }

    def prefix_warm_status(self, *, skeleton_hash: str | None = None, node_id: str | None = None, profile_id: str | None = None) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if skeleton_hash is not None:
            clauses.append("skeleton_hash = ?")
            params.append(skeleton_hash)
        if node_id is not None:
            clauses.append("node_id = ?")
            params.append(node_id)
        if profile_id is not None:
            clauses.append("profile_id = ?")
            params.append(profile_id)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"""
                select * from prefix_warms
                {where}
                order by updated_at desc, warm_key asc
                """,
                tuple(params),
            ).fetchall()
        return {
            "format": PREFIX_WARM_STATUS_FORMAT,
            "state": "known" if rows else "cold",
            "statuses": [self._row_to_prefix_warm_status(row) for row in rows],
        }

    def _expire_running_row(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        max_attempts: int,
        now: float,
        notices: list[tuple[str, dict[str, Any]]],
    ) -> tuple[str, str]:
        request_id = str(row["request_id"])
        attempts = int(row["attempt_count"] or 0)
        payload = _lease_payload(row, attempts)
        if attempts >= max_attempts:
            failure = _lease_failure(request_id, attempts)
            conn.execute(
                """
                update requests
                set state = 'failed', result_json = ?, error = ?, completed_at = ?, updated_at = ?,
                    lease_id = null, leased_by = null, lease_expires_at = null, heartbeat_at = null
                where request_id = ? and state = 'running'
                """,
                (json.dumps(failure, sort_keys=True), failure["error"], now, now, request_id),
            )
            self._insert_event(conn, request_id, "lease_expired", "failed", payload)
            notices.append((request_id, failure))
            return str(row["batch_id"]), "failed"
        conn.execute(
            """
            update requests
            set state = 'queued', updated_at = ?,
                lease_id = null, leased_by = null, lease_expires_at = null, heartbeat_at = null
            where request_id = ? and state = 'running'
            """,
            (now, request_id),
        )
        self._insert_event(conn, request_id, "lease_expired", "queued", payload)
        return str(row["batch_id"]), "queued"

    def status(self, *, request_id: str | None = None, batch_id: str | None = None) -> dict[str, Any]:
        with closing(self._connect()) as conn, conn:
            if request_id is not None:
                row = conn.execute("select * from requests where request_id = ?", (request_id,)).fetchone()
                if row is None:
                    return {"format": REQUEST_STATUS_FORMAT, "request_id": request_id, "state": "unknown"}
                return self._row_to_request_status(row)
            if batch_id is not None:
                self._refresh_batch_row(conn, batch_id)
                row = conn.execute("select * from batches where batch_id = ?", (batch_id,)).fetchone()
                if row is None:
                    return {"format": BATCH_STATUS_FORMAT, "batch_id": batch_id, "state": "unknown"}
                return self._row_to_batch_status(row)
            rows = conn.execute(
                "select state, count(*) as count from requests group by state order by state"
            ).fetchall()
            counts = {str(row["state"]): int(row["count"]) for row in rows}
            event = conn.execute("select max(event_id) as newest_event_id from events").fetchone()
            return {
                "format": QUEUE_FORMAT,
                "state_counts": counts,
                "newest_event_id": int(event["newest_event_id"] or 0),
            }

    def cancel(self, *, request_id: str | None = None, batch_id: str | None = None, reason: str = "cancelled by operator") -> dict[str, Any]:
        if (request_id is None) == (batch_id is None):
            raise ValueError("exactly one of request_id or batch_id is required")
        now = time.time()
        cancelled: list[str] = []
        skipped: dict[str, int] = {}
        with closing(self._connect()) as conn, conn:
            if request_id is not None:
                rows = conn.execute("select * from requests where request_id = ?", (request_id,)).fetchall()
            else:
                rows = conn.execute("select * from requests where batch_id = ? order by request_id", (batch_id,)).fetchall()
            if not rows:
                return {
                    "format": QUEUE_FORMAT,
                    "state": "unknown",
                    "request_id": request_id,
                    "batch_id": batch_id,
                    "cancelled_count": 0,
                    "cancelled_request_ids": [],
                    "skipped_state_counts": {},
                }
            touched_batches = {str(row["batch_id"]) for row in rows}
            notices: list[tuple[str, dict[str, Any]]] = []
            for row in rows:
                state = str(row["state"])
                rid = str(row["request_id"])
                if state != "queued":
                    skipped[state] = skipped.get(state, 0) + 1
                    continue
                result = {
                    "format": "ds4-inference-cancelled-v1",
                    "request_id": rid,
                    "status": "cancelled",
                    "reason": reason,
                }
                updated = conn.execute(
                    """
                    update requests
                    set state = 'cancelled', result_json = ?, error = ?, completed_at = ?, updated_at = ?
                    where request_id = ? and state = 'queued'
                    """,
                    (json.dumps(result, sort_keys=True), reason, now, now, rid),
                ).rowcount
                if updated == 1:
                    cancelled.append(rid)
                    notices.append((rid, result))
                    self._insert_event(conn, rid, "cancelled", "cancelled", {"batch_id": str(row["batch_id"]), "reason": reason})
            for touched_batch in touched_batches:
                self._refresh_batch_row(conn, touched_batch)
        for rid, result in notices:
            self._write_notice(rid, "cancelled", result)
        return {
            "format": QUEUE_FORMAT,
            "state": "cancelled" if cancelled else "unchanged",
            "request_id": request_id,
            "batch_id": batch_id,
            "cancelled_count": len(cancelled),
            "cancelled_request_ids": cancelled,
            "skipped_state_counts": skipped,
        }

    def poll(self, *, after_event_id: int = 0, limit: int = 100) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "select * from events where event_id > ? order by event_id limit ?",
                (after_event_id, limit),
            ).fetchall()
        events = [self._row_to_event(row) for row in rows]
        return {
            "format": QUEUE_FORMAT,
            "after_event_id": after_event_id,
            "newest_event_id": events[-1]["event_id"] if events else after_event_id,
            "events": events,
        }

    def collect(self, *, request_id: str | None = None, batch_id: str | None = None) -> dict[str, Any]:
        if (request_id is None) == (batch_id is None):
            raise ValueError("exactly one of request_id or batch_id is required")
        with closing(self._connect()) as conn:
            if request_id is not None:
                row = conn.execute("select * from requests where request_id = ?", (request_id,)).fetchone()
                if row is None:
                    return {"format": QUEUE_FORMAT, "request_id": request_id, "state": "unknown"}
                payload = {"format": QUEUE_FORMAT, "request": self._row_to_request_status(row)}
                if row["result_json"]:
                    payload["result"] = json.loads(str(row["result_json"]))
                return payload
            rows = conn.execute("select * from requests where batch_id = ? order by request_id", (batch_id,)).fetchall()
            if not rows:
                return {"format": QUEUE_FORMAT, "batch_id": batch_id, "state": "unknown", "results": []}
            results = []
            for row in rows:
                item = {"request": self._row_to_request_status(row)}
                if row["result_json"]:
                    item["result"] = json.loads(str(row["result_json"]))
                results.append(item)
            return {"format": QUEUE_FORMAT, "batch_id": batch_id, "results": results}

    def _connect(self) -> sqlite3.Connection:
        busy_timeout_ms = _env_int("DS4_QUEUE_BUSY_TIMEOUT_MS", 5000)
        conn = sqlite3.connect(self.db_path, timeout=max(0.001, busy_timeout_ms / 1000.0))
        conn.row_factory = sqlite3.Row
        conn.execute(f"pragma busy_timeout = {busy_timeout_ms}")
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma synchronous = normal")
        for statement in QUEUE_SCHEMA_SQL:
            conn.execute(statement)
        self._ensure_request_columns(conn)
        self._ensure_batch_columns(conn)
        return conn

    def _ensure_request_columns(self, conn: sqlite3.Connection) -> None:
        existing = {str(row["name"]) for row in conn.execute("pragma table_info(requests)").fetchall()}
        columns = {
            "lease_id": "text",
            "leased_by": "text",
            "lease_expires_at": "real",
            "heartbeat_at": "real",
            "attempt_count": "integer not null default 0",
            "request_kind": "text not null default 'model'",
            "service_name": "text",
        }
        for name, spec in columns.items():
            if name not in existing:
                conn.execute(f"alter table requests add column {name} {spec}")

    def _ensure_batch_columns(self, conn: sqlite3.Connection) -> None:
        existing = {str(row["name"]) for row in conn.execute("pragma table_info(batches)").fetchall()}
        columns = {
            "cancelled_count": "integer not null default 0",
        }
        for name, spec in columns.items():
            if name not in existing:
                conn.execute(f"alter table batches add column {name} {spec}")

    def _select_next_batch_key(
        self,
        conn: sqlite3.Connection,
        *,
        node_id: str | None,
        batch_id: str | None,
    ) -> str | None:
        clauses = ["state = 'queued'"]
        params: list[Any] = []
        if node_id is not None:
            clauses.append("selected_node_id = ?")
            params.append(node_id)
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        row = conn.execute(
            f"""
            select batch_key
            from requests
            where {' and '.join(clauses)}
            order by priority asc, batch_key asc, created_at asc, request_id asc
            limit 1
            """,
            tuple(params),
        ).fetchone()
        return str(row["batch_key"]) if row is not None else None

    def _select_work_rows(
        self,
        conn: sqlite3.Connection,
        *,
        node_id: str | None,
        batch_id: str | None,
        batch_key: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        clauses = ["state = 'queued'"]
        params: list[Any] = []
        if node_id is not None:
            clauses.append("selected_node_id = ?")
            params.append(node_id)
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        if batch_key is not None:
            clauses.append("batch_key = ?")
            params.append(batch_key)
        params.append(limit)
        return conn.execute(
            f"""
            select * from requests
            where {' and '.join(clauses)}
            order by priority asc, batch_key asc, created_at asc, request_id asc
            limit ?
            """,
            tuple(params),
        ).fetchall()

    def _refresh_batch_row(self, conn: sqlite3.Connection, batch_id: str) -> None:
        rows = conn.execute(
            "select state, count(*) as count from requests where batch_id = ? group by state",
            (batch_id,),
        ).fetchall()
        counts = {str(row["state"]): int(row["count"]) for row in rows}
        request_count = sum(counts.values())
        queued = counts.get("queued", 0)
        running = counts.get("running", 0)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        if request_count == 0:
            state = "unknown"
        elif cancelled == request_count:
            state = "cancelled"
        elif completed + failed + cancelled == request_count:
            if failed:
                state = "completed_with_failures"
            elif cancelled:
                state = "completed_with_cancelled"
            else:
                state = "completed"
        elif running:
            state = "running"
        else:
            state = "queued"
        conn.execute(
            """
            update batches
            set state = ?, updated_at = ?, request_count = ?, queued_count = ?,
                running_count = ?, completed_count = ?, failed_count = ?, cancelled_count = ?
            where batch_id = ?
            """,
            (state, time.time(), request_count, queued, running, completed, failed, cancelled, batch_id),
        )

    def _queued_and_running_node_load(self) -> dict[str, int]:
        return queue_depths(self.db_path, request_kind="model")

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        request_id: str,
        event_type: str,
        state: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            "insert into events(created_at, request_id, event_type, state, payload_json) values (?, ?, ?, ?, ?)",
            (time.time(), request_id, event_type, state, json.dumps(payload, sort_keys=True)),
        )

    def _prefix_groups(
        self,
        conn: sqlite3.Connection,
        *,
        node_id: str | None,
        batch_id: str | None,
        batch_key: str | None,
        min_group_size: int,
    ) -> list[dict[str, Any]]:
        clauses = ["state = 'queued'", "request_kind = 'model'"]
        params: list[Any] = []
        if node_id is not None:
            clauses.append("selected_node_id = ?")
            params.append(node_id)
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        if batch_key is not None:
            clauses.append("batch_key = ?")
            params.append(batch_key)
        rows = conn.execute(
            f"select * from requests where {' and '.join(clauses)} order by selected_profile_id, selected_node_id, batch_key, created_at, request_id",
            tuple(params),
        ).fetchall()
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            raw = json.loads(str(row["request_json"]))
            input_data = dict(raw.get("input", {}))
            if input_data.get("messages") is not None:
                continue
            shared_prefix = input_data.get("shared_prefix")
            if not isinstance(shared_prefix, str) or not shared_prefix:
                continue
            skeleton_hash = str(input_data.get("skeleton_hash") or input_data.get("shared_prefix_hash") or _sha256_text(shared_prefix))
            shared_prefix_hash = _sha256_text(shared_prefix)
            system_hash = _sha256_text(str(input_data.get("system", "")))
            profile_id = str(row["selected_profile_id"])
            group_node_id = str(row["selected_node_id"]) if row["selected_node_id"] is not None else None
            chat = bool(raw.get("chat", False))
            warm_key = "|".join([group_node_id or "unassigned", profile_id, "chat" if chat else "completion", skeleton_hash, shared_prefix_hash, system_hash])
            group = groups.setdefault(
                warm_key,
                {
                    "format": PREFIX_GROUP_FORMAT,
                    "warm_key": warm_key,
                    "skeleton_hash": skeleton_hash,
                    "shared_prefix_hash": shared_prefix_hash,
                    "shared_prefix": shared_prefix,
                    "shared_prefix_bytes": len(shared_prefix.encode("utf-8")),
                    "profile_id": profile_id,
                    "node_id": group_node_id,
                    "chat": chat,
                    "system": input_data.get("system") if isinstance(input_data.get("system"), str) else None,
                    "sample_request_json": raw,
                    "request_ids": [],
                    "batch_keys": set(),
                },
            )
            group["request_ids"].append(str(row["request_id"]))
            group["batch_keys"].add(str(row["batch_key"]))
        result = []
        for group in groups.values():
            if len(group["request_ids"]) < min_group_size:
                continue
            group["batch_keys"] = sorted(group["batch_keys"])
            result.append(group)
        return sorted(result, key=lambda item: item["warm_key"])

    def _prefix_warm_status(self, conn: sqlite3.Connection, warm_key: str) -> dict[str, Any] | None:
        row = conn.execute("select * from prefix_warms where warm_key = ?", (warm_key,)).fetchone()
        return self._row_to_prefix_warm_status(row) if row is not None else None

    def _record_prefix_warm(self, conn: sqlite3.Connection, group: dict[str, Any], *, state: str, result: dict[str, Any] | None, error: str | None) -> None:
        now = time.time()
        warmed_at = now if state == "warm" else None
        conn.execute(
            """
            insert into prefix_warms(
                warm_key, skeleton_hash, shared_prefix_hash, profile_id, node_id,
                chat, shared_prefix_bytes, request_count, state, warmed_at,
                updated_at, result_json, error
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(warm_key) do update set
                state = excluded.state,
                warmed_at = coalesce(excluded.warmed_at, prefix_warms.warmed_at),
                updated_at = excluded.updated_at,
                request_count = excluded.request_count,
                result_json = excluded.result_json,
                error = excluded.error
            """,
            (
                group["warm_key"],
                group["skeleton_hash"],
                group["shared_prefix_hash"],
                group["profile_id"],
                group["node_id"],
                1 if group["chat"] else 0,
                int(group["shared_prefix_bytes"]),
                len(group["request_ids"]),
                state,
                warmed_at,
                now,
                json.dumps(result, sort_keys=True) if result is not None else None,
                error,
            ),
        )
        self._insert_event(
            conn,
            str(group["warm_key"]),
            "prefix_warm_" + state,
            state,
            {
                "skeleton_hash": group["skeleton_hash"],
                "profile_id": group["profile_id"],
                "node_id": group["node_id"],
                "request_count": len(group["request_ids"]),
            },
        )

    def _write_notice(self, request_id: str, state: str, result: dict[str, Any]) -> None:
        notice = {
            "format": REQUEST_NOTICE_FORMAT,
            "request_id": request_id,
            "state": state,
            "result": result,
        }
        (self.notices_dir / f"{request_id}.json").write_text(
            json.dumps(notice, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _row_to_request_status(self, row: sqlite3.Row) -> dict[str, Any]:
        status = {
            "format": REQUEST_STATUS_FORMAT,
            "service_name": row["service_name"],
            "immediate": bool(row["immediate"]),
            "selected_node_id": row["selected_node_id"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "lease_id": row["lease_id"],
            "leased_by": row["leased_by"],
            "lease_expires_at": row["lease_expires_at"],
            "heartbeat_at": row["heartbeat_at"],
            "attempt_count": int(row["attempt_count"] or 0),
            "error": row["error"],
        }
        status.update(_row_strings(row, "request_id", "batch_id", "request_kind", "state", "batch_key", "selected_profile_id"))
        return status

    def _row_to_batch_status(self, row: sqlite3.Row) -> dict[str, Any]:
        status = {
            "format": BATCH_STATUS_FORMAT,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }
        status.update(_row_strings(row, "batch_id", "state"))
        status.update(_row_ints(row, "request_count", "queued_count", "running_count", "completed_count", "failed_count", "cancelled_count"))
        return status

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": int(row["event_id"]),
            "created_at": float(row["created_at"]),
            "request_id": str(row["request_id"]),
            "event_type": str(row["event_type"]),
            "state": str(row["state"]),
            "payload": json.loads(str(row["payload_json"])),
        }

    def _row_to_prefix_warm_status(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "format": PREFIX_WARM_STATUS_FORMAT,
            "warm_key": str(row["warm_key"]),
            "skeleton_hash": str(row["skeleton_hash"]),
            "shared_prefix_hash": str(row["shared_prefix_hash"]),
            "profile_id": str(row["profile_id"]),
            "node_id": row["node_id"],
            "state": str(row["state"]),
            "request_count": int(row["request_count"]),
            "shared_prefix_bytes": int(row["shared_prefix_bytes"]),
            "warmed_at": row["warmed_at"],
            "updated_at": float(row["updated_at"]),
            "error": row["error"],
        }


def request_batch_key(request: InferenceRequest, profile: ModelProfile, assignment: SparkAssignment | None) -> str:
    return "|".join(
        [
            assignment.node_id if assignment is not None else "unassigned",
            profile.profile_id,
            "chat" if request.chat else "completion",
            request.job_class,
            input_bucket(request),
            output_bucket(request.max_output_tokens),
            thinking_bucket(request.thinking_budget_tokens),
            str(request.input.get("shared_prefix_hash") or request.input.get("skeleton_hash") or "no_prefix"),
            "immediate" if request.immediate else "queued",
        ]
    )


def cpu_batch_key(*, service: str, node_id: str | None, immediate: bool, timeout_s: float | None = None) -> str:
    return "|".join(
        [
            node_id or "unassigned",
            "cpu",
            service,
            _timeout_bucket(timeout_s),
            "immediate" if immediate else "queued",
        ]
    )


def queue_depths(db_path: str | Path, *, request_kind: str | None = None) -> dict[str, int]:
    path = Path(db_path)
    if not path.exists():
        return {}
    clauses = ["state in ('queued', 'running')", "selected_node_id is not null"]
    params: list[Any] = []
    if request_kind is not None:
        clauses.append("request_kind = ?")
        params.append(request_kind)
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute(
            f"""
            select selected_node_id, count(*) as count
            from requests
            where {' and '.join(clauses)}
            group by selected_node_id
            """,
            tuple(params),
        ).fetchall()
    return {str(node_id): int(count) for node_id, count in rows}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value in (None, "") else int(value)


def _timeout_bucket(timeout_s: float | None) -> str:
    if timeout_s is None:
        return "timeout_default"
    return f"timeout_{max(1, int(float(timeout_s)))}s"


def _validated_cpu_items(
    service: str,
    items: Iterable[dict[str, Any]],
    timeout_s: float | None,
) -> tuple[str, list[dict[str, Any]]]:
    service = str(service)
    item_list = [dict(item) for item in items]
    if not item_list:
        raise ValueError("cannot submit an empty CPU request set")
    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    from ds4_tools.cpu_batch import validate_cpu_submission
    validate_cpu_submission(service, len(item_list))
    return service, item_list


def _cpu_request_rows(
    service: str,
    item_list: list[dict[str, Any]],
    timeout_s: float | None,
) -> Iterable[tuple[str, dict[str, Any]]]:
    seen: set[str] = set()
    for index, item in enumerate(item_list):
        custom_id = str(item.get("custom_id") or item.get("request_id") or f"{service}-{index}")
        request_id = safe_request_id(custom_id, index, seen)
        item.setdefault("custom_id", request_id)
        if timeout_s is not None:
            item[CPU_QUEUE_TIMEOUT_KEY] = float(timeout_s)
        yield request_id, item


def _row_strings(row: sqlite3.Row, *names: str) -> dict[str, str]:
    return {name: str(row[name]) for name in names}


def _row_ints(row: sqlite3.Row, *names: str) -> dict[str, int]:
    return {name: int(row[name]) for name in names}


def _lease_payload(row: sqlite3.Row, attempts: int) -> dict[str, Any]:
    return {
        "batch_id": row["batch_id"],
        "batch_key": row["batch_key"],
        "lease_id": row["lease_id"],
        "attempt_count": attempts,
    }


def _lease_failure(request_id: str, attempts: int) -> dict[str, Any]:
    return {
        "format": "ds4-inference-failure-v1",
        "request_id": request_id,
        "status": "lease_expired",
        "error": f"lease expired after {attempts} attempts",
    }


def _row_claim(row: sqlite3.Row, *, request_id: str, lease_id: str) -> QueueClaim:
    return QueueClaim(
        request_id=request_id,
        batch_id=str(row["batch_id"]),
        batch_key=str(row["batch_key"]),
        request_kind=str(row["request_kind"]),
        selected_profile_id=str(row["selected_profile_id"]),
        selected_node_id=str(row["selected_node_id"]) if row["selected_node_id"] else None,
        lease_id=lease_id,
        request=_row_request(row),
        service_name=str(row["service_name"]) if row["service_name"] else None,
        payload=json.loads(str(row["request_json"])),
    )


def _row_request(row: sqlite3.Row) -> InferenceRequest | None:
    if str(row["request_kind"]) != "model":
        return None
    return InferenceRequest.from_json(json.loads(str(row["request_json"])))


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


def _warm_request_from_group(group: dict[str, Any], *, max_output_tokens: int) -> InferenceRequest:
    raw = dict(group["sample_request_json"])
    warm_input: dict[str, Any] = {
        "shared_prefix": group["shared_prefix"],
        "suffix": "\nCACHE_WARM_ONLY",
        "skeleton_hash": group["skeleton_hash"],
        "shared_prefix_hash": group["shared_prefix_hash"],
    }
    if group.get("system"):
        warm_input["system"] = group["system"]
    raw.update(
        {
            "request_id": "prefix-warm-" + hashlib.sha256(str(group["warm_key"]).encode("utf-8")).hexdigest()[:16],
            "immediate": True,
            "max_output_tokens": max_output_tokens,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": warm_input,
            "output_contract": {"format": "ds4-prefix-cache-warm-v1"},
        }
    )
    return InferenceRequest.from_json(raw)


def _run_warm_request(runner: Runner, request: InferenceRequest, profile: ModelProfile, node_id: str | None) -> dict[str, Any]:
    if hasattr(runner, "run_one_on_node"):
        return runner.run_one_on_node(request, profile, node_id)  # type: ignore[attr-defined]
    if hasattr(runner, "run_one"):
        return runner.run_one(request, profile)
    return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text="warm skipped: runner lacks run_one", status="transport_failed")


def _public_prefix_group(group: dict[str, Any], *, state: str, skipped: bool, status: dict[str, Any] | None = None, result: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "format": PREFIX_GROUP_FORMAT,
        "warm_key": group["warm_key"],
        "skeleton_hash": group["skeleton_hash"],
        "shared_prefix_hash": group["shared_prefix_hash"],
        "profile_id": group["profile_id"],
        "node_id": group["node_id"],
        "chat": group["chat"],
        "request_count": len(group["request_ids"]),
        "request_ids": list(group["request_ids"]),
        "batch_keys": list(group["batch_keys"]),
        "shared_prefix_bytes": group["shared_prefix_bytes"],
        "state": state,
        "skipped": skipped,
    }
    if status is not None:
        payload["status"] = status
    if result is not None:
        payload["result_status"] = result.get("status")
        payload["usage"] = result.get("usage")
        payload["transport"] = result.get("transport")
    return payload


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
