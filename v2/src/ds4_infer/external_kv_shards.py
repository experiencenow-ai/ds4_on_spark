from __future__ import annotations

import json
import sqlite3
from typing import Any


def validate_external_kv_shards(shard_list: list[dict[str, Any]], *, total_bytes: int) -> None:
    if not shard_list:
        raise ValueError("external KV objects must be declared with explicit node-local shard manifests; spark0 aggregation is forbidden")
    seen: set[tuple[str, int]] = set()
    stage_counts: set[int] = set()
    for shard in shard_list:
        node_id = str(shard.get("node_id") or "")
        if not node_id:
            raise ValueError("external KV shard missing node_id")
        stage_index = int(shard.get("stage_index", 0) or 0)
        stage_count = int(shard.get("stage_count", len(shard_list)) or len(shard_list))
        if stage_index < 0 or stage_count < 1 or stage_index >= stage_count:
            raise ValueError("external KV shard has invalid stage_index/stage_count")
        key = (node_id, stage_index)
        if key in seen:
            raise ValueError(f"duplicate external KV shard for {node_id} stage {stage_index}")
        seen.add(key)
        stage_counts.add(stage_count)
    if len(stage_counts) != 1:
        raise ValueError("external KV shards must agree on stage_count")
    stage_count = next(iter(stage_counts))
    if stage_count != len(shard_list):
        raise ValueError("external KV shard manifest must include exactly one shard per pipeline stage")
    if int(total_bytes) > 0 and stage_count > 1 and len({str(shard.get("node_id")) for shard in shard_list}) < stage_count:
        raise ValueError("external KV pipeline shards must be node-local, not aggregated on a single node")


def update_external_kv_shard(conn: sqlite3.Connection, *, namespace: str, kv_key: str, service_id: str, update: dict[str, Any], default_state: str, now: float) -> int:
    clauses = ["state=?", "updated_at=?", "last_used_at=?"]
    params: list[Any] = [str(update.get("state") or default_state), now, now]
    if "bytes" in update:
        clauses.append("bytes=?")
        params.append(max(0, int(update["bytes"] or 0)))
    if "storage_uri" in update:
        clauses.append("storage_uri=?")
        params.append(str(update["storage_uri"]) if update.get("storage_uri") is not None else None)
    if "gpu_resident" in update:
        clauses.append("gpu_resident=?")
        params.append(1 if bool(update.get("gpu_resident")) else 0)
    if "metadata" in update:
        clauses.append("metadata_json=?")
        params.append(json.dumps(dict(update.get("metadata") or {}), sort_keys=True))
    params.extend([namespace, kv_key, service_id])
    where = "namespace=? and kv_key=? and service_id=?"
    if update.get("node_id") is not None:
        where += " and node_id=?"
        params.append(str(update["node_id"]))
    if update.get("stage_index") is not None:
        where += " and stage_index=?"
        params.append(int(update["stage_index"]))
    return int(conn.execute(f"update kv_memory_shards set {', '.join(clauses)} where {where}", tuple(params)).rowcount)


def external_kv_object_state_from_shards(conn: sqlite3.Connection, *, namespace: str, kv_key: str, service_id: str, requested_state: str) -> str:
    states = [str(row["state"]) for row in conn.execute("select state from kv_memory_shards where namespace=? and kv_key=? and service_id=?", (namespace, kv_key, service_id)).fetchall()]
    if not states:
        return "missing_shards"
    ready_states = {"ready_on_ssd", "gpu_resident", "available", "archived", "ready"}
    if all(state in ready_states for state in states):
        return requested_state
    if any(state in {"failed", "corrupt", "missing"} for state in states):
        return "degraded"
    return "partial"
