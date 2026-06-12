#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


RAIL_DEVS = {
    "enp1s0f0np0",
    "enp1s0f1np1",
    "enP2p1s0f0np0",
    "enP2p1s0f1np1",
}
CONTROL_IFACE = "ds4ring0"
DEFAULT_TOPOLOGY = Path(__file__).resolve().parents[1] / "profiles" / "transfer" / "spark_200g.json"
SSH_OPTIONS: list[str] = []


@dataclass(frozen=True)
class NodeInfo:
    rank: int
    node_id: str
    host: str
    fabric_ip: str


@dataclass(frozen=True)
class RouteSpec:
    source_rank: int
    target_rank: int
    target_ip: str
    via: str
    dev: str
    source_ip: str
    source_node: str = ""
    target_node: str = ""
    source_host: str = ""

    @property
    def label(self) -> str:
        source = self.source_node or f"spark{self.source_rank}"
        target = self.target_node or f"spark{self.target_rank}"
        return f"{source}->{target}"

    def ip_cmd(self, sudo: bool) -> str:
        argv = [
            "ip",
            "route",
            "replace",
            self.target_ip,
            "via",
            self.via,
            "dev",
            self.dev,
            "src",
            self.source_ip,
        ]
        if sudo:
            argv.insert(0, "sudo")
        return " ".join(shlex.quote(item) for item in argv)


@dataclass(frozen=True)
class ControlIfaceSpec:
    rank: int
    ip: str
    node_id: str = ""
    host: str = ""

    @property
    def label(self) -> str:
        return self.node_id or f"spark{self.rank}"

    def ip_cmds(self, sudo: bool, *, remove_loopback: bool) -> list[str]:
        prefix = ["sudo"] if sudo else []
        cmds = [
            _shell_cmd(prefix + ["ip", "link", "add", CONTROL_IFACE, "type", "dummy"]) + " 2>/dev/null || true",
            _shell_cmd(prefix + ["ip", "addr", "replace", f"{self.ip}/32", "dev", CONTROL_IFACE]),
            _shell_cmd(prefix + ["ip", "link", "set", CONTROL_IFACE, "up"]),
        ]
        if remove_loopback:
            cmds.insert(1, _shell_cmd(prefix + ["ip", "addr", "del", f"{self.ip}/32", "dev", "lo"]) + " 2>/dev/null || true")
        return cmds


def fabric_ip(rank: int) -> str:
    return f"10.10.100.{rank + 10}"


def fallback_nodes(count: int) -> list[NodeInfo]:
    return [
        NodeInfo(
            rank=rank,
            node_id=f"spark{rank}",
            host=f"spark{rank}",
            fabric_ip=fabric_ip(rank),
        )
        for rank in range(count)
    ]


def load_nodes(topology_path: str, count: int) -> list[NodeInfo]:
    path = Path(topology_path).expanduser()
    if str(path) == ".":
        path = DEFAULT_TOPOLOGY
    try:
        with path.open("r", encoding="utf-8") as handle:
            topology = json.load(handle)
        nodes = [
            NodeInfo(
                rank=rank,
                node_id=str(node["node_id"]),
                host=str(node.get("host") or node["node_id"]),
                fabric_ip=str(node.get("fabric_ip") or fabric_ip(rank)),
            )
            for rank, node in enumerate(topology.get("nodes", []))
            if "node_id" in node
        ]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        nodes = []
    if count > 0:
        nodes = nodes[:count]
    if nodes:
        return nodes
    return fallback_nodes(count if count > 0 else 8)


def load_ssh_options(topology_path: str) -> list[str]:
    path = Path(topology_path).expanduser()
    if str(path) == ".":
        path = DEFAULT_TOPOLOGY
    try:
        with path.open("r", encoding="utf-8") as handle:
            topology = json.load(handle)
        return [str(item) for item in topology.get("ssh_options", [])]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def line_next_hop(source_rank: int, target_rank: int) -> tuple[str, str]:
    if source_rank == target_rank:
        raise ValueError("self route does not need a next hop")
    if target_rank > source_rank:
        subnet = ((source_rank + 1) * 2)
        return (f"10.10.{subnet}.2", "enP2p1s0f1np1")
    subnet = (source_rank * 2)
    return (f"10.10.{subnet}.1", "enP2p1s0f0np0")


