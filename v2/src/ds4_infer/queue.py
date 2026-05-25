from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

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
TERMINAL_STATES = {"completed", "failed"}


@dataclass(frozen=True)
class QueueSubmission:
    batch_id: str
    request_ids: tuple[str, ...]
    selected_profiles: dict[str, int]
    selected_nodes: dict[str, int]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "format": QUEUE_FORMAT,
            "batch_id": self.batch_id,
            "state": "queued",
            "request_count": len(self.request_ids),
            "request_ids": list(self.request_ids),
            "selected_profiles": self.selected_profiles,
            "selected_nodes": self.selected_nodes,
        }


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
        batch_id = batch_id or f"batch-{int(time.time() * 1000)}"
        request_ids: list[str] = []
        selected_profiles: dict[str, int] = {}
        selected_nodes: dict[str, int] = {}
        node_load = self._queued_and_running_node_load()
        now = time.time()
        with self._connection() as conn:
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
                        request_id, batch_id, state, priority, immediate, batch_key,
                        selected_profile_id, selected_node_id, request_json,
                        created_at, updated_at
                    ) values (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
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
        return QueueSubmission(batch_id=batch_id, request_ids=tuple(request_ids), selected_profiles=selected_profiles, selected_nodes=selected_nodes).to_public_dict()

    def work(
        self,
        *,
        registry: ProfileRegistry,
        runner: Runner,
        node_id: str | None = None,
        batch_key: str | None = None,
        limit: int = 1,
        warm_prefixes: bool = False,
        warm_min_group_size: int = 2,
        warm_max_output_tokens: int = 1,
    ) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be positive")
        warm_report = None
        if warm_prefixes:
            warm_report = self.warm_prefixes(
                registry=registry,
                runner=runner,
                node_id=node_id,
                batch_key=batch_key,
                min_group_size=warm_min_group_size,
                max_output_tokens=warm_max_output_tokens,
            )
        claimed = completed = failed = 0
        groups: dict[str, dict[str, int]] = {}
        with self._connection() as conn:
            rows = self._select_work_rows(conn, node_id=node_id, batch_key=batch_key, limit=limit)
            for row in rows:
                request_id = str(row["request_id"])
                now = time.time()
                updated = conn.execute(
                    "update requests set state = 'running', started_at = ?, updated_at = ? where request_id = ? and state = 'queued'",
                    (now, now, request_id),
                ).rowcount
                if updated != 1:
                    continue
                claimed += 1
                self._insert_event(conn, request_id, "started", "running", {"batch_id": row["batch_id"], "batch_key": row["batch_key"]})
                request = InferenceRequest.from_json(json.loads(str(row["request_json"])))
                try:
                    profile = registry.get(str(row["selected_profile_id"]))
                    if hasattr(runner, "run_one_on_node"):
                        result = runner.run_one_on_node(request, profile, str(row["selected_node_id"]) if row["selected_node_id"] else None)
                    else:
                        result = runner.run_one(request, profile)
                    if row["selected_node_id"]:
                        result["selected_node"] = {"node_id": str(row["selected_node_id"])}
                    result["batch_key"] = str(row["batch_key"])
                    state = "completed" if result.get("status") == "completed" else "failed"
                    if state == "completed":
                        completed += 1
                    else:
                        failed += 1
                    self._finish_request(conn, request_id, state, result, None if state == "completed" else str(result.get("status", "failed")))
                    batch_key_value = str(row["batch_key"])
                    group = groups.setdefault(batch_key_value, {"claimed_count": 0, "completed_count": 0, "failed_count": 0})
                    group["claimed_count"] += 1
                    if state == "completed":
                        group["completed_count"] += 1
                    else:
                        group["failed_count"] += 1
                except Exception as exc:
                    failed += 1
                    failure = {
                        "format": "ds4-inference-failure-v1",
                        "request_id": request_id,
                        "status": "runner_exception",
                        "error": str(exc),
                    }
                    self._finish_request(conn, request_id, "failed", failure, str(exc))
                    batch_key_value = str(row["batch_key"])
                    group = groups.setdefault(batch_key_value, {"claimed_count": 0, "completed_count": 0, "failed_count": 0})
                    group["claimed_count"] += 1
                    group["failed_count"] += 1
            for batch_id in {str(row["batch_id"]) for row in rows}:
                self._refresh_batch_row(conn, batch_id)
        result = {
            "format": QUEUE_FORMAT,
            "claimed_count": claimed,
            "completed_count": completed,
            "failed_count": failed,
            "state": "worked" if claimed else "idle",
            "groups": [dict({"batch_key": key}, **value) for key, value in sorted(groups.items())],
        }
        if warm_report is not None:
            result["prefix_warm"] = warm_report
        return result

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
        with self._connection() as conn:
            groups = self._prefix_groups(conn, node_id=node_id, batch_id=batch_id, batch_key=batch_key, min_group_size=min_group_size)
            statuses = {group["warm_key"]: self._prefix_warm_status(conn, group["warm_key"]) for group in groups}
        for group in groups:
            status = statuses[group["warm_key"]]
            if status is not None and status["state"] == "warm" and not force:
                skipped += 1
                public_groups.append(_public_prefix_group(group, state="warm", skipped=True, status=status))
                continue
            with self._connection() as conn:
                self._record_prefix_warm(conn, group, state="warming", result=None, error=None)
            try:
                profile = registry.get(group["profile_id"])
                request = _warm_request_from_group(group, max_output_tokens=max_output_tokens)
                result = _run_warm_request(runner, request, profile, group["node_id"])
                state = "warm" if result.get("status") == "completed" else "failed"
                with self._connection() as conn:
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
                with self._connection() as conn:
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
        with self._connection() as conn:
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

    def status(self, *, request_id: str | None = None, batch_id: str | None = None) -> dict[str, Any]:
        with self._connection() as conn:
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
            rows = conn.execute("select state, count(*) as count from requests group by state order by state").fetchall()
            counts = {str(row["state"]): int(row["count"]) for row in rows}
            event = conn.execute("select max(event_id) as newest_event_id from events").fetchone()
            return {"format": QUEUE_FORMAT, "state_counts": counts, "newest_event_id": int(event["newest_event_id"] or 0)}

    def poll(self, *, after_event_id: int = 0, limit: int = 100) -> dict[str, Any]:
        with self._connection() as conn:
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
        with self._connection() as conn:
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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma synchronous = normal")
        conn.execute(
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
                failed_count integer not null default 0
            )
            """
        )
        conn.execute(
            """
            create table if not exists requests(
                request_id text primary key,
                batch_id text not null,
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
                completed_at real
            )
            """
        )
        conn.execute("create index if not exists idx_requests_state_node_key on requests(state, selected_node_id, batch_key, priority, created_at)")
        conn.execute("create index if not exists idx_requests_batch on requests(batch_id, state)")
        conn.execute(
            """
            create table if not exists events(
                event_id integer primary key autoincrement,
                created_at real not null,
                request_id text not null,
                event_type text not null,
                state text not null,
                payload_json text not null
            )
            """
        )
        conn.execute(
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
            """
        )
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _select_work_rows(self, conn: sqlite3.Connection, *, node_id: str | None, batch_key: str | None, limit: int) -> list[sqlite3.Row]:
        clauses = ["state = 'queued'"]
        params: list[Any] = []
        if node_id is not None:
            clauses.append("selected_node_id = ?")
            params.append(node_id)
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

    def _finish_request(self, conn: sqlite3.Connection, request_id: str, state: str, result: dict[str, Any], error: str | None) -> None:
        now = time.time()
        conn.execute(
            """
            update requests
            set state = ?, result_json = ?, error = ?, completed_at = ?, updated_at = ?
            where request_id = ?
            """,
            (state, json.dumps(result, sort_keys=True), error, now, now, request_id),
        )
        row = conn.execute("select batch_id, batch_key from requests where request_id = ?", (request_id,)).fetchone()
        payload = {"batch_id": row["batch_id"], "batch_key": row["batch_key"]} if row is not None else {}
        self._insert_event(conn, request_id, state, state, payload)
        self._write_notice(request_id, state, result)

    def _refresh_batch_row(self, conn: sqlite3.Connection, batch_id: str) -> None:
        rows = conn.execute("select state, count(*) as count from requests where batch_id = ? group by state", (batch_id,)).fetchall()
        counts = {str(row["state"]): int(row["count"]) for row in rows}
        request_count = sum(counts.values())
        queued = counts.get("queued", 0)
        running = counts.get("running", 0)
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        if request_count == 0:
            state = "unknown"
        elif completed + failed == request_count:
            state = "completed" if failed == 0 else "completed_with_failures"
        elif running:
            state = "running"
        else:
            state = "queued"
        conn.execute(
            """
            update batches
            set state = ?, updated_at = ?, request_count = ?, queued_count = ?, running_count = ?, completed_count = ?, failed_count = ?
            where batch_id = ?
            """,
            (state, time.time(), request_count, queued, running, completed, failed, batch_id),
        )

    def _queued_and_running_node_load(self) -> dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                select selected_node_id, count(*) as count
                from requests
                where state in ('queued', 'running') and selected_node_id is not null
                group by selected_node_id
                """
            ).fetchall()
        return {str(row["selected_node_id"]): int(row["count"]) for row in rows}

    def _insert_event(self, conn: sqlite3.Connection, request_id: str, event_type: str, state: str, payload: dict[str, Any]) -> None:
        conn.execute(
            "insert into events(created_at, request_id, event_type, state, payload_json) values (?, ?, ?, ?, ?)",
            (time.time(), request_id, event_type, state, json.dumps(payload, sort_keys=True)),
        )

    def _prefix_groups(self, conn: sqlite3.Connection, *, node_id: str | None, batch_id: str | None, batch_key: str | None, min_group_size: int) -> list[dict[str, Any]]:
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
        (self.notices_dir / f"{request_id}.json").write_text(json.dumps(notice, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _row_to_request_status(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "format": REQUEST_STATUS_FORMAT,
            "request_id": str(row["request_id"]),
            "batch_id": str(row["batch_id"]),
            "state": str(row["state"]),
            "immediate": bool(row["immediate"]),
            "batch_key": str(row["batch_key"]),
            "selected_profile_id": str(row["selected_profile_id"]),
            "selected_node_id": row["selected_node_id"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "error": row["error"],
        }

    def _row_to_batch_status(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "format": BATCH_STATUS_FORMAT,
            "batch_id": str(row["batch_id"]),
            "state": str(row["state"]),
            "request_count": int(row["request_count"]),
            "queued_count": int(row["queued_count"]),
            "running_count": int(row["running_count"]),
            "completed_count": int(row["completed_count"]),
            "failed_count": int(row["failed_count"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

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
