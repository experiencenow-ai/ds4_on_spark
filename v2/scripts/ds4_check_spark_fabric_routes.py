#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass


RAIL_DEVS = {
    "enp1s0f0np0",
    "enp1s0f1np1",
    "enP2p1s0f0np0",
    "enP2p1s0f1np1",
}


@dataclass(frozen=True)
class RouteSpec:
    source_rank: int
    target_rank: int
    target_ip: str
    via: str
    dev: str
    source_ip: str

    @property
    def label(self) -> str:
        return f"spark{self.source_rank}->spark{self.target_rank}"

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


def fabric_ip(rank: int) -> str:
    return f"10.10.100.{rank + 10}"


def line_next_hop(source_rank: int, target_rank: int) -> tuple[str, str]:
    if source_rank == target_rank:
        raise ValueError("self route does not need a next hop")
    if target_rank > source_rank:
        subnet = ((source_rank + 1) * 2)
        return (f"10.10.{subnet}.2", "enP2p1s0f1np1")
    subnet = (source_rank * 2)
    return (f"10.10.{subnet}.1", "enP2p1s0f0np0")


def build_specs(nodes: int, *, adjacent_only: bool, head_only: bool) -> list[RouteSpec]:
    specs: list[RouteSpec] = []
    for source_rank in range(nodes):
        for target_rank in range(nodes):
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
                    target_ip=fabric_ip(target_rank),
                    via=via,
                    dev=dev,
                    source_ip=fabric_ip(source_rank),
                )
            )
    return specs


def run_ssh(host: str, command: str, timeout_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", host, command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def route_get(spec: RouteSpec, timeout_s: int, *, strict_next_hop: bool) -> tuple[bool, str]:
    completed = run_ssh(
        f"spark{spec.source_rank}",
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
    dev_up = _dev_is_up(spec.source_rank, dev, timeout_s) if has_dev and dev is not None else False
    has_via = via is not None
    has_src = f" src {spec.source_ip} " in f" {first} "
    has_expected_next_hop = (dev == spec.dev and via == spec.via)
    bad_wifi = " dev wl" in first or " via 192.168." in first
    bad_linkdown = "linkdown" in first
    ok = has_dev and dev_up and has_via and has_src and not bad_wifi and not bad_linkdown
    if strict_next_hop:
        ok = ok and has_expected_next_hop
    return (ok, first)


def apply_specs(specs: list[RouteSpec], sudo: bool, timeout_s: int) -> int:
    failures = 0
    by_source: dict[int, list[RouteSpec]] = {}
    for spec in specs:
        by_source.setdefault(spec.source_rank, []).append(spec)
    for source_rank in sorted(by_source):
        commands = [spec.ip_cmd(sudo=sudo) for spec in by_source[source_rank]]
        remote_command = " && ".join(commands)
        completed = run_ssh(f"spark{source_rank}", remote_command, timeout_s)
        if completed.returncode != 0:
            failures += 1
            print(f"FAIL apply spark{source_rank}: {completed.stderr.strip() or completed.stdout.strip()}")
        else:
            print(f"PASS apply spark{source_rank}: {len(commands)} routes")
    return failures


def print_repairs(specs: list[RouteSpec], sudo: bool) -> None:
    by_source: dict[int, list[RouteSpec]] = {}
    for spec in specs:
        by_source.setdefault(spec.source_rank, []).append(spec)
    for source_rank in sorted(by_source):
        commands = [spec.ip_cmd(sudo=sudo) for spec in by_source[source_rank]]
        print(f"ssh spark{source_rank} {shlex.quote('; '.join(commands))}")


def _extract_field(route: str, field: str) -> str | None:
    parts = route.split()
    for i, part in enumerate(parts[:-1]):
        if part == field:
            return parts[i + 1]
    return None


def _dev_is_up(source_rank: int, dev: str | None, timeout_s: int) -> bool:
    if dev is None:
        return False
    completed = run_ssh(
        f"spark{source_rank}",
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or repair Spark 200G loopback host routes for the 0-7 line fabric.",
    )
    parser.add_argument("--nodes", type=int, default=8)
    parser.add_argument("--adjacent-only", action="store_true")
    parser.add_argument("--head-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-sudo", action="store_true")
    parser.add_argument("--strict-next-hop", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=8)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.nodes < 2:
        raise SystemExit("--nodes must be at least 2")
    specs = build_specs(
        args.nodes,
        adjacent_only=bool(args.adjacent_only),
        head_only=bool(args.head_only),
    )
    sudo = not bool(args.no_sudo)
    if args.apply:
        return apply_specs(specs, sudo=sudo, timeout_s=args.timeout_s)
    failures = check_specs(
        specs,
        sudo=sudo,
        timeout_s=args.timeout_s,
        strict_next_hop=bool(args.strict_next_hop),
    )
    if failures:
        print(f"fabric route check failed: {failures} failed probes")
        return 1
    print("fabric route check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