def build_specs(nodes: list[NodeInfo], *, adjacent_only: bool, head_only: bool) -> list[RouteSpec]:
    specs: list[RouteSpec] = []
    for source in nodes:
        for target in nodes:
            source_rank = source.rank
            target_rank = target.rank
            if source_rank == target_rank:
                continue
            if adjacent_only and abs(source_rank - target_rank) != 1:
                continue
            if head_only and source_rank != 0 and target_rank != 0:
                continue
            via, dev = line_next_hop(source_rank, target_rank)
            specs.append(
                RouteSpec(
                    source_rank=source_rank,
                    target_rank=target_rank,
                    target_ip=target.fabric_ip,
                    via=via,
                    dev=dev,
                    source_ip=source.fabric_ip,
                    source_node=source.node_id,
                    target_node=target.node_id,
                    source_host=source.host,
                )
            )
    return specs


def build_control_iface_specs(nodes: list[NodeInfo], ranks: list[int]) -> list[ControlIfaceSpec]:
    by_rank = {node.rank: node for node in nodes}
    specs: list[ControlIfaceSpec] = []
    for rank in ranks:
        node = by_rank[rank]
        specs.append(ControlIfaceSpec(rank=rank, ip=node.fabric_ip, node_id=node.node_id, host=node.host))
    return specs


