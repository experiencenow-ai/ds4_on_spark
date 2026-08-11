#!/usr/bin/env python3
"""Install, reboot, and verify the 16-node switched Spark fabric."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
APPLY_SCRIPT = ROOT / "scripts" / "ds4_switched_fabric_apply.sh"
DEFAULT_NODES = tuple(f"spark{rank:x}" for rank in range(16))


class FleetError(RuntimeError):
    pass


def run(argv: list[str],input_bytes: bytes | None = None,timeout: int = 60,check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(argv,input=input_bytes,capture_output=True,timeout=timeout)
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8",errors="replace").strip()
        raise FleetError(f"command failed ({result.returncode}): {' '.join(argv)}: {detail}")
    return(result)


def ssh(node: str,*argv: str,input_bytes: bytes | None = None,timeout: int = 60,check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return(run(["ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=5",node,*argv],input_bytes,timeout,check))


def text(result: subprocess.CompletedProcess[bytes]) -> str:
    return(result.stdout.decode("utf-8",errors="replace").strip())


def rank(node: str) -> int:
    if not node.startswith("spark"):
        raise FleetError(f"invalid Spark node: {node}")
    value = int(node[5:],16)
    if value < 0 or value > 15:
        raise FleetError(f"Spark rank outside 0..15: {node}")
    return(value)


def install(node: str,payload: bytes,expected_sha256: str) -> dict[str,object]:
    temporary = "/tmp/ds4-switched-fabric-apply"
    rank_temporary = "/tmp/ds4-node-rank"
    rank_payload = f"{rank(node)}\n".encode()
    ssh(node,"tee",rank_temporary,input_bytes=rank_payload)
    try:
        ssh(node,"sudo","-n","install","-m","0644","-o","root","-g","root",rank_temporary,"/etc/ds4-node-rank")
        ssh(node,"sudo","-n","rm","-f","/etc/ds4-ring-rank")
    finally:
        ssh(node,"rm","-f",rank_temporary,check=False)
    ssh(node,"tee",temporary,input_bytes=payload)
    try:
        ssh(node,"sudo","-n","bash",temporary,"--install",timeout=90)
    finally:
        ssh(node,"rm","-f",temporary,check=False)
    remote_sha256 = text(ssh(node,"sha256sum","/usr/local/sbin/ds4-switched-fabric-apply")).split()[0]
    if remote_sha256 != expected_sha256:
        raise FleetError(f"{node}: installed script hash mismatch")
    if ssh(node,"sudo","-n","test","!","-e","/etc/nvidia/cx7-hotplug-enabled",check=False).returncode != 0:
        raise FleetError(f"{node}: CX7 hot-plug marker remains present")
    return({"installed_sha256":remote_sha256,"node":node})


def canonicalize_rank(node: str) -> dict[str,object]:
    expected = str(rank(node))
    workload_names = (
        "sparkpipe_model",
        "sparkpipe_glm52_cuda_residentd",
        "sparkpipe_gateway",
        "sparkpipe_glm52_gateway",
    )
    for name in workload_names:
        if ssh(node,"pgrep","-x",name,check=False).returncode == 0:
            raise FleetError(f"{node}: workload is active; refusing rank-file migration")
    compute_apps = text(ssh(
        node,
        "nvidia-smi",
        "--query-compute-apps=pid,process_name",
        "--format=csv,noheader,nounits",
        check=False,
    ))
    if compute_apps:
        raise FleetError(f"{node}: GPU compute workload is active; refusing rank-file migration")
    canonical = text(ssh(node,"sudo","-n","cat","/etc/ds4-node-rank",check=False))
    legacy = text(ssh(node,"sudo","-n","cat","/etc/ds4-ring-rank",check=False))
    if canonical not in ("",expected):
        raise FleetError(f"{node}: canonical rank is {canonical!r}, expected {expected!r}")
    if legacy not in ("",expected):
        raise FleetError(f"{node}: legacy rank is {legacy!r}, expected {expected!r}")
    if canonical != expected:
        temporary = "/tmp/ds4-node-rank"
        ssh(node,"tee",temporary,input_bytes=(expected + "\n").encode())
        try:
            ssh(node,"sudo","-n","install","-m","0644","-o","root","-g","root",temporary,"/etc/ds4-node-rank")
        finally:
            ssh(node,"rm","-f",temporary,check=False)
    if legacy != "":
        ssh(node,"sudo","-n","rm","-f","/etc/ds4-ring-rank")
    final_canonical = text(ssh(node,"sudo","-n","cat","/etc/ds4-node-rank"))
    if final_canonical != expected or ssh(node,"sudo","-n","test","!","-e","/etc/ds4-ring-rank",check=False).returncode != 0:
        raise FleetError(f"{node}: rank-file migration verification failed")
    return({"node":node,"rank":int(expected),"canonical":"/etc/ds4-node-rank","legacy_removed":True})


def boot_id(node: str,check: bool = True) -> str:
    return(text(ssh(node,"cat","/proc/sys/kernel/random/boot_id",timeout=10,check=check)))


def reboot(node: str,old_boot_id: str,timeout_s: int) -> dict[str,object]:
    ssh(node,"sudo","-n","systemctl","reboot",timeout=10,check=False)
    deadline = time.monotonic() + timeout_s
    saw_disconnect = False
    last_error = ""
    while time.monotonic() < deadline:
        result = ssh(node,"cat","/proc/sys/kernel/random/boot_id",timeout=8,check=False)
        if result.returncode != 0:
            saw_disconnect = True
            last_error = result.stderr.decode("utf-8",errors="replace").strip()
        else:
            current = text(result)
            if saw_disconnect and current != old_boot_id:
                return({"boot_id":current,"node":node})
        time.sleep(5)
    raise FleetError(f"{node}: reboot timeout; last={last_error}")


def verify(node: str) -> dict[str,object]:
    expected_ip = f"10.10.100.{10 + rank(node)}/24"
    mapping = text(ssh(node,"ibdev2netdev"))
    active = [line for line in mapping.splitlines() if line.startswith("rocep1s0f") and line.endswith("(Up)")]
    if len(active) != 1:
        raise FleetError(f"{node}: expected one active lower-case RDMA device, got {active}")
    fields = active[0].split()
    rdma_device = fields[0]
    ethernet_device = fields[4]
    addresses = text(ssh(node,"ip","-o","-4","address","show","dev",ethernet_device))
    if expected_ip not in addresses:
        raise FleetError(f"{node}: {ethernet_device} lacks {expected_ip}")
    ping = ssh(node,"ping","-c","3","-M","do","-s","8972","10.10.100.10",timeout=15,check=False)
    if ping.returncode != 0:
        raise FleetError(f"{node}: jumbo ping failed")
    fabric_unit = "ds4-switched-fabric.service"
    if text(ssh(node,"systemctl","is-enabled",fabric_unit,check=False)) != "enabled":
        raise FleetError(f"{node}: {fabric_unit} is not enabled")
    if text(ssh(node,"systemctl","is-active",fabric_unit,check=False)) != "active":
        raise FleetError(f"{node}: {fabric_unit} is not active")
    failed_units = [
        row for row in text(ssh(node,"systemctl","--failed","--no-legend",check=False)).splitlines()
        if row.strip()
    ]
    if ssh(node,"sudo","-n","test","!","-e","/etc/nvidia/cx7-hotplug-enabled",check=False).returncode != 0:
        raise FleetError(f"{node}: CX7 hot-plug marker was recreated")
    return({
        "ethernet_device":ethernet_device,
        "fabric_ip":expected_ip,
        "node":node,
        "rdma_device":rdma_device,
        "failed_units":failed_units,
    })


def parallel(nodes: tuple[str,...],function,workers: int,continue_on_error: bool = False) -> list[dict[str,object]]:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(function,node):node for node in nodes}
        for future in as_completed(futures):
            node = futures[future]
            try:
                result = future.result()
            except Exception as error:
                if not continue_on_error:
                    raise
                result = {"error":str(error),"node":node}
                print(f"{node}: failed: {error}",flush=True)
            else:
                print(f"{node}: complete",flush=True)
            results.append(result)
    return(sorted(results,key=lambda item:rank(str(item["node"]))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes",default=",".join(DEFAULT_NODES))
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--canonicalize-ranks",action="store_true")
    parser.add_argument("--reboot",action="store_true")
    parser.add_argument("--wave-size",type=int,default=4)
    parser.add_argument("--reboot-timeout-s",type=int,default=300)
    parser.add_argument("--continue-on-error",action="store_true")
    return(parser.parse_args())


def main() -> int:
    args = parse_args()
    nodes = tuple(item.strip() for item in args.nodes.split(",") if item.strip())
    for node in nodes:
        rank(node)
    if args.reboot and not args.apply:
        raise FleetError("--reboot requires --apply")
    if args.reboot and args.canonicalize_ranks:
        raise FleetError("--reboot cannot be combined with --canonicalize-ranks")
    payload = APPLY_SCRIPT.read_bytes()
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    receipt: dict[str,object] = {"apply_sha256":expected_sha256,"nodes":nodes}
    if args.apply:
        receipt["install"] = parallel(nodes,lambda node:install(node,payload,expected_sha256),args.wave_size)
    if args.canonicalize_ranks:
        receipt["canonicalize_ranks"] = parallel(nodes,canonicalize_rank,args.wave_size)
    if args.reboot:
        reboot_results = []
        for offset in range(0,len(nodes),args.wave_size):
            wave = nodes[offset:offset + args.wave_size]
            old_ids = {node:boot_id(node) for node in wave}
            print(f"reboot wave: {','.join(wave)}",flush=True)
            wave_results = parallel(wave,lambda node:reboot(node,old_ids[node],args.reboot_timeout_s),len(wave),args.continue_on_error)
            reboot_results.extend(wave_results)
        receipt["reboot"] = reboot_results
    receipt["verify"] = parallel(nodes,verify,args.wave_size,args.continue_on_error)
    receipt_path = Path(tempfile.gettempdir()) / "ds4_switched_fabric_fleet_receipt.json"
    receipt_path.write_text(json.dumps(receipt,indent=2,sort_keys=True) + "\n",encoding="utf-8")
    print(f"receipt={receipt_path}")
    failed = any(
        "error" in item
        for section in ("install","reboot","verify")
        for item in receipt.get(section,[])
    )
    return(1 if failed else 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FleetError as error:
        print(f"ds4_switched_fabric_fleet: {error}")
        raise SystemExit(1)
