from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

from .profiles import ModelProfile, ProfileRegistry
from .runners import Runner
from .schemas import InferenceRequest
from .topology import SparkAssignment, SparkTopology

QUEUE_FORMAT = "ds4-inference-queue-v1"
REQUEST_STATUS_FORMAT = "ds4-inference-request-status-v1"
REQUEST_NOTICE_FORMAT = "ds4-inference-completion-notice-v1"
BATCH_STATUS_FORMAT = "ds4-inference-batch-status-v1"
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
        with self._connect() as conn:
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
    ) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be positive")
        claimed = completed = failed = 0
        groups: dict[str, dict[str, int]] = {}
        with self._connect() as conn:
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
            for batch_id in {str(row["batch_id"]) for row in rows}:
                self._refresh_batch_row(conn, batch_id)
        # derive group completions after loop so failure/completion counts are accurate
        return {
            "format": QUEUE_FORMAT,
            "claimed_count": claimed,
            "completed_count": completed,
            "failed_count": failed,
            "state": "worked" if claimed else "idle",
            "groups": [dict({"batch_key": key}, **value) for key, value in sorted(groups.items())],
        }

    def status(self, *, request_id: str | None = None, batch_id: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        return conn

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
        with self._connect() as conn:
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