def run_ssh(host: str, command: str, timeout_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", *SSH_OPTIONS, host, command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def route_get(spec: RouteSpec, timeout_s: int, *, strict_next_hop: bool) -> tuple[bool, str]:
    completed = run_ssh(
        spec.source_host or f"spark{spec.source_rank}",
        "ip route get " + shlex.quote(spec.target_ip),
        timeout_s,
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return (False, output)
    first = output.splitlines()[0] if output else ""
    dev = _extract_field(first, "dev")
    via = _extract_field(first, "via")
    has_dev = dev in RAIL_DEVS
    dev_up = _dev_is_up(spec.source_host or f"spark{spec.source_rank}", dev, timeout_s) if has_dev and dev is not None else False
    has_via = via is not None
    has_src = f" src {spec.source_ip} " in f" {first} "
    has_expected_next_hop = (dev == spec.dev and via == spec.via)
    bad_wifi = " dev wl" in first or " via 192.168." in first
    bad_linkdown = "linkdown" in first
    ok = has_dev and dev_up and has_via and has_src and not bad_wifi and not bad_linkdown
    if strict_next_hop:
        ok = ok and has_expected_next_hop
    return (ok, first)


def control_iface_get(spec: ControlIfaceSpec, timeout_s: int) -> tuple[bool, str]:
    completed = run_ssh(
        spec.host or f"spark{spec.rank}",
        f"ip -o -4 addr show dev {CONTROL_IFACE} && ip -d link show {CONTROL_IFACE}",
        timeout_s,
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return (False, output)
    has_ip = f" inet {spec.ip}/32 " in f" {output} "
    has_dummy = " dummy " in f" {output} "
    has_up = "<" in output and "UP" in output.split(">", 1)[0]
    return (has_ip and has_dummy and has_up, output.splitlines()[0] if output else "")


def apply_specs(specs: list[RouteSpec], sudo: bool, timeout_s: int) -> int:
    failures = 0
    by_source: dict[int, list[RouteSpec]] = {}
    for spec in specs:
        by_source.setdefault(spec.source_rank, []).append(spec)
    for source_rank in sorted(by_source):
        commands = [spec.ip_cmd(sudo=sudo) for spec in by_source[source_rank]]
        remote_command = " && ".join(commands)
        host = by_source[source_rank][0].source_host or f"spark{source_rank}"
        label = by_source[source_rank][0].source_node or f"spark{source_rank}"
        completed = run_ssh(host, remote_command, timeout_s)
        if completed.returncode != 0:
            failures += 1
            print(f"FAIL apply {label}: {completed.stderr.strip() or completed.stdout.strip()}")
        else:
            print(f"PASS apply {label}: {len(commands)} routes")
    return failures


def apply_control_iface_specs(specs: list[ControlIfaceSpec], sudo: bool, timeout_s: int, *, remove_loopback: bool) -> int:
    failures = 0
    for spec in specs:
        remote_command = " && ".join(spec.ip_cmds(sudo=sudo, remove_loopback=remove_loopback))
        completed = run_ssh(spec.host or f"spark{spec.rank}", remote_command, timeout_s)
        if completed.returncode != 0:
            failures += 1
            print(f"FAIL apply {spec.label} {CONTROL_IFACE}: {completed.stderr.strip() or completed.stdout.strip()}")
        else:
            print(f"PASS apply {spec.label} {CONTROL_IFACE}: {spec.ip}/32")
    return failures


def print_repairs(specs: list[RouteSpec], sudo: bool) -> None:
    by_source: dict[int, list[RouteSpec]] = {}
    for spec in specs:
        by_source.setdefault(spec.source_rank, []).append(spec)
    for source_rank in sorted(by_source):
        commands = [spec.ip_cmd(sudo=sudo) for spec in by_source[source_rank]]
        host = by_source[source_rank][0].source_host or f"spark{source_rank}"
        print(f"ssh {shlex.quote(host)} {shlex.quote('; '.join(commands))}")


def print_control_iface_repairs(specs: list[ControlIfaceSpec], sudo: bool, *, remove_loopback: bool) -> None:
    for spec in specs:
        commands = spec.ip_cmds(sudo=sudo, remove_loopback=remove_loopback)
        print(f"ssh {shlex.quote(spec.host or f'spark{spec.rank}')} {shlex.quote('; '.join(commands))}")


def _extract_field(route: str, field: str) -> str | None:
    parts = route.split()
    for i, part in enumerate(parts[:-1]):
        if part == field:
            return parts[i + 1]
    return None


def _shell_cmd(argv: list[str]) -> str:
    return " ".join(shlex.quote(item) for item in argv)


def _parse_rank_filter(raw: str | None, nodes: int | list[NodeInfo]) -> list[int]:
    if isinstance(nodes, int):
        node_count = nodes
        node_ranks = {f"spark{rank}": rank for rank in range(nodes)}
    else:
        node_count = len(nodes)
        node_ranks = {node.node_id: node.rank for node in nodes}
    if raw is None or raw.strip() == "":
        return list(range(node_count))
    ranks: list[int] = []
    for item in raw.split(","):
        value = item.strip()
        if value in node_ranks:
            rank = node_ranks[value]
        elif value.startswith("spark"):
            value = value[5:]
            rank = int(value)
        else:
            rank = int(value)
        if rank < 0 or rank >= node_count:
            raise ValueError(f"rank {rank} outside 0..{node_count - 1}")
        if rank not in ranks:
            ranks.append(rank)
    return ranks


def _dev_is_up(host: str, dev: str | None, timeout_s: int) -> bool:
    if dev is None:
        return False
    completed = run_ssh(
        host,
        "cat " + shlex.quote(f"/sys/class/net/{dev}/operstate"),
        timeout_s,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "up"


def check_specs(specs: list[RouteSpec], sudo: bool, timeout_s: int, *, strict_next_hop: bool) -> int:
    failures: list[RouteSpec] = []
    for spec in specs:
        ok, route = route_get(spec, timeout_s, strict_next_hop=strict_next_hop)
        status = "PASS" if ok else "FAIL"
        print(f"{status} {spec.label:<15} {spec.target_ip:<13} :: {route}")
        if not ok:
            failures.append(spec)
    if failures:
        print("")
        print("repair commands:")
        print_repairs(failures, sudo=sudo)
    return len(failures)


def check_control_iface_specs(specs: list[ControlIfaceSpec], sudo: bool, timeout_s: int, *, remove_loopback: bool) -> int:
    failures: list[ControlIfaceSpec] = []
    for spec in specs:
        ok, state = control_iface_get(spec, timeout_s)
        status = "PASS" if ok else "FAIL"
        print(f"{status} {spec.label:<7} {CONTROL_IFACE:<9} {spec.ip:<13} :: {state}")
        if not ok:
            failures.append(spec)
    if failures:
        print("")
        print("control interface repair commands:")
        print_control_iface_repairs(failures, sudo=sudo, remove_loopback=remove_loopback)
    return len(failures)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or repair Spark 200G loopback host routes for the canonical Spark fleet.",
    )
    parser.add_argument("--topology", default=os.environ.get("DS4_SPARK_FLEET_TOPOLOGY", str(DEFAULT_TOPOLOGY)))
    parser.add_argument("--nodes", type=int, default=0, help="Optional number of topology nodes to check; defaults to all nodes in the topology.")
    parser.add_argument("--ssh-option", action="append", default=[], help="Extra ssh option, for example '-o UserKnownHostsFile=/tmp/kh'.")
    parser.add_argument("--ssh-known-hosts", default="", help="Known-hosts file to use with StrictHostKeyChecking=accept-new.")
    parser.add_argument("--only-ranks", default="", help="Comma-separated source ranks or spark names, for example 4,6 or spark4,spark6.")
    parser.add_argument("--adjacent-only", action="store_true")
    parser.add_argument("--head-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check-control-iface", action="store_true")
    parser.add_argument("--apply-control-iface", action="store_true")
    parser.add_argument("--control-only", action="store_true")
    parser.add_argument("--remove-loopback-control-ip", action="store_true")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--strict-next-hop", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=8)
    return parser.parse_args(argv)


def selected_route_specs(args: argparse.Namespace, nodes: list[NodeInfo], source_ranks: list[int]) -> list[RouteSpec]:
    specs = build_specs(
        nodes,
        adjacent_only=bool(args.adjacent_only),
        head_only=bool(args.head_only),
    )
    return [spec for spec in specs if spec.source_rank in source_ranks]


def handle_control_iface(args: argparse.Namespace, iface_specs: list[ControlIfaceSpec], sudo: bool) -> int:
    failures = 0
    if args.apply_control_iface:
        failures += apply_control_iface_specs(
            iface_specs,
            sudo=sudo,
            timeout_s=args.timeout_s,
            remove_loopback=bool(args.remove_loopback_control_ip),
        )
        failures += check_control_iface_specs(
            iface_specs,
            sudo=sudo,
            timeout_s=args.timeout_s,
            remove_loopback=bool(args.remove_loopback_control_ip),
        )
    elif args.check_control_iface or args.control_only:
        failures += check_control_iface_specs(
            iface_specs,
            sudo=sudo,
            timeout_s=args.timeout_s,
            remove_loopback=bool(args.remove_loopback_control_ip),
        )
    return failures


def handle_routes(args: argparse.Namespace, specs: list[RouteSpec], sudo: bool) -> int:
    if args.control_only:
        return 0
    if args.apply:
        return apply_specs(specs, sudo=sudo, timeout_s=args.timeout_s)
    return check_specs(
        specs,
        sudo=sudo,
        timeout_s=args.timeout_s,
        strict_next_hop=bool(args.strict_next_hop),
    )


def main(argv: list[str]) -> int:
    global SSH_OPTIONS
    args = parse_args(argv)
    nodes = load_nodes(args.topology, args.nodes)
    SSH_OPTIONS = load_ssh_options(args.topology) + list(args.ssh_option)
    if args.ssh_known_hosts:
        SSH_OPTIONS.extend(["-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={args.ssh_known_hosts}"])
    if len(nodes) < 2:
        raise SystemExit("need at least 2 nodes")
    try:
        source_ranks = _parse_rank_filter(args.only_ranks, nodes)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    sudo = not bool(args.no_sudo)
    specs = selected_route_specs(args, nodes, source_ranks)
    iface_specs = build_control_iface_specs(nodes, source_ranks)
    failures = handle_control_iface(args, iface_specs, sudo)
    if args.control_only:
        if failures:
            print(f"control interface check failed: {failures} failed probes")
            return 1
        print("control interface check passed")
        return 0
    failures += handle_routes(args, specs, sudo)
    if failures:
        print(f"fabric route check failed: {failures} failed probes")
        return 1
    print("fabric route check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
