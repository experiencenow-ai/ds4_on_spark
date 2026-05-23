#!/usr/bin/env python3
"""Minimal multi-Spark layer-pipeline proof.

This is intentionally model-free: it proves the orchestration and data movement
shape independently from DS4 CUDA kernels. Each rank processes a fixed-size
microbatch payload, forwards it to the next rank, and reports steady-state
throughput. Compare it with the built-in sequential baseline to estimate the
pipeline gain when compute is balanced and network is hidden.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.spark_ssh import ssh_prefix as build_ssh_prefix


COMMON_SSH_OPTS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts",
]


DEFAULT_MANIFEST = {
    "nodes": [
        {"name": "spark0", "ssh": "spark0@aitopatom-9ab9.local"},
        {"name": "spark1", "ssh": "spark1@edgexpert-d623.local"},
        {
            "name": "spark2",
            "ssh": "spark2@10.10.2.2",
            "jump": "spark0@aitopatom-9ab9.local",
        },
    ],
    "pipeline": [
        {
            "src": "spark0",
            "dst": "spark1",
            "src_bind": "10.10.1.1",
            "dst_bind": "10.10.1.252",
            "port": 6301,
        },
        {
            "src": "spark1",
            "dst": "spark2",
            "src_bind": "10.10.5.1",
            "dst_bind": "10.10.5.2",
            "port": 6302,
        },
    ],
}

HEADER = struct.Struct("!QQ")
REMOTE_SCRIPT = "/tmp/ds4_layer_pipeline_mre.py"
REMOTE_C_SRC = "/tmp/ds4_layer_pipeline_mre.c"
REMOTE_C_BIN = "/tmp/ds4_layer_pipeline_mre_c"


@dataclass(frozen=True)
class Node:
    name: str
    ssh: str
    jump: str | None


@dataclass(frozen=True)
class Link:
    src: str
    dst: str
    src_bind: str
    dst_bind: str
    port: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or host the Spark pipeline MRE.")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--role", choices=["controller", "rank", "sequential"], default="controller")
    parser.add_argument("--rank", type=int, default=0)
    parser.add_argument("--world-size", type=int, default=1)
    parser.add_argument("--items", type=int, default=120)
    parser.add_argument("--payload-bytes", type=int, default=(16 * 1024 * 1024))
    parser.add_argument("--stage-ms", type=float, default=22.2)
    parser.add_argument("--listen-bind", default="")
    parser.add_argument("--listen-port", type=int, default=0)
    parser.add_argument("--next-bind", default="")
    parser.add_argument("--next-host", default="")
    parser.add_argument("--next-port", type=int, default=0)
    parser.add_argument("--socket-buffer-mib", type=int, default=64)
    parser.add_argument("--startup-sleep", type=float, default=0.7)
    parser.add_argument("--worker", choices=["python", "c"], default="python")
    parser.add_argument("--no-deploy", action="store_true")
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def load_manifest(path: Path | None) -> tuple[dict[str, Node], list[Link]]:
    raw = DEFAULT_MANIFEST if path is None else json.loads(path.read_text())
    nodes = {
        item["name"]: Node(
            name=item["name"],
            ssh=item["ssh"],
            jump=item.get("jump"),
        )
        for item in raw["nodes"]
    }
    links = [
        Link(
            src=item["src"],
            dst=item["dst"],
            src_bind=item["src_bind"],
            dst_bind=item["dst_bind"],
            port=int(item["port"]),
        )
        for item in raw["pipeline"]
    ]
    return nodes, links


def pipeline_order(links: list[Link]) -> list[str]:
    if not links:
        raise ValueError("pipeline requires at least one link")
    order = [links[0].src]
    for link in links:
        if link.src != order[-1]:
            raise ValueError(f"non-linear pipeline link {link.src}->{link.dst}")
        order.append(link.dst)
    return order


def scp_prefix(node: Node) -> list[str]:
    cmd = ["scp", *COMMON_SSH_OPTS]
    if node.jump is not None:
        cmd.extend(["-J", node.jump])
    return cmd


def deploy(nodes: dict[str, Node], order: list[str], worker: str) -> None:
    local = Path(__file__).resolve()
    c_src = local.with_suffix(".c")
    for name in order:
        node = nodes[name]
        dst = f"{node.ssh}:{REMOTE_SCRIPT}"
        result = subprocess.run(
            [*scp_prefix(node), str(local), dst],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise RuntimeError(f"scp to {name} failed: {result.stderr.strip()}")
        if worker == "c":
            result = subprocess.run(
                [*scp_prefix(node), str(c_src), f"{node.ssh}:{REMOTE_C_SRC}"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                raise RuntimeError(f"scp C worker to {name} failed: {result.stderr.strip()}")
            compile_cmd = f"gcc -O3 -Wall -Wextra -o {REMOTE_C_BIN} {REMOTE_C_SRC}"
            result = subprocess.run(
                [*build_ssh_prefix(node.ssh, node.jump, COMMON_SSH_OPTS), compile_cmd],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                raise RuntimeError(f"compile C worker on {name} failed: {result.stderr.strip()}")


def set_sock_buffers(sock: socket.socket, mib: int) -> None:
    if mib <= 0:
        return
    value = mib * 1024 * 1024
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, value)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, value)


def connect_next(host: str, port: int, bind: str, buffer_mib: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    set_sock_buffers(sock, buffer_mib)
    if bind:
        sock.bind((bind, 0))
    deadline = time.time() + 30.0
    while True:
        try:
            sock.connect((host, port))
            return sock
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.1)


def accept_prev(bind: str, port: int, buffer_mib: int) -> socket.socket:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    set_sock_buffers(server, buffer_mib)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((bind, port))
    server.listen(1)
    conn, _addr = server.accept()
    set_sock_buffers(conn, buffer_mib)
    server.close()
    return conn


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        data = sock.recv(size - len(chunks))
        if not data:
            raise EOFError("socket closed")
        chunks.extend(data)
    return bytes(chunks)


def stage_work(stage_seconds: float) -> None:
    if stage_seconds > 0.0:
        time.sleep(stage_seconds)


def run_rank(args: argparse.Namespace) -> int:
    stage_seconds = args.stage_ms / 1000.0
    prev_sock = None
    next_sock = None
    payload = bytearray(args.payload_bytes)
    started = time.perf_counter()
    if args.rank > 0:
        prev_sock = accept_prev(args.listen_bind, args.listen_port, args.socket_buffer_mib)
    if args.rank < (args.world_size - 1):
        next_sock = connect_next(args.next_host, args.next_port, args.next_bind, args.socket_buffer_mib)
    first_item = 0.0
    items = 0
    total_bytes = 0
    if args.rank == 0:
        assert next_sock is not None
        for seq in range(args.items):
            if seq == 0:
                first_item = time.perf_counter()
            stage_work(stage_seconds)
            next_sock.sendall(HEADER.pack(seq, len(payload)))
            next_sock.sendall(payload)
            items += 1
            total_bytes += len(payload)
        next_sock.sendall(HEADER.pack(args.items, 0))
    else:
        assert prev_sock is not None
        while True:
            seq, length = HEADER.unpack(recv_exact(prev_sock, HEADER.size))
            if length == 0:
                if next_sock is not None:
                    next_sock.sendall(HEADER.pack(seq, 0))
                break
            if items == 0:
                first_item = time.perf_counter()
            remaining = length
            while remaining > 0:
                data = prev_sock.recv(min(4 * 1024 * 1024, remaining))
                if not data:
                    raise EOFError("payload socket closed")
                remaining -= len(data)
            stage_work(stage_seconds)
            if next_sock is not None:
                next_sock.sendall(HEADER.pack(seq, len(payload)))
                next_sock.sendall(payload)
            items += 1
            total_bytes += length
    ended = time.perf_counter()
    if prev_sock is not None:
        prev_sock.close()
    if next_sock is not None:
        next_sock.close()
    elapsed = ended - started
    active = ended - (first_item or started)
    result = {
        "role": "rank",
        "rank": args.rank,
        "world_size": args.world_size,
        "items": items,
        "payload_bytes": args.payload_bytes,
        "total_payload_bytes": total_bytes,
        "stage_ms": args.stage_ms,
        "elapsed_s": elapsed,
        "active_s": active,
        "items_per_s": items / active if active > 0 else 0.0,
        "payload_GBps": (total_bytes / active / 1_000_000_000.0) if active > 0 else 0.0,
    }
    print("PIPELINE_RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return 0


def run_sequential(args: argparse.Namespace) -> int:
    stage_seconds = args.stage_ms / 1000.0
    started = time.perf_counter()
    for _item in range(args.items):
        for _rank in range(args.world_size):
            stage_work(stage_seconds)
    elapsed = time.perf_counter() - started
    result = {
        "role": "sequential",
        "world_size": args.world_size,
        "items": args.items,
        "payload_bytes": args.payload_bytes,
        "stage_ms": args.stage_ms,
        "elapsed_s": elapsed,
        "items_per_s": args.items / elapsed if elapsed > 0 else 0.0,
    }
    print("PIPELINE_RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return 0


def rank_cmd(rank: int, world_size: int, args: argparse.Namespace, links: list[Link]) -> str:
    prefix = ["python3", REMOTE_SCRIPT] if args.worker == "python" else [REMOTE_C_BIN]
    parts = [
        *prefix,
        "--role",
        "rank",
        "--rank",
        str(rank),
        "--world-size",
        str(world_size),
        "--items",
        str(args.items),
        "--payload-bytes",
        str(args.payload_bytes),
        "--stage-ms",
        str(args.stage_ms),
        "--socket-buffer-mib",
        str(args.socket_buffer_mib),
    ]
    if rank > 0:
        prev = links[rank - 1]
        parts.extend(["--listen-bind", prev.dst_bind, "--listen-port", str(prev.port)])
    if rank < (world_size - 1):
        nxt = links[rank]
        parts.extend(["--next-bind", nxt.src_bind, "--next-host", nxt.dst_bind, "--next-port", str(nxt.port)])
    return " ".join(parts)


def parse_result(stdout: str) -> dict[str, Any] | None:
    for line in stdout.splitlines():
        if line.startswith("PIPELINE_RESULT "):
            return json.loads(line[len("PIPELINE_RESULT ") :])
    return None


def run_controller(args: argparse.Namespace) -> int:
    nodes, links = load_manifest(args.manifest)
    order = pipeline_order(links)
    world_size = len(order)
    if not args.no_deploy:
        deploy(nodes, order, args.worker)
    procs: list[tuple[int, str, subprocess.Popen[str]]] = []
    for rank in reversed(range(world_size)):
        node = nodes[order[rank]]
        remote_cmd = rank_cmd(rank, world_size, args, links)
        proc = subprocess.Popen(
            [*build_ssh_prefix(node.ssh, node.jump, COMMON_SSH_OPTS), remote_cmd],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        procs.append((rank, order[rank], proc))
        time.sleep(args.startup_sleep)
    results = []
    failed = False
    for rank, name, proc in procs:
        stdout, stderr = proc.communicate(timeout=max(60, int((args.items * args.stage_ms / 1000.0) + 120)))
        result = parse_result(stdout)
        if proc.returncode != 0 or result is None:
            failed = True
            print(f"rank {rank} {name} failed rc={proc.returncode}", file=sys.stderr)
            print(stderr.strip(), file=sys.stderr)
            print(stdout.strip(), file=sys.stderr)
        else:
            result["node"] = name
            results.append(result)
    seq_prefix = ["python3", REMOTE_SCRIPT] if args.worker == "python" else [REMOTE_C_BIN]
    sequential_cmd = [
        *build_ssh_prefix(nodes[order[0]].ssh, nodes[order[0]].jump, COMMON_SSH_OPTS),
        *seq_prefix,
        "--role",
        "sequential",
        "--world-size",
        str(world_size),
        "--items",
        str(args.items),
        "--payload-bytes",
        str(args.payload_bytes),
        "--stage-ms",
        str(args.stage_ms),
    ]
    seq_run = subprocess.run(
        sequential_cmd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(60, int((args.items * world_size * args.stage_ms / 1000.0) + 120)),
    )
    seq_result = parse_result(seq_run.stdout)
    sink = next((row for row in results if row["rank"] == (world_size - 1)), None)
    if sink is not None and seq_result is not None:
        speedup = sink["items_per_s"] / seq_result["items_per_s"] if seq_result["items_per_s"] > 0 else 0.0
        ideal = float(world_size)
        print(
            "PIPELINE_SUMMARY "
            + json.dumps(
                {
                    "world_size": world_size,
                    "items": args.items,
                    "payload_bytes": args.payload_bytes,
                    "stage_ms": args.stage_ms,
                    "pipeline_items_per_s": sink["items_per_s"],
                    "sequential_items_per_s": seq_result["items_per_s"],
                    "measured_speedup": speedup,
                    "ideal_speedup": ideal,
                    "speedup_efficiency": speedup / ideal if ideal > 0 else 0.0,
                    "sink_payload_GBps": sink["payload_GBps"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    output = {"rank_results": results, "sequential": seq_result}
    if args.json_out is not None:
        args.json_out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    return 1 if failed else 0


def main() -> int:
    args = parse_args()
    if args.role == "rank":
        return run_rank(args)
    if args.role == "sequential":
        return run_sequential(args)
    return run_controller(args)


if __name__ == "__main__":
    raise SystemExit(main())
