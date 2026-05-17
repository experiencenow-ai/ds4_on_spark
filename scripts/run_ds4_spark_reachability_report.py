#!/usr/bin/env python3
"""Build a DS4 Spark reachability report from local DNS/mDNS/ping/SSH checks."""

from __future__ import annotations

import argparse
import json
import platform
import re
import socket
import subprocess
import time
import ipaddress
from pathlib import Path
from typing import Any

try:
    from validate_ds4_spark_reachability_report import artifact_sha256
    from validate_ds4_spark_reachability_report import validate_report
except ModuleNotFoundError:
    from scripts.validate_ds4_spark_reachability_report import artifact_sha256
    from scripts.validate_ds4_spark_reachability_report import validate_report


FORMAT = "ds4-spark-reachability-report-v1"
DEFAULT_HOSTS = ("aitopatom-9ab9.local", "spark0.local", "spark1.local", "spark2.local")


def _run(command: list[str], timeout_s: float) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
        return {
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "elapsed_ms": round((time.time() - started) * 1000.0, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
            "elapsed_ms": round((time.time() - started) * 1000.0, 3),
            "timeout": True,
        }
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_ms": round((time.time() - started) * 1000.0, 3),
        }


def _status(result: dict[str, Any]) -> str:
    if result.get("timeout"):
        return "timeout"
    return "success" if result.get("returncode") == 0 else "failed"


def _host_only(target: str) -> str:
    return target.rsplit("@", 1)[-1]


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _user_for_target(target: str, default: str) -> str:
    return target.split("@", 1)[0] if "@" in target else default


def _read_inventory_targets(root: Path, default_user: str) -> dict[str, str]:
    targets = {host: f"{default_user}@{host}" for host in DEFAULT_HOSTS}
    manifest_dir = root / "fixtures" / "stage_handoff_manifests"
    for path in sorted(manifest_dir.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for stage in obj.get("stages", []):
            if not isinstance(stage, dict) or not isinstance(stage.get("host"), str):
                continue
            host_target = stage["host"]
            host = _host_only(host_target)
            user = _user_for_target(host_target, default_user)
            targets[host] = host_target
            if isinstance(stage.get("proxy"), str):
                targets[_host_only(stage["proxy"])] = stage["proxy"]
            if isinstance(stage.get("listen_ip"), str):
                targets[stage["listen_ip"]] = f"{user}@{stage['listen_ip']}"
    return targets


def _dns_result(host: str, timeout_s: float) -> dict[str, Any]:
    command = ["dscacheutil", "-q", "host", "-a", "name", host]
    result = _run(command, timeout_s)
    if result["returncode"] is None:
        status = _status(result)
    elif result["returncode"] == 0 and result["stdout"]:
        status = "success"
    else:
        status = "not_found"
    addresses = re.findall(r"ip(?:v6)?_?address:\s+(\S+)", result.get("stdout", ""))
    return {**result, "status": status, "addresses": addresses, "error": result.get("stderr") or ("" if addresses else "no host record returned")}


def _mdns_result(host: str, timeout_s: float) -> dict[str, Any]:
    result = _run(["dns-sd", "-G", "v4v6", host], timeout_s)
    status = "success" if result.get("returncode") == 0 and host in result.get("stdout", "") else _status(result)
    return {**result, "status": status, "error": result.get("stderr") or ("" if status == "success" else "mDNS lookup did not return a usable host record")}


def _ping_result(host: str, timeout_s: float) -> dict[str, Any]:
    result = _run(["ping", "-c", "1", "-W", "1000", host], timeout_s)
    status = "success" if result.get("returncode") == 0 else _status(result)
    return {**result, "status": status, "error": result.get("stderr") or ("" if status == "success" else result.get("stdout", ""))}


def _ssh_result(target: str, timeout_s: float) -> dict[str, Any]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={int(timeout_s)}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        target,
        "hostname",
    ]
    result = _run(command, timeout_s + 2.0)
    status = "success" if result.get("returncode") == 0 else _status(result)
    return {**result, "status": status, "target": target, "error": result.get("stderr") or ("" if status == "success" else result.get("stdout", ""))}


def _known_hosts_result(host: str) -> dict[str, Any]:
    result = _run(["ssh-keygen", "-F", host], 2.0)
    status = "present" if result.get("returncode") == 0 and result.get("stdout") else "missing"
    return {**result, "status": status, "error": result.get("stderr") or ""}


