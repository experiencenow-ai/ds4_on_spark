#!/usr/bin/env python3
"""Converge the declared shared Spark package baseline without changing cohorts."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "scripts" / "ds4_spark_fleet_preflight.py"
spec = importlib.util.spec_from_file_location("ds4_spark_fleet_preflight", PREFLIGHT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load fleet transport: {PREFLIGHT_PATH}")
preflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


DEFAULT_TOPOLOGY = ROOT / "v2" / "profiles" / "transfer" / "spark_200g.json"
PROTECTED_PREFIXES = (
    "cuda",
    "ceph",
    "librados",
    "librbd",
    "libceph",
    "libcublas",
    "libcufft",
    "libcufile",
    "libcurand",
    "libcusolver",
    "libcusparse",
    "libnpp",
    "libnv",
    "gds-tools",
    "mlnx",
    "mstflint",
    "perftest",
    "srptools",
    "nv-",
    "podman",
    "containerd",
    "docker",
    "buildah",
    "conmon",
    "netavark",
    "aardvark",
    "dgx",
    "dell-dgx",
    "firmware",
    "gigabyte",
    "ibverbs",
    "libib",
    "libnvidia",
    "librdmacm",
    "linux",
    "mlx",
    "nvidia",
    "openmpi",
    "rdma",
    "tailscale",
    "ucx",
    "ubuntu-drivers",
    "xserver-xorg-video-nvidia",
)
REMOTE_PACKAGES = r'''
import json
import subprocess


def command(argv, timeout=30):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", str(error), 124
    return result.stdout.strip(), result.stderr.strip(), result.returncode


output, error, code = command([
    "dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n",
])
packages = {}
if code == 0:
    for row in output.splitlines():
        fields = row.split("\t", 1)
        if len(fields) == 2:
            packages[fields[0]] = fields[1]
manual_output, manual_error, manual_code = command(["apt-mark", "showmanual"])
manual_packages = []
if manual_code == 0:
    manual_packages = sorted(
        package for package in manual_output.splitlines() if package.strip()
    )
print(json.dumps({
    "packages": packages,
    "manual_packages": manual_packages,
    "error": error if code != 0 else "",
    "manual_error": manual_error if manual_code != 0 else "",
}))
'''


def load_transport(topology: str) -> tuple[tuple[Any, ...], list[str]]:
    nodes = preflight.load_nodes(topology)
    options = preflight.load_ssh_options(topology)
    return nodes, options


def parse_nodes(raw: str, nodes: tuple[Any, ...]) -> tuple[Any, ...]:
    if raw.strip() == "":
        return nodes
    by_name = {node.node_id: node for node in nodes}
    selected = []
    for value in raw.split(","):
        name = value.strip()
        if name == "":
            continue
        if name not in by_name:
            raise ValueError(f"node is absent from topology: {name}")
        selected.append(by_name[name])
    return tuple(selected)


def query_node(node: Any, route: str, topology: str, options: list[str]) -> dict[str, Any]:
    selected_route, stdout, error = preflight.run_remote_payload(
        node, route, topology, options, REMOTE_PACKAGES, 20
    )
    if error:
        raise RuntimeError(f"{node.node_id}: package query failed: {error}")
    try:
        result = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{node.node_id}: invalid package query: {error}") from error
    result["route"] = selected_route
    result["node"] = node.node_id
    return result


def is_protected(package: str) -> bool:
    name = package.split(":", 1)[0]
    return name.startswith(PROTECTED_PREFIXES)


def shared_plan(reference: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    base = reference["packages"]
    current = observed["packages"]
    managed_names = {
        name for name in reference.get("manual_packages", []) if not is_protected(name)
    }
    managed = {name: base[name] for name in managed_names if name in base}
    return {
        "managed": sorted(managed),
        "missing": sorted(name for name in managed if name not in current),
        "version_drift": sorted(
            name for name in managed if name in current and current[name] != managed[name]
        ),
        "protected_drift": sorted(
            name for name in set(base) & set(current) if is_protected(name) and base[name] != current[name]
        ),
    }


def apply_node(
    node: Any,
    route: str,
    topology: str,
    options: list[str],
    packages: list[str],
) -> dict[str, Any]:
    remote = f'''
import json
import subprocess

PACKAGES = {packages!r}


def command(argv, timeout=180):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", str(error), 124
    return result.stdout.strip(), result.stderr.strip(), result.returncode


before_kernel, _, _ = command(["uname", "-r"])
before_driver, _, _ = command([
    "nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader,nounits",
])
audit_before, audit_before_error, audit_before_code = command(["sudo", "-n", "dpkg", "--audit"])
if audit_before_code != 0 or audit_before or audit_before_error:
    print(json.dumps({{"ok": False, "step": "dpkg-audit-before", "error": audit_before_error or audit_before}}))
    raise SystemExit(0)
lock_check, lock_error, lock_code = command([
    "sudo", "-n", "fuser", "-s", "/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock",
])
if lock_code == 0:
    print(json.dumps({{"ok": False, "step": "package-lock", "error": lock_error or lock_check}}))
    raise SystemExit(0)
if not PACKAGES:
    print(json.dumps({{
        "ok": True,
        "step": "already-aligned",
        "package_count": 0,
        "kernel_before": before_kernel,
        "kernel_after": before_kernel,
        "driver_before": before_driver,
        "driver_after": before_driver,
    }}))
    raise SystemExit(0)
install_out, install_error, install_code = command([
    "sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive",
    "apt-get", "install", "-y", "--no-install-recommends", "--no-remove",
    "-o", "DPkg::Lock::Timeout=60", "--", *PACKAGES,
], 900)
after_kernel, _, _ = command(["uname", "-r"])
after_driver, _, _ = command([
    "nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader,nounits",
])
audit_out, audit_error, audit_code = command(["sudo", "-n", "dpkg", "--audit"])
print(json.dumps({{
    "ok": install_code == 0 and audit_code == 0,
    "install_code": install_code,
    "install_error": install_error if install_code != 0 else "",
    "dpkg_audit": audit_error or audit_out,
    "kernel_before": before_kernel,
    "kernel_after": after_kernel,
    "driver_before": before_driver,
    "driver_after": after_driver,
}}))
'''
    selected_route, stdout, error = preflight.run_remote_payload(
        node, route, topology, options, remote, 960
    )
    if error:
        raise RuntimeError(f"{node.node_id}: package apply failed: {error}")
    try:
        result = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{node.node_id}: invalid package apply result: {error}") from error
    result["node"] = node.node_id
    result["route"] = selected_route
    result["package_count"] = len(packages)
    if result.get("kernel_before") != result.get("kernel_after"):
        raise RuntimeError(f"{node.node_id}: package operation changed the running kernel")
    if result.get("driver_before") != result.get("driver_after"):
        raise RuntimeError(f"{node.node_id}: package operation changed the GPU driver")
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", default=str(DEFAULT_TOPOLOGY))
    parser.add_argument("--reference-node", default="spark0")
    parser.add_argument("--nodes", default="")
    parser.add_argument("--route", choices=("mgmt", "fabric"), default="mgmt")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wave-size", type=int, default=4)
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    nodes, options = load_transport(args.topology)
    nodes = parse_nodes(args.nodes, nodes)
    by_name = {node.node_id: node for node in nodes}
    all_nodes, _ = load_transport(args.topology)
    reference = next(node for node in all_nodes if node.node_id == args.reference_node)
    query_nodes = tuple({node.node_id: node for node in (reference, *nodes)}.values())
    observed: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(query_nodes))) as pool:
        futures = {
            pool.submit(query_node, node, args.route, str(args.topology), options): node
            for node in query_nodes
        }
        for future in as_completed(futures):
            result = future.result()
            observed[result["node"]] = result
    reference_observed = observed[args.reference_node]
    managed = sorted(
        name
        for name in reference_observed.get("manual_packages", [])
        if not is_protected(name) and name in reference_observed["packages"]
    )
    plans = {node: shared_plan(reference_observed, observed[node]) for node in sorted(observed)}
    result: dict[str, Any] = {
        "apply": args.apply,
        "reference_node": args.reference_node,
        "managed_package_count": len(managed),
        "protected_prefixes": PROTECTED_PREFIXES,
        "plans": plans,
    }
    if args.apply:
        apply_nodes = tuple(node for node in nodes if node.node_id != args.reference_node)
        receipts = []
        for offset in range(0, len(apply_nodes), max(1, args.wave_size)):
            wave = apply_nodes[offset:offset + max(1, args.wave_size)]
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                futures = {
                    pool.submit(
                        apply_node,
                        node,
                        args.route,
                        str(args.topology),
                        options,
                        plans[node.node_id]["missing"],
                    ): node
                    for node in wave
                }
                for future in as_completed(futures):
                    try:
                        receipts.append(future.result())
                    except Exception as error:
                        if not args.continue_on_error:
                            raise
                        receipts.append({"node": futures[future].node_id, "error": str(error)})
        result["receipts"] = sorted(receipts, key=lambda item: item["node"])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
