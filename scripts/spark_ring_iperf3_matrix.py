#!/usr/bin/env python3
"""Run reproducible iperf3 tests across Spark high-speed links.

The older SSH/dd bandwidth probe is useful for Mac reachability, but it tests
the Mac-side path. This runner binds iperf3 clients and servers to the
inter-Spark addresses so the 100/200G links are measured directly.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    "edges": [
        {
            "name": "spark0_to_spark1_10_10_1",
            "src": "spark0",
            "dst": "spark1",
            "src_bind": "10.10.1.1",
            "dst_bind": "10.10.1.252",
            "port": 5201,
        },
        {
            "name": "spark0_to_spark2_10_10_2",
            "src": "spark0",
            "dst": "spark2",
            "src_bind": "10.10.2.1",
            "dst_bind": "10.10.2.2",
            "port": 5202,
        },
        {
            "name": "spark1_to_spark2_10_10_5",
            "src": "spark1",
            "dst": "spark2",
            "src_bind": "10.10.5.1",
            "dst_bind": "10.10.5.2",
            "port": 5205,
        },
        {
            "name": "spark1_to_spark2_10_10_6",
            "src": "spark1",
            "dst": "spark2",
            "src_bind": "10.10.6.1",
            "dst_bind": "10.10.6.2",
            "port": 5206,
        },
    ],
}


@dataclass(frozen=True)
class Node:
    name: str
    ssh: str
    jump: str | None


@dataclass(frozen=True)
class Edge:
    name: str
    src: str
    dst: str
    src_bind: str
    dst_bind: str
    port: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run bound iperf3 tests over Spark interconnect links."
    )
    parser.add_argument("--manifest", type=Path, help="JSON manifest override")
    parser.add_argument("--seconds", type=int, default=8)
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--edge", action="append", default=[], help="Edge name to run")
    parser.add_argument("--reverse", action="store_true", help="Run iperf3 reverse mode")
    parser.add_argument("--bidir", action="store_true", help="Run iperf3 bidirectional mode")
    parser.add_argument("--zerocopy", action="store_true", help="Use iperf3 zero-copy send path")
    parser.add_argument("--json-out", type=Path, help="Write machine-readable results")
    parser.add_argument("--server-wait", type=float, default=1.0)
    return parser.parse_args()


def load_manifest(path: Path | None) -> tuple[dict[str, Node], list[Edge]]:
    raw = DEFAULT_MANIFEST if path is None else json.loads(path.read_text())
    nodes = {
        item["name"]: Node(
            name=item["name"],
            ssh=item["ssh"],
            jump=item.get("jump"),
        )
        for item in raw["nodes"]
    }
    edges = [
        Edge(
            name=item["name"],
            src=item["src"],
            dst=item["dst"],
            src_bind=item["src_bind"],
            dst_bind=item["dst_bind"],
            port=int(item["port"]),
        )
        for item in raw["edges"]
    ]
    return nodes, edges


def ssh_prefix(node: Node) -> list[str]:
    cmd = ["ssh", *COMMON_SSH_OPTS]
    if node.jump is not None:
        cmd.extend(["-J", node.jump])
    cmd.append(node.ssh)
    return cmd


def run_remote(node: Node, remote_cmd: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ssh_prefix(node), remote_cmd],
        check=False,
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def start_server(node: Node, edge: Edge) -> None:
    log = f"/tmp/ds4_iperf3_{edge.name}_{edge.port}.log"
    remote = (
        "set -eu; "
        f"nohup iperf3 -s -1 -B {edge.dst_bind} -p {edge.port} >{log} 2>&1 &"
    )
    result = run_remote(node, remote, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(
            f"server start failed for {node.name}: stdout={result.stdout.strip()} stderr={result.stderr.strip()}"
        )


def parse_iperf_json(stdout: str) -> dict[str, Any]:
    data = json.loads(stdout)
    end = data.get("end", {})
    if "sum_sent" in end:
        sent = end["sum_sent"]
    elif "sum" in end:
        sent = end["sum"]
    else:
        sent = {}
    recv = end.get("sum_received", {})
    return {
        "bits_per_second_sent": float(sent.get("bits_per_second", 0.0)),
        "bits_per_second_received": float(recv.get("bits_per_second", 0.0)),
        "retransmits": int(sent.get("retransmits", 0) or 0),
        "seconds": float(sent.get("seconds", 0.0) or recv.get("seconds", 0.0) or 0.0),
        "raw": data,
    }


def run_client(nodes: dict[str, Node], edge: Edge, args: argparse.Namespace) -> dict[str, Any]:
    src = nodes[edge.src]
    cmd = [
        "iperf3",
        "-J",
        "-c",
        edge.dst_bind,
        "-B",
        edge.src_bind,
        "-p",
        str(edge.port),
        "-P",
        str(args.parallel),
        "-t",
        str(args.seconds),
    ]
    if args.reverse:
        cmd.append("-R")
    if args.bidir:
        cmd.append("--bidir")
    if args.zerocopy:
        cmd.append("-Z")
    result = run_remote(src, " ".join(cmd), timeout=(args.seconds + 45))
    if result.returncode != 0:
        raise RuntimeError(
            f"client failed for {edge.name}: {result.stderr.strip()}\n{result.stdout}"
        )
    metrics = parse_iperf_json(result.stdout)
    metrics.pop("raw", None)
    return metrics


def gbps(bits_per_second: float) -> float:
    return bits_per_second / 1_000_000_000.0


def main() -> int:
    args = parse_args()
    nodes, edges = load_manifest(args.manifest)
    selected = set(args.edge)
    results = []
    for edge in edges:
        if selected and edge.name not in selected:
            continue
        start_server(nodes[edge.dst], edge)
        time.sleep(args.server_wait)
        started = time.time()
        try:
            metrics = run_client(nodes, edge, args)
            status = "ok"
            error = ""
        except Exception as exc:  # noqa: BLE001
            metrics = {
                "bits_per_second_sent": 0.0,
                "bits_per_second_received": 0.0,
                "retransmits": 0,
                "seconds": 0.0,
            }
            status = "failed"
            error = str(exc)
        elapsed = time.time() - started
        row = {
            "edge": edge.name,
            "src": edge.src,
            "dst": edge.dst,
            "src_bind": edge.src_bind,
            "dst_bind": edge.dst_bind,
            "port": edge.port,
            "parallel_streams": args.parallel,
            "target_seconds": args.seconds,
            "wall_seconds": elapsed,
            "status": status,
            "error": error,
            **metrics,
        }
        results.append(row)
        print(
            f"{edge.name}: status={status} sent={gbps(row['bits_per_second_sent']):.2f}Gbps "
            f"recv={gbps(row['bits_per_second_received']):.2f}Gbps "
            f"retrans={row['retransmits']} wall={elapsed:.2f}s"
        )
        if error:
            print(error, file=sys.stderr)
    if args.json_out is not None:
        args.json_out.write_text(json.dumps({"results": results}, indent=2) + "\n")
    return 0 if all(row["status"] == "ok" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