def _network_interfaces() -> dict[str, Any]:
    result = _run(["ifconfig"], 3.0)
    ps_result = _run(["ps", "-ax", "-o", "comm="], 3.0)
    scutil_result = _run(["scutil", "--dns"], 3.0)
    networksetup_result = _run(["networksetup", "-listallhardwareports"], 3.0)
    active = []
    current = ""
    for line in result.get("stdout", "").splitlines():
        if line and not line.startswith("\t") and not line.startswith(" "):
            current = line.split(":", 1)[0]
        if current and "status: active" in line:
            active.append(current)
    ps_stdout = ps_result.get("stdout", "")
    networksetup_error = networksetup_result.get("stderr") or networksetup_result.get("stdout", "")
    return {
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "active_interfaces": sorted(set(active)),
        "ifconfig_status": _status(result),
        "mdnsresponder_process_status": "observed" if "mDNSResponder" in ps_stdout else "not_observed",
        "process_check_status": _status(ps_result),
        "scutil_dns_status": _status(scutil_result),
        "scutil_dns_error": scutil_result.get("stderr") or scutil_result.get("stdout", ""),
        "networksetup_status": "failed" if "failed" in networksetup_error.lower() else _status(networksetup_result),
        "networksetup_error": networksetup_error,
        "error": result.get("stderr") or "",
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root)
    targets = _read_inventory_targets(root, args.ssh_user) if args.include_inventory else {host: f"{args.ssh_user}@{host}" for host in DEFAULT_HOSTS}
    for host in args.host:
        targets[_host_only(host)] = host if "@" in host else f"{args.ssh_user}@{host}"
    expected_hosts = sorted(host for host in targets if host)
    dns_results = {host: _dns_result(host, args.lookup_timeout_s) for host in expected_hosts}
    mdns_results = {host: _mdns_result(host, args.lookup_timeout_s) for host in expected_hosts}
    ping_results = {host: _ping_result(host, args.ping_timeout_s) for host in expected_hosts}
    ssh_results = {host: _ssh_result(targets[host], args.ssh_timeout_s) for host in expected_hosts}
    known_hosts_status = {host: _known_hosts_result(host) for host in expected_hosts}
    any_ssh = any(result.get("status") == "success" for result in ssh_results.values())
    hostname_hosts = [host for host in expected_hosts if not _is_ip_literal(host)]
    ip_literal_hosts = [host for host in expected_hosts if _is_ip_literal(host)]
    any_hostname_dns = any(dns_results[host].get("status") == "success" for host in hostname_hosts)
    any_hostname_mdns = any(mdns_results[host].get("status") == "success" for host in hostname_hosts)
    any_ip_literal = bool(ip_literal_hosts)
    if not expected_hosts:
        blocker_kind = "no_expected_hosts"
        blocker_detail = "No Spark hosts were supplied or discovered."
    elif any_ssh:
        blocker_kind = "none"
        blocker_detail = "At least one Spark host accepted SSH."
    elif any_hostname_dns or any_hostname_mdns:
        blocker_kind = "ssh_unreachable"
        blocker_detail = "Spark hostnames resolved but SSH did not reach any Spark host."
    elif any_ip_literal:
        blocker_kind = "ssh_unreachable"
        blocker_detail = "Spark hostnames did not resolve through DNS/mDNS; inventory direct IPs were checked but SSH did not reach any Spark host."
    else:
        blocker_kind = "spark_host_resolution_unreachable"
        blocker_detail = "No expected Spark host resolved through DNS/mDNS, and SSH did not reach any Spark host."
    report = {
        "format": FORMAT,
        "run_id": args.run_id or f"spark-reachability-{int(time.time())}",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_host": {"hostname": socket.gethostname(), "platform": platform.platform()},
        "expected_hosts": expected_hosts,
        "dns_results": dns_results,
        "mdns_results": mdns_results,
        "ping_results": ping_results,
        "ssh_results": ssh_results,
        "known_hosts_status": known_hosts_status,
        "network_interface_summary": _network_interfaces(),
        "blocker_kind": blocker_kind,
        "blocker_detail": blocker_detail,
        "recommended_fix": (
            "Restore local network/VPN/mDNS visibility to the Spark nodes or provide direct reachable Spark IPs; "
            "rerun this report before retrying SGLang acquisition."
            if blocker_kind != "none"
            else "Rerun SGLang acquisition against the reachable Spark host."
        ),
    }
    report["artifact_sha256"] = artifact_sha256(report)
    report["artifact_hash"] = report["artifact_sha256"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--host", action="append", default=[])
    parser.add_argument("--ssh-user", default="spark0")
    parser.add_argument("--no-include-inventory", dest="include_inventory", action="store_false", default=True)
    parser.add_argument("--lookup-timeout-s", type=float, default=3.0)
    parser.add_argument("--ping-timeout-s", type=float, default=3.0)
    parser.add_argument("--ssh-timeout-s", type=float, default=5.0)
    args = parser.parse_args()
    report = build_report(args)
    errors = validate_report(report)
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
