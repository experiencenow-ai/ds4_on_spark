#!/usr/bin/env python3
"""Open an SSH byte stream over the best available Spark path."""

from __future__ import annotations

import argparse
import json
import os
import select
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


COPY_BYTES = 1024 * 1024
SSH_PREFACE_LIMIT = 8192
DEFAULT_TOPOLOGY = Path(__file__).resolve().parents[1] / "v2" / "profiles" / "transfer" / "spark_200g.json"


class RouteFailure(RuntimeError):
    pass


def node_rank(node_id: str) -> int:
    if not node_id.startswith("spark"):
        raise RouteFailure(f"invalid Spark node: {node_id}")
    try:
        rank = int(node_id[5:],16)
    except ValueError as error:
        raise RouteFailure(f"invalid Spark node: {node_id}") from error
    if rank < 0 or rank > 15:
        raise RouteFailure(f"Spark node is outside the 16-node fleet: {node_id}")
    return(rank)


def address_for(node_id: str,prefix: str) -> str:
    return(f"{prefix}.{10 + node_rank(node_id)}")


def load_topology(path: str) -> dict[str,dict[str,str]]:
    topology_path = Path(path).expanduser()
    with topology_path.open("r",encoding="utf-8") as handle:
        payload = json.load(handle)
    records = {}
    for item in payload.get("nodes",[]):
        node_id = str(item.get("node_id",""))
        if node_id == "":
            continue
        records[node_id] = {
            "fabric_host": str(item.get("fabric_host") or node_id),
            "fabric_ip": str(item.get("fabric_ip") or ""),
            "host": str(item.get("host") or node_id),
            "management_ip": str(item.get("management_ip") or ""),
        }
    if not records:
        raise RouteFailure(f"topology has no nodes: {topology_path}")
    return(records)


def node_addresses(node_id: str,records: dict[str,dict[str,str]]) -> dict[str,str]:
    record = records.get(node_id)
    if record is None:
        raise RouteFailure(f"node is absent from topology: {node_id}")
    if record["fabric_ip"] == "" or record["management_ip"] == "":
        raise RouteFailure(f"node has incomplete topology addresses: {node_id}")
    return(record)


def tailscale_address(node_id: str) -> str:
    try:
        result = subprocess.run(
            ["tailscale","status","--json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError):
        return("")
    candidates = [payload.get("Self",{})]
    peers = payload.get("Peer",{})
    if isinstance(peers,dict):
        candidates.extend(value for value in peers.values() if isinstance(value,dict))
    for candidate in candidates:
        hostname = str(candidate.get("HostName","")).lower()
        dns_name = str(candidate.get("DNSName","")).split(".",1)[0].lower()
        if node_id.lower() not in (hostname,dns_name):
            continue
        for address in candidate.get("TailscaleIPs",[]):
            if isinstance(address,str) and ":" not in address:
                return(address)
    return("")


def read_ssh_preface(sock: socket.socket,timeout_s: float) -> bytes:
    deadline = time.monotonic() + timeout_s
    data = bytearray()
    while len(data) < SSH_PREFACE_LIMIT:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        readable,_,_ = select.select([sock],[],[],remaining)
        if not readable:
            break
        chunk = sock.recv(min(1024,SSH_PREFACE_LIMIT - len(data)))
        if chunk == b"":
            break
        data.extend(chunk)
        if any(line.startswith(b"SSH-") for line in bytes(data).splitlines()):
            return(bytes(data))
    raise RouteFailure("endpoint did not provide an SSH banner")


def open_address(address: str,port: int,timeout_s: float) -> tuple[socket.socket,bytes]:
    sock = socket.create_connection((address,port),timeout=timeout_s)
    try:
        preface = read_ssh_preface(sock,timeout_s)
    except Exception:
        sock.close()
        raise
    sock.settimeout(None)
    return(sock,preface)


def route_candidates(node_id: str,route: str,records: dict[str,dict[str,str]]) -> list[tuple[str,str,float]]:
    record = node_addresses(node_id,records)
    candidates: list[tuple[str,str,float]] = []
    if route in ("auto","fabric"):
        candidates.append(("fabric",record["fabric_ip"],0.75))
    if route in ("auto","mgmt"):
        candidates.append(("mgmt",record["management_ip"],0.75))
    if route in ("auto","mgmt","tailscale"):
        address = tailscale_address(node_id)
        if address != "":
            candidates.append(("tailscale",address,3.0))
    return(candidates)


def open_route(node_id: str,route: str,port: int,records: dict[str,dict[str,str]]) -> tuple[str,str,socket.socket,bytes]:
    failures = []
    for label,address,timeout_s in route_candidates(node_id,route,records):
        try:
            sock,preface = open_address(address,port,timeout_s)
            return(label,address,sock,preface)
        except (OSError,RouteFailure) as error:
            failures.append(f"{label}={error}")
    raise RouteFailure("; ".join(failures) or f"no route candidates for {route}")


def write_all(fd: int,data: bytes) -> None:
    offset = 0
    while offset < len(data):
        offset += os.write(fd,data[offset:])


def copy_stdin(sock: socket.socket) -> None:
    try:
        while True:
            data = os.read(0,COPY_BYTES)
            if data == b"":
                break
            sock.sendall(data)
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass


def relay(sock: socket.socket,preface: bytes) -> int:
    write_all(1,preface)
    thread = threading.Thread(target=copy_stdin,args=(sock,),daemon=True)
    thread.start()
    try:
        while True:
            data = sock.recv(COPY_BYTES)
            if data == b"":
                break
            write_all(1,data)
    finally:
        sock.close()
    thread.join(timeout=1)
    return(0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node",required=True)
    parser.add_argument("--port",type=int,default=22)
    parser.add_argument("--route",choices=("auto","fabric","mgmt","tailscale"),default="auto")
    parser.add_argument(
        "--topology",
        default=os.environ.get("DS4_SPARK_FLEET_TOPOLOGY",str(DEFAULT_TOPOLOGY)),
    )
    parser.add_argument("--probe",action="store_true")
    return(parser.parse_args(argv))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.port < 1 or args.port > 65535:
            raise RouteFailure("port must be in 1..65535")
        records = load_topology(args.topology)
        label,address,sock,preface = open_route(args.node,args.route,args.port,records)
        if args.probe:
            print(json.dumps({"address":address,"node":args.node,"route":label},sort_keys=True))
            sock.close()
            return(0)
        return(relay(sock,preface))
    except RouteFailure as error:
        print(f"ds4_spark_fleet_proxy: {error}",file=sys.stderr)
        return(1)


if __name__ == "__main__":
    raise SystemExit(main())
