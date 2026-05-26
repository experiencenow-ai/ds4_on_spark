from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
import subprocess
import time
import uuid
from typing import Any

TRANSFER_TOPOLOGY_FORMAT = "ds4-transfer-topology-v1"
TRANSFER_REQUEST_FORMAT = "ds4-transfer-request-v1"
TRANSFER_PLAN_FORMAT = "ds4-transfer-plan-v1"
TRANSFER_RESULT_FORMAT = "ds4-transfer-result-v1"


@dataclass(frozen=True)
class TransferNode:
    node_id: str
    host: str
    root_allowlist: tuple[str, ...]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "TransferNode":
        required = ["node_id", "host", "root_allowlist"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"transfer node missing fields: {missing}")
        roots = tuple(_normalize_root(str(root)) for root in data["root_allowlist"])
        if not roots:
            raise ValueError("transfer node requires at least one root_allowlist entry")
        return TransferNode(node_id=str(data["node_id"]), host=str(data["host"]), root_allowlist=roots)


@dataclass(frozen=True)
class TransferTopology:
    fabric_id: str
    fabric_hint: str
    nodes: dict[str, TransferNode]
    rsync_options: tuple[str, ...]
    ssh_options: tuple[str, ...]

    @staticmethod
    def load(path: str | Path) -> "TransferTopology":
        with Path(path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("format") != TRANSFER_TOPOLOGY_FORMAT:
            raise ValueError(f"unsupported transfer topology format: {data.get('format')!r}")
        nodes = {node.node_id: node for node in (TransferNode.from_json(item) for item in data.get("nodes", []))}
        if not nodes:
            raise ValueError("transfer topology requires at least one node")
        return TransferTopology(
            fabric_id=str(data.get("fabric_id", "unnamed")),
            fabric_hint=str(data.get("fabric_hint", "unknown")),
            nodes=nodes,
            rsync_options=tuple(str(item) for item in data.get("rsync_options", _default_rsync_options())),
            ssh_options=tuple(str(item) for item in data.get("ssh_options", _default_ssh_options())),
        )

    def get_node(self, node_id: str) -> TransferNode:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise ValueError(f"unknown transfer node_id: {node_id}") from exc


@dataclass(frozen=True)
class TransferRequest:
    request_id: str
    source_node: str
    source_path: str
    destination_node: str
    destination_path: str
    recursive: bool
    delete_extra: bool
    dry_run: bool
    raw: dict[str, Any]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "TransferRequest": 
        if data.get("format") != TRANSFER_REQUEST_FORMAT:
            raise ValueError(f"unsupported transfer request format: {data.get('format')!r}")
        required = ["source_node", "source_path", "destination_node", "destination_path"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"transfer request missing fields: {missing}")
        return TransferRequest(
            request_id=str(data.get("request_id") or f"transfer-{uuid.uuid4().hex[:16]}"),
            source_node=str(data["source_node"]),
            source_path=str(data["source_path"]),
            destination_node=str(data["destination_node"]),
            destination_path=str(data["destination_path"]),
            recursive=bool(data.get("recursive", True)),
            delete_extra=bool(data.get("delete_extra", False)),
            dry_run=bool(data.get("dry_run", False)),
            raw=dict(data),
        )


def plan_transfer(topology: TransferTopology, request: TransferRequest) -> dict[str, Any]:
    if request.source_node == request.destination_node:
        raise ValueError("transfer requires distinct source and destination nodes")
    source = topology.get_node(request.source_node)
    destination = topology.get_node(request.destination_node)
    _validate_allowed_path(source, request.source_path)
    _validate_allowed_path(destination, request.destination_path)

    source_path = _source_path_for_rsync(request.source_path, request.recursive)
    destination_spec = f"{destination.host}:{request.destination_path}"
    remote_rsync = ["rsync", *topology.rsync_options]
    if request.delete_extra:
        remote_rsync.append("--delete")
    if request.dry_run:
        remote_rsync.append("--dry-run")
    remote_rsync.extend([source_path, destination_spec])
    argv = ["ssh", *topology.ssh_options, source.host, *remote_rsync]
    return {
        "format": TRANSFER_PLAN_FORMAT,
        "request_id": request.request_id,
        "fabric_id": topology.fabric_id,
        "fabric_hint": topology.fabric_hint,
        "method": "source_initiated_rsync_over_ssh_no_compress",
        "source_node": request.source_node,
        "destination_node": request.destination_node,
        "source_host": source.host,
        "destination_host": destination.host,
        "source_path": request.source_path,
        "destination_path": request.destination_path,
        "direct_data_path": f"{source.host} -> {destination.host}",
        "argv": argv,
        "argv_shell": " ".join(shlex.quote(item) for item in argv),
        "notes": [
            "Run rsync on the source Spark so payload flows source->destination over the Spark fabric instead of through the controller.",
            "Compression is disabled by default because 200Gbps LAN transfer should spend CPU on checksums and I/O, not compression.",
        ],
    }


def run_transfer(topology: TransferTopology, request: TransferRequest, *, timeout_s: int = 3600, dry_run: bool = False) -> dict[str, Any]:
    started = time.time()
    effective_request = request if not dry_run else TransferRequest(
        request_id=request.request_id,
        source_node=request.source_node,
        source_path=request.source_path,
        destination_node=request.destination_node,
        destination_path=request.destination_path,
        recursive=request.recursive,
        delete_extra=request.delete_extra,
        dry_run=True,
        raw=request.raw,
    )
    plan = plan_transfer(topology, effective_request)
    if dry_run or request.dry_run:
        return {
            "format": TRANSFER_RESULT_FORMAT,
            "request_id": request.request_id,
            "status": "planned",
            "ok": True,
            "duration_s": round(time.time() - started, 6),
            "plan": plan,
        }
    completed = subprocess.run(plan["argv"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_s, check=False)
    return {
        "format": TRANSFER_RESULT_FORMAT,
        "request_id": request.request_id,
        "status": "completed" if completed.returncode == 0 else "failed",
        "ok": completed.returncode == 0,
        "duration_s": round(time.time() - started, 6),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-8000:],
        "stderr_tail": completed.stderr[-8000:],
        "plan": plan,
    }


def _default_rsync_options() -> list[str]:
    return [
        "-a",
        "--whole-file",
        "--inplace",
        "--partial",
        "--numeric-ids",
        "--no-compress",
        "--info=stats2,progress2",
        "--protect-args",
    ]


def _default_ssh_options() -> list[str]:
    return [
        "-T",
        "-o", "Compression=no",
        "-o", "BatchMode=yes",
        "-x",
    ]


def _normalize_root(root: str) -> str:
    if not root.startswith("/"):
        raise ValueError("root_allowlist entries must be absolute")
    return str(Path(root)).rstrip("/") or "/"


def _validate_allowed_path(node: TransferNode, path: str) -> None:
    if not path.startswith("/"):
        raise ValueError("transfer paths must be absolute")
    normalized = str(Path(path))
    for root in node.root_allowlist:
        if normalized == root or normalized.startswith(root.rstrip("/") + "/"):
            return
    raise ValueError(f"path {path!r} is outside allowlist for {node.node_id}")


def _source_path_for_rsync(path: str, recursive: bool) -> str:
    if recursive and path.endswith("/"):
        return path
    return path
