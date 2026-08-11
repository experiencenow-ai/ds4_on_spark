#!/usr/bin/env python3
"""Fail-closed readiness audit for the switched Spark fleet."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY = ROOT / "v2" / "profiles" / "transfer" / "spark_200g.json"
PROXY = ROOT / "scripts" / "ds4_spark_fleet_proxy.py"
FABRIC_DEVICES = (
    "enp1s0f0np0",
    "enp1s0f1np1",
    "enP2p1s0f0np0",
    "enP2p1s0f1np1",
)
REQUIRED_UNITS = (
    "ds4-switched-fabric.service",
    "centaur-sparkring-agent.service",
    "tailscaled.service",
)
WORKLOAD_PROCESSES = (
    "sparkpipe_model",
    "sparkpipe_glm52_cuda_residentd",
    "sparkpipe_gateway",
    "sparkpipe_glm52_gateway",
)
HASH_PATHS = (
    "/home/centaur-agent/src/centaur/centaur_sparkring_service.py",
    "/usr/local/sbin/ds4_spark_uplink.py",
    "/usr/local/sbin/ds4-switched-fabric-apply",
    "/etc/systemd/system/ds4-switched-fabric.service",
)


REMOTE_PROBE = r'''
import json
from pathlib import Path
import subprocess


FABRIC_DEVICES = %s
WORKLOAD_PROCESSES = %s
HASH_PATHS = %s
REQUIRED_UNITS = %s


def command(argv, timeout=8):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", str(error), 124
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def first_line(value):
    return value.splitlines()[0].strip() if value.splitlines() else ""


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def link_state(device):
    root = "/sys/class/net/" + device
    if not Path(root).exists():
        return None
    addresses, _, _ = command(["ip", "-o", "-4", "addr", "show", "dev", device])
    return {
        "device": device,
        "operstate": read_text(root + "/operstate"),
        "carrier": read_text(root + "/carrier"),
        "speed_mbps": read_text(root + "/speed"),
        "duplex": read_text(root + "/duplex"),
        "mtu": read_text(root + "/mtu"),
        "ipv4": [row.split()[3] for row in addresses.splitlines() if len(row.split()) > 3],
    }


def unit_state(unit):
    enabled, _, _ = command(["systemctl", "is-enabled", unit])
    active, _, _ = command(["systemctl", "is-active", unit])
    return {"enabled": enabled or "unavailable", "active": active or "unavailable"}


def process_ids(name):
    output, _, code = command(["pgrep", "-x", name])
    if code != 0:
        return []
    return [item for item in output.split() if item.isdigit()]


def file_hash(path):
    output, _, code = command(["sudo", "-n", "sha256sum", path])
    if code != 0 or output == "":
        return ""
    return output.split()[0]


def parse_tailscale():
    output, _, code = command(["tailscale", "status", "--json"])
    if code != 0:
        return {"state": "unavailable", "ip_present": False}
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"state": "invalid", "ip_present": False}
    addresses, _, address_code = command(["tailscale", "ip", "-4"])
    return {
        "state": str(payload.get("BackendState", "unknown")),
        "ip_present": address_code == 0 and any(item.strip() for item in addresses.splitlines()),
    }


def gpu_state():
    output, error, code = command([
        "nvidia-smi",
        "--query-gpu=name,driver_version",
        "--format=csv,noheader,nounits",
    ], timeout=12)
    apps, _, apps_code = command([
        "nvidia-smi",
        "--query-compute-apps=pid,process_name",
        "--format=csv,noheader,nounits",
    ], timeout=12)
    return {
        "query_ok": code == 0,
        "query_error": error if code != 0 else "",
        "rows": [row.strip() for row in output.splitlines() if row.strip()],
        "compute_apps": [row.strip() for row in apps.splitlines() if row.strip()] if apps_code == 0 else [],
    }


def recent_xid():
    output, _, code = command(["sudo", "-n", "dmesg", "--color=never"], timeout=8)
    if code != 0:
        return ""
    rows = [row.strip() for row in output.splitlines() if "NVRM: Xid" in row]
    return rows[-1] if rows else ""


def main():
    all_addresses, _, _ = command(["ip", "-o", "-4", "addr", "show"])
    extnvme_mounts = []
    try:
        home_entries = [item for item in Path("/home").iterdir() if item.is_dir()]
    except OSError:
        home_entries = []
    for home_entry in home_entries:
        mount_path = home_entry / "extnvme"
        if command(["findmnt", "-T", str(mount_path)])[2] == 0:
            extnvme_mounts.append(str(mount_path))
    failed_units = []
    failed_output = command(["systemctl","--failed","--no-legend"])[0]
    for row in failed_output.splitlines():
        fields = row.split()
        if not fields:
            continue
        failed_units.append(fields[1] if fields[0] == "●" and len(fields) > 1 else fields[0])
    result = {
        "hostname": first_line(command(["hostname", "-s"])[0]),
        "kernel": first_line(command(["uname", "-r"])[0]),
        "rank_file": read_text("/etc/ds4-node-rank"),
        "legacy_rank_file": read_text("/etc/ds4-ring-rank"),
        "all_ipv4": [row.split()[3] for row in all_addresses.splitlines() if len(row.split()) > 3],
        "fabric_links": [state for device in FABRIC_DEVICES if (state := link_state(device)) is not None],
        "units": {unit: unit_state(unit) for unit in REQUIRED_UNITS},
        "failed_units": failed_units,
        "tailscale": parse_tailscale(),
        "gpu": gpu_state(),
        "workload_processes": {name: process_ids(name) for name in WORKLOAD_PROCESSES},
        "hashes": {path: file_hash(path) for path in HASH_PATHS},
        "extnvme_mounted": bool(extnvme_mounts),
        "extnvme_mounts": extnvme_mounts,
        "recent_xid": recent_xid(),
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
''' % (
    repr(FABRIC_DEVICES),
    repr(WORKLOAD_PROCESSES),
    repr(HASH_PATHS),
    repr(REQUIRED_UNITS),
)


@dataclass(frozen=True)
class Node:
    node_id: str
    rank: int
    host: str
    fabric_host: str
    fabric_ip: str
    management_ip: str


def node_rank(node_id: str) -> int:
    if not node_id.startswith("spark"):
        raise ValueError(f"invalid Spark node name: {node_id}")
    return int(node_id[5:],16)


def load_nodes(path: str) -> tuple[Node,...]:
    topology_path = Path(path).expanduser()
    with topology_path.open("r",encoding="utf-8") as handle:
        payload = json.load(handle)
    nodes = []
    for item in payload.get("nodes",[]):
        node_id = str(item.get("node_id",""))
        if node_id == "":
            continue
        nodes.append(Node(
            node_id=node_id,
            rank=int(item.get("rank",node_rank(node_id))),
            host=str(item.get("host") or node_id),
            fabric_host=str(item.get("fabric_host") or node_id),
            fabric_ip=str(item.get("fabric_ip") or ""),
            management_ip=str(item.get("management_ip") or ""),
        ))
    if not nodes:
        raise ValueError(f"topology has no nodes: {topology_path}")
    return tuple(nodes)


def load_ssh_options(path: str) -> list[str]:
    with Path(path).expanduser().open("r",encoding="utf-8") as handle:
        payload = json.load(handle)
    return [str(item) for item in payload.get("ssh_options",[])]


def proxy_option(node: Node, route: str, topology: str) -> str:
    argv = [
        "python3",
        str(PROXY),
        "--node",
        node.node_id,
        "--port",
        "%p",
        "--route",
        route,
        "--topology",
        topology,
    ]
    return " ".join(shlex.quote(item) for item in argv)


def run_remote_payload(
    node: Node,
    route: str,
    topology: str,
    ssh_options: list[str],
    payload: str,
    timeout_s: int,
) -> tuple[str,bytes,str]:
    try:
        route_result = subprocess.run(
            [
                "python3",
                str(PROXY),
                "--node",
                node.node_id,
                "--port",
                "22",
                "--route",
                route,
                "--topology",
                topology,
                "--probe",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s + 4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return("unreachable",b"",str(error))
    if route_result.returncode != 0:
        detail = route_result.stderr.strip() or route_result.stdout.strip()
        return("unreachable",b"",detail or "route probe failed")
    try:
        selected_route = json.loads(route_result.stdout).get("route",route)
    except json.JSONDecodeError as error:
        return("unreachable",b"",f"invalid route probe JSON: {error}")
    options = list(ssh_options)
    options.extend([
        "-o",
        f"ConnectTimeout={timeout_s}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        f"ProxyCommand={proxy_option(node,route,topology)}",
    ])
    try:
        result = subprocess.run(
            ["ssh",*options,node.node_id,"python3","-"],
            input=payload.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s + 8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return("unreachable",b"",str(error))
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8",errors="replace").strip()
        return("unreachable",b"",detail or f"ssh exited {result.returncode}")
    return(selected_route,result.stdout,b"")


def probe_node(node: Node, route: str, topology: str, ssh_options: list[str], timeout_s: int) -> dict[str,object]:
    selected_route,stdout,error = run_remote_payload(
        node,route,topology,ssh_options,REMOTE_PROBE,timeout_s
    )
    if error:
        return {"probe_error": error,"route": "unreachable"}
    try:
        observed = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as error:
        return {"probe_error": f"invalid probe JSON: {error}","route": "unreachable"}
    observed["route"] = selected_route
    return observed


def evaluate_node(
    node: Node,
    observed: dict[str,object],
    *,
    require_fabric: bool,
    require_tailscale: bool,
    strict_hostname: bool,
    allow_workload: bool,
) -> tuple[list[str],list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    if observed.get("probe_error"):
        return ([f"probe={observed['probe_error']}"],warnings)
    if strict_hostname and observed.get("hostname") != node.node_id:
        failures.append(f"hostname={observed.get('hostname','')!r} expected={node.node_id!r}")
    if str(observed.get("rank_file") or "") != str(node.rank):
        failures.append(f"rank_file={observed.get('rank_file','')!r} expected={node.rank}")
    if observed.get("legacy_rank_file"):
        failures.append("legacy_ds4-ring-rank_present")
    all_ipv4 = [str(item) for item in observed.get("all_ipv4",[])]
    if not any(item.startswith(node.management_ip + "/") for item in all_ipv4):
        failures.append("management_ip_missing")
    links = [item for item in observed.get("fabric_links",[]) if isinstance(item,dict)]
    fabric_ip_present = any(
        any(str(address).startswith(node.fabric_ip + "/") for address in item.get("ipv4",[]))
        for item in links
    )
    if require_fabric and not fabric_ip_present:
        failures.append("fabric_ip_missing")
    qualified_links = [
        item for item in links
        if str(item.get("operstate")) == "up"
        and str(item.get("duplex")).lower() == "full"
        and str(item.get("speed_mbps")) == "100000"
    ]
    if require_fabric and not qualified_links:
        failures.append("no_100g_full_duplex_link")
    units = observed.get("units",{})
    for unit in REQUIRED_UNITS:
        state = units.get(unit,{}) if isinstance(units,dict) else {}
        if state.get("enabled") != "enabled" or state.get("active") != "active":
            failures.append(f"unit={unit}:{state.get('enabled','unavailable')}/{state.get('active','unavailable')}")
    tailscale = observed.get("tailscale",{})
    if require_tailscale and (
        tailscale.get("state") != "Running" or tailscale.get("ip_present") is not True
    ):
        failures.append(f"tailscale={tailscale.get('state','unavailable')}")
    workload = {
        name: pids
        for name,pids in (observed.get("workload_processes",{}) or {}).items()
        if pids
    }
    gpu = observed.get("gpu",{})
    compute_apps = gpu.get("compute_apps",[]) if isinstance(gpu,dict) else []
    if not allow_workload and workload:
        failures.append("stale_workload=" + ",".join(sorted(workload)))
    if not allow_workload and compute_apps:
        failures.append("gpu_compute_apps=" + str(len(compute_apps)))
    if observed.get("recent_xid"):
        warnings.append("NVRM_Xid_seen_current_dmesg")
    failed_units = observed.get("failed_units",[])
    if failed_units:
        warnings.append(f"systemd_failed_units={len(failed_units)}")
    if observed.get("extnvme_mounted") is False:
        warnings.append("extnvme_not_mounted")
    return(failures,warnings)


def public_observed(observed: dict[str,object]) -> dict[str,object]:
    gpu = observed.get("gpu",{})
    workload = observed.get("workload_processes",{})
    return {
        "hostname": observed.get("hostname",""),
        "kernel": observed.get("kernel",""),
        "rank_file": observed.get("rank_file",""),
        "legacy_rank_file": observed.get("legacy_rank_file",""),
        "route": observed.get("route",""),
        "fabric_links": observed.get("fabric_links",[]),
        "units": observed.get("units",{}),
        "failed_units": observed.get("failed_units",[]),
        "tailscale": observed.get("tailscale",{}),
        "gpu": {
            "query_ok": gpu.get("query_ok",False) if isinstance(gpu,dict) else False,
            "rows": gpu.get("rows",[]) if isinstance(gpu,dict) else [],
            "compute_app_count": len(gpu.get("compute_apps",[])) if isinstance(gpu,dict) else 0,
        },
        "workload_processes": sorted(name for name,pids in workload.items() if pids),
        "hashes": observed.get("hashes",{}),
        "extnvme_mounted": observed.get("extnvme_mounted",False),
        "xid_present": bool(observed.get("recent_xid")),
    }


def parse_nodes(raw: str, nodes: tuple[Node,...]) -> tuple[Node,...]:
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology",default=str(DEFAULT_TOPOLOGY))
    parser.add_argument("--nodes",default="",help="comma-separated node ids; default is the entire topology")
    parser.add_argument("--route",choices=("auto","fabric","mgmt","tailscale"),default="auto")
    parser.add_argument("--timeout-s",type=int,default=8)
    parser.add_argument("--json-output",default="")
    parser.add_argument("--allow-workload",action="store_true")
    parser.add_argument("--no-fabric-check",action="store_true")
    parser.add_argument("--no-tailscale-check",action="store_true")
    parser.add_argument("--strict-hostname",action="store_true")
    return parser.parse_args(argv)


def print_summary(results: list[dict[str,object]]) -> None:
    print("node    route       status  kernel                     link  tailscale  workload")
    print("------  ----------  ------  -------------------------  ----  ---------  --------")
    for result in results:
        observed = result["observed"]
        links = observed.get("fabric_links",[])
        qualified = sum(
            1 for item in links
            if item.get("operstate") == "up"
            and str(item.get("duplex")).lower() == "full"
            and str(item.get("speed_mbps")) == "100000"
        )
        status = result["status"]
        print(
            f"{result['node_id']:<6}  {str(observed.get('route','')):<10}  "
            f"{status:<6}  {str(observed.get('kernel','')):<25}  "
            f"{qualified:>4}  {str(observed.get('tailscale',{}).get('state','')):<9}  "
            f"{','.join(observed.get('workload_processes',[])) or '-'}"
        )
        for message in result["failures"]:
            print(f"  FAIL {result['node_id']}: {message}")
        for message in result["warnings"]:
            print(f"  WARN {result['node_id']}: {message}")


def fleet_consistency(results: list[dict[str,object]]) -> tuple[list[str],list[str],dict[str,list[str]]]:
    failures = []
    warnings = []
    hash_groups = {}
    for path in HASH_PATHS:
        groups = {}
        for result in results:
            value = str(result["observed"].get("hashes",{}).get(path,""))
            groups.setdefault(value,[]).append(result["node_id"])
        hash_groups[path] = sorted(value for value in groups if value != "")
        if "" in groups:
            warnings.append(f"hash_missing={path}:{','.join(groups[''])}")
        if len(hash_groups[path]) > 1:
            failures.append(f"hash_mismatch={path}")
    return(failures,warnings,hash_groups)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    topology = Path(args.topology).expanduser()
    nodes = parse_nodes(args.nodes,load_nodes(str(topology)))
    ssh_options = load_ssh_options(str(topology))
    with ThreadPoolExecutor(max_workers=max(1,len(nodes))) as pool:
        observed_rows = list(pool.map(
            lambda node: probe_node(node,args.route,str(topology),ssh_options,args.timeout_s),
            nodes,
        ))
    results = []
    for node,observed in zip(nodes,observed_rows):
        failures,warnings = evaluate_node(
            node,
            observed,
            require_fabric=not args.no_fabric_check,
            require_tailscale=not args.no_tailscale_check,
            strict_hostname=args.strict_hostname,
            allow_workload=args.allow_workload,
        )
        results.append({
            "node_id": node.node_id,
            "rank": node.rank,
            "status": "FAIL" if failures else "WARN" if warnings else "PASS",
            "failures": failures,
            "warnings": warnings,
            "observed": public_observed(observed),
        })
    fleet_failures,fleet_warnings,hash_groups = fleet_consistency(results)
    summary = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "route_policy": args.route,
        "node_count": len(results),
        "failed_nodes": sum(1 for item in results if item["status"] == "FAIL"),
        "warning_nodes": sum(1 for item in results if item["status"] == "WARN"),
        "fleet_failures": fleet_failures,
        "fleet_warnings": fleet_warnings,
        "common_hash_groups": hash_groups,
        "results": results,
    }
    print_summary(results)
    for message in fleet_failures:
        print(f"FAIL fleet: {message}")
    for message in fleet_warnings:
        print(f"WARN fleet: {message}")
    if args.json_output:
        output = Path(args.json_output).expanduser()
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(summary,indent=2,sort_keys=True) + "\n",encoding="utf-8")
        print(f"receipt={output}")
    return 1 if summary["failed_nodes"] or fleet_failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
