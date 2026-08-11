#!/usr/bin/env python3
"""Read-only deep audit of Spark hardware, fabric, storage, and runtime drift."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY = ROOT / "v2" / "profiles" / "transfer" / "spark_200g.json"
PREFLIGHT_PATH = Path(__file__).with_name("ds4_spark_fleet_preflight.py")
spec = importlib.util.spec_from_file_location("ds4_spark_fleet_preflight",PREFLIGHT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load fleet transport: {PREFLIGHT_PATH}")
preflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


FABRIC_DEVICES = (
    "enp1s0f0np0",
    "enp1s0f1np1",
    "enP2p1s0f0np0",
    "enP2p1s0f1np1",
)
RELEVANT_UNITS = (
    "ds4-switched-fabric.service",
    "centaur-sparkring-agent.service",
    "tailscaled.service",
    "NetworkManager.service",
    "systemd-timesyncd.service",
    "chrony.service",
    "nvidia-fabricmanager.service",
)
CONFIG_PATHS = (
    "/etc/ds4-node-rank",
    "/etc/ds4-ring-rank",
    "/etc/fstab",
    "/etc/hosts",
    "/etc/hostname",
    "/etc/ssh/sshd_config",
    "/etc/ssh/sshd_config.d",
    "/etc/NetworkManager/system-connections",
    "/etc/netplan",
    "/etc/modprobe.d",
    "/etc/modules-load.d",
    "/etc/sysctl.conf",
    "/etc/sysctl.d",
    "/etc/systemd/system",
)
SYSCTL_KEYS = (
    "net.ipv4.tcp_congestion_control",
    "net.ipv4.tcp_rmem",
    "net.ipv4.tcp_wmem",
    "net.core.rmem_max",
    "net.core.wmem_max",
    "net.core.netdev_max_backlog",
    "net.ipv4.conf.all.rp_filter",
    "net.ipv4.ip_forward",
    "vm.swappiness",
    "vm.zone_reclaim_mode",
)
WORKLOAD_PROCESSES = (
    "sparkpipe_model",
    "sparkpipe_glm52_cuda_residentd",
    "sparkpipe_gateway",
    "sparkpipe_glm52_gateway",
    "centaur_sparkring_service",
)


REMOTE_AUDIT = r'''
import hashlib
import json
from pathlib import Path
import re
import subprocess


FABRIC_DEVICES = %s
RELEVANT_UNITS = %s
CONFIG_PATHS = %s
SYSCTL_KEYS = %s
WORKLOAD_PROCESSES = %s


def command(argv, timeout=10):
    try:
        result = subprocess.run(argv,capture_output=True,text=True,timeout=timeout,check=False)
    except (OSError,subprocess.TimeoutExpired) as error:
        return "",str(error),124
    return result.stdout.strip(),result.stderr.strip(),result.returncode


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8",errors="replace").strip()
    except OSError:
        return ""


def first_line(value):
    return value.splitlines()[0].strip() if value.splitlines() else ""


def json_command(argv,timeout=10):
    output,error,code = command(argv,timeout)
    if code != 0:
        return {"available":False,"error":error or output or str(code)}
    try:
        return {"available":True,"value":json.loads(output)}
    except json.JSONDecodeError:
        return {"available":False,"error":"invalid-json"}


def digest(value):
    return hashlib.sha256(value.encode("utf-8",errors="replace")).hexdigest()


def command_digest(argv,timeout=20):
    output,error,code = command(argv,timeout)
    return {
        "available":code == 0,
        "sha256":digest(output) if output else "",
        "line_count":len(output.splitlines()),
        "error":error if code != 0 else "",
    }


def normalized_command_digest(argv,timeout=20):
    output,error,code = command(argv,timeout)
    normalized = re.sub(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b","<ip>",output)
    normalized = re.sub(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f]*:[0-9A-Fa-f:]+(?![0-9A-Fa-f:])","<ipv6>",normalized)
    normalized = re.sub(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b","<mac>",normalized)
    normalized = re.sub(r"\bcounter packets [0-9]+ bytes [0-9]+\b","counter",normalized)
    return {
        "available":code == 0,
        "sha256":digest(normalized) if normalized else "",
        "line_count":len(normalized.splitlines()),
        "error":error if code != 0 else "",
    }


def parse_ring_parameters(device):
    output,_,code = command(["ethtool","-g",device],12)
    sections = {"preset":{},"current":{}}
    section = "preset"
    for row in output.splitlines():
        line = row.strip()
        if line.lower().startswith("current hardware settings"):
            section = "current"
            continue
        if ":" not in line:
            continue
        key,value = [part.strip() for part in line.split(":",1)]
        if key not in ("RX","TX","RX Mini","RX Jumbo"):
            continue
        sections[section][key] = value
    return {"available":code == 0,"sections":sections}


def parse_offloads(device):
    output,_,code = command(["ethtool","-k",device],12)
    keys = {
        "rx-checksumming",
        "tx-checksumming",
        "scatter-gather",
        "tcp-segmentation-offload",
        "generic-segmentation-offload",
        "generic-receive-offload",
        "receive-hashing",
        "rx-vlan-offload",
        "tx-vlan-offload",
        "hw-tc-offload",
        "rx-gro-hw",
        "rx-gro-list",
        "tx-tcp-mangleid-segmentation",
    }
    values = {}
    for row in output.splitlines():
        line = row.strip()
        if ":" not in line:
            continue
        key,value = [part.strip() for part in line.split(":",1)]
        if key in keys:
            values[key] = value.split(" [",1)[0]
    return {"available":code == 0,"values":values}


def privileged_tree_digest(path):
    script = (
        "set -o pipefail; "
        "if [ -d \"$1\" ]; then "
        "find \"$1\" -type f -print0 | sort -z | xargs -0 -r sha256sum; "
        "elif [ -f \"$1\" ]; then sha256sum \"$1\"; "
        "else printf ABSENT; fi"
    )
    output,error,code = command(["sudo","-n","bash","-c",script,"hash",path],20)
    return {
        "available":code == 0,
        "sha256":digest(output) if output else "",
        "line_count":len(output.splitlines()),
        "error":error if code != 0 else "",
    }


def unit_state(unit):
    enabled,_,enabled_code = command(["systemctl","is-enabled",unit])
    active,_,active_code = command(["systemctl","is-active",unit])
    return {
        "enabled":enabled if enabled_code == 0 else "unavailable",
        "active":active if active_code == 0 else "unavailable",
    }


def interface_state(device):
    root = Path("/sys/class/net") / device
    if not root.exists():
        return {"device":device,"present":False}
    driver = ""
    driver_link = root / "device" / "driver"
    try:
        driver = str(driver_link.resolve()).rsplit("/",1)[-1]
    except OSError:
        pass
    addresses,_,_ = command(["ip","-o","-4","addr","show","dev",device])
    features = {}
    for suffix in ("-i","-k","-c","-g","-l"):
        features[suffix] = command_digest(["ethtool",suffix,device],12)
    return {
        "device":device,
        "present":True,
        "driver":driver,
        "operstate":read_text(root / "operstate"),
        "carrier":read_text(root / "carrier"),
        "speed_mbps":read_text(root / "speed"),
        "duplex":read_text(root / "duplex"),
        "mtu":read_text(root / "mtu"),
        "mac":read_text(root / "address"),
        "ipv4":[row.split()[3] for row in addresses.splitlines() if len(row.split()) > 3],
        "ethtool":features,
        "ring":parse_ring_parameters(device),
        "offloads":parse_offloads(device),
    }


def all_interfaces():
    try:
        names = sorted(path.name for path in Path("/sys/class/net").iterdir())
    except OSError:
        names = []
    return [interface_state(name) for name in names]


def gpu_state():
    query = command([
        "nvidia-smi","--query-gpu=name,driver_version,memory.total,pci.bus_id,pstate,compute_mode",
        "--format=csv,noheader,nounits",
    ],15)
    apps = command([
        "nvidia-smi","--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ],15)
    return {
        "query_ok":query[2] == 0,
        "rows":[row.strip() for row in query[0].splitlines() if row.strip()],
        "query_error":query[1] if query[2] != 0 else "",
        "compute_apps":[row.strip() for row in apps[0].splitlines() if row.strip()] if apps[2] == 0 else [],
    }


def nvme_state():
    devices = sorted(str(path) for path in Path("/dev").glob("nvme*n1"))
    smart = {}
    for device in devices:
        output,error,code = command(["sudo","-n","nvme","smart-log","-o","json",device],20)
        if code == 0:
            try:
                payload = json.loads(output)
                smart[device] = {
                    "available":True,
                    "critical_warning":payload.get("critical_warning"),
                    "temperature":payload.get("temperature"),
                    "available_spare":payload.get("available_spare"),
                    "percentage_used":payload.get("percentage_used"),
                    "media_errors":payload.get("media_errors"),
                    "num_err_log_entries":payload.get("num_err_log_entries"),
                }
            except json.JSONDecodeError:
                smart[device] = {"available":False,"error":"invalid-json"}
        else:
            smart[device] = {"available":False,"error":error or output}
    inventory = json_command(["nvme","list","-o","json"],15)
    inventory_value = inventory.get("value",{}) if inventory.get("available") else {}
    inventory_rows = []
    for item in inventory_value.get("Devices",[]) if isinstance(inventory_value,dict) else []:
        if not isinstance(item,dict):
            continue
        inventory_rows.append({
            key:item.get(key)
            for key in ("ModelNumber","Firmware","PhysicalSize","UsedBytes","SectorSize")
            if key in item
        })
    return {
        "devices":devices,
        "list":command_digest(["nvme","list"],15),
        "subsystems":command_digest(["nvme","list-subsys"],15),
        "inventory":sorted(inventory_rows,key=lambda item:json.dumps(item,sort_keys=True)),
        "smart":smart,
    }


def mount_state():
    mounts = json_command(["findmnt","--json","--real","--all"],15)
    df_output,df_error,df_code = command(["df","-P","-x","tmpfs","-x","devtmpfs","-x","squashfs"],15)
    return {
        "findmnt":mounts,
        "df":{
            "available":df_code == 0,
            "sha256":digest(df_output) if df_output else "",
            "line_count":len(df_output.splitlines()),
            "error":df_error if df_code != 0 else "",
        },
    }


def process_state():
    result = {}
    for name in WORKLOAD_PROCESSES:
        output,_,code = command(["pgrep","-x",name])
        result[name] = output.split() if code == 0 else []
    return result


def main():
    os_release = {}
    for row in read_text("/etc/os-release").splitlines():
        if "=" not in row:
            continue
        key,value = row.split("=",1)
        os_release[key] = value.strip().strip('"')
    lscpu = json_command(["lscpu","-J"],12)
    memory = {}
    for row in read_text("/proc/meminfo").splitlines():
        if row.startswith(("MemTotal:","HugePages_Total:","HugePages_Free:","SwapTotal:","SwapFree:")):
            fields = row.split()
            memory[fields[0].rstrip(":")] = fields[1:]
    all_addresses = json_command(["ip","-j","addr","show"],12)
    routes = json_command(["ip","-j","route","show","table","main"],12)
    rules = command_digest(["ip","rule","show"],12)
    rdma = command_digest(["rdma","link"],12)
    ibdev = command_digest(["ibdev2netdev"],12)
    pci = command_digest(["lspci","-nnk"],20)
    usb = command_digest(["lsusb","-t"],12)
    package_command = [
        "dpkg-query","-W","-f=${binary:Package}\\t${Version}\\t${Architecture}\\n",
    ]
    package_manifest = command_digest(package_command,30)
    package_output,package_error,package_code = command(package_command,30)
    manual_output,manual_error,manual_code = command(["apt-mark","showmanual"],20)
    manual_packages = command_digest(["apt-mark","showmanual"],20)
    sysctls = {}
    for key in SYSCTL_KEYS:
        value,error,code = command(["sysctl","-n",key])
        sysctls[key] = value if code == 0 else "unavailable"
    config_hashes = {path:privileged_tree_digest(path) for path in CONFIG_PATHS}
    service_hash = privileged_tree_digest("/usr/lib/systemd/system")
    failed_units = command_digest(["systemctl","--failed","--no-legend"],12)
    enabled_units = command_digest(["systemctl","list-unit-files","--state=enabled","--no-legend","--no-pager"],20)
    firewall = normalized_command_digest(["sudo","-n","nft","list","ruleset"],15)
    kernel_errors = command_digest(["journalctl","-k","-b","--no-pager","-p","err..alert"],20)
    kernel_xids = command_digest(["sudo","-n","dmesg","--color=never"],12)
    time_state = {
        "timedatectl":command_digest(["timedatectl","show","--no-pager"],12),
        "chronyc":command_digest(["chronyc","tracking"],12),
    }
    result = {
        "identity":{
            "hostname":first_line(command(["hostname","-s"])[0]),
            "kernel":first_line(command(["uname","-r"])[0]),
            "arch":first_line(command(["uname","-m"])[0]),
            "os_release":os_release,
            "lscpu":lscpu,
            "memory":memory,
        },
        "rank":{
            "canonical":read_text("/etc/ds4-node-rank"),
            "legacy":read_text("/etc/ds4-ring-rank"),
        },
        "gpu":gpu_state(),
        "cuda":{
            "nvcc":command_digest(["nvcc","--version"],12),
            "cuda_libraries":command_digest(["bash","-c","ldconfig -p | grep -E 'libcuda|libcudart'"],12),
        },
        "network":{
            "interfaces":all_interfaces(),
            "addresses":all_addresses,
            "routes":routes,
            "rules":rules,
            "rdma":rdma,
            "ibdev2netdev":ibdev,
            "sysctls":sysctls,
            "network_manager_connections":command_digest([
                "nmcli","-t","-f","NAME,UUID,TYPE,DEVICE,STATE","connection","show",
            ],15),
        },
        "storage":{
            "mounts":mount_state(),
            "lsblk":json_command(["lsblk","--json","--output-all"],20),
            "nvme":nvme_state(),
            "pci":pci,
            "usb_tree":usb,
            "smart_scan":command_digest(["sudo","-n","smartctl","--scan-open"],15),
        },
        "software":{
            "packages":package_manifest,
            "package_rows":[row for row in package_output.splitlines() if row.strip()] if package_code == 0 else [],
            "package_error":package_error if package_code != 0 else "",
            "manual_packages":manual_packages,
            "manual_package_rows":[row for row in manual_output.splitlines() if row.strip()] if manual_code == 0 else [],
            "manual_package_error":manual_error if manual_code != 0 else "",
            "config_hashes":config_hashes,
            "usr_systemd_hash":service_hash,
            "units":{unit:unit_state(unit) for unit in RELEVANT_UNITS},
            "failed_units":failed_units,
            "enabled_units":enabled_units,
        },
        "health":{
            "firewall":firewall,
            "kernel_errors":kernel_errors,
            "kernel_dmesg":kernel_xids,
            "time":time_state,
            "workloads":process_state(),
        },
    }
    print(json.dumps(result,sort_keys=True))


if __name__ == "__main__":
    main()
''' % (
    repr(FABRIC_DEVICES),
    repr(RELEVANT_UNITS),
    repr(CONFIG_PATHS),
    repr(SYSCTL_KEYS),
    repr(WORKLOAD_PROCESSES),
)


def parse_nodes(raw: str, nodes: tuple[Any,...]) -> tuple[Any,...]:
    if raw.strip() == "":
        return nodes
    by_name = {node.node_id:node for node in nodes}
    selected = []
    for value in raw.split(","):
        name = value.strip()
        if name == "":
            continue
        if name not in by_name:
            raise ValueError(f"node is absent from topology: {name}")
        selected.append(by_name[name])
    return tuple(selected)


def audit_node(node: Any, route: str, topology: str, ssh_options: list[str], timeout_s: int) -> dict[str,Any]:
    selected_route,stdout,error = preflight.run_remote_payload(
        node,route,topology,ssh_options,REMOTE_AUDIT,timeout_s
    )
    if error:
        return {"node_id":node.node_id,"route":"unreachable","error":error}
    try:
        observed = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as parse_error:
        return {
            "node_id":node.node_id,
            "route":selected_route,
            "error":f"invalid audit JSON: {parse_error}",
            "raw_sha256":hashlib.sha256(stdout).hexdigest(),
        }
    return {"node_id":node.node_id,"rank":node.rank,"route":selected_route,"observed":observed}


def get_path(data: dict[str,Any], path: tuple[str,...]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value,dict) or key not in value:
            return None
        value = value[key]
    return value


def stable(value: Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)


def normalize_field(observed: dict[str,Any], label: str, path: tuple[str,...]) -> Any:
    value = get_path(observed,path)
    if label == "identity.cpu":
        if not isinstance(value,dict) or not value.get("available"):
            return value
        fields = value.get("value",{}).get("lscpu",[]) if isinstance(value.get("value"),dict) else []
        keep = {
            "Architecture",
            "CPU(s)",
            "Core(s) per socket",
            "Model name",
            "On-line CPU(s) list",
            "Socket(s)",
            "Thread(s) per core",
            "Vendor ID",
        }
        return sorted(
            {str(item.get("field")):str(item.get("data")) for item in fields if item.get("field") in keep}.items()
        )
    if label == "gpu":
        rows = [] if value is None else value
        normalized = []
        for row in rows:
            fields = [item.strip() for item in str(row).split(",")]
            if len(fields) >= 6:
                normalized.append((fields[0],fields[1],fields[2],fields[5]))
            else:
                normalized.append(tuple(fields[:3]))
        return sorted(normalized)
    if label == "network.fabric_interfaces":
        normalized = []
        active = [
            item for item in value or []
            if item.get("device") in FABRIC_DEVICES
            and item.get("operstate") == "up"
            and str(item.get("speed_mbps")) == "100000"
        ]
        for item in active:
            if item.get("device") not in FABRIC_DEVICES:
                continue
            normalized.append({
                key:item.get(key)
                for key in ("device","present","driver","operstate","carrier","speed_mbps","duplex","mtu","ring","offloads")
            })
        return normalized
    if label == "network.routes":
        payload = value.get("value") if isinstance(value,dict) else None
        if not isinstance(payload,list):
            return value
        keep = ("dst","dev","protocol","scope","table","type","metric")
        rows = [
            {key:item.get(key) for key in keep if key in item}
            for item in payload if isinstance(item,dict)
        ]
        return sorted(rows,key=lambda item:stable(item))
    if label == "storage.mounts":
        payload = get_path(observed,("storage","mounts","findmnt","value","filesystems"))
        if not isinstance(payload,list):
            return value
        rows = []
        def visit(items):
            for item in items:
                if not isinstance(item,dict):
                    continue
                rows.append({
                    key:item.get(key)
                    for key in ("target","source","fstype","options") if key in item
                })
                visit(item.get("children",[]))
        visit(payload)
        return sorted(rows,key=lambda item:stable(item))
    if label == "storage.lsblk":
        payload = value.get("value",{}).get("blockdevices") if isinstance(value,dict) else None
        if not isinstance(payload,list):
            return value
        def normalize_devices(items):
            result = []
            for item in items:
                if not isinstance(item,dict):
                    continue
                result.append({
                    key:item.get(key)
                    for key in ("name","type","size","model","vendor","rev","tran","fstype","parttype","rota")
                    if key in item
                } | {"children":normalize_devices(item.get("children",[]))})
            return result
        return normalize_devices(payload)
    if label == "software.config_hashes":
        if not isinstance(value,dict):
            return value
        ignored = {"/etc/ds4-node-rank","/etc/ds4-ring-rank","/etc/hosts","/etc/hostname","/etc/fstab"}
        return {key:item for key,item in value.items() if key not in ignored}
    if label.startswith("software.config:"):
        path_name = label.split(":",1)[1]
        return value.get(path_name) if isinstance(value,dict) else None
    return value


def group_values(rows: list[dict[str,Any]], path: tuple[str,...], label: str = "") -> dict[str,list[str]]:
    groups: dict[str,list[str]] = {}
    for row in rows:
        value = stable(normalize_field(row.get("observed",{}),label,path))
        groups.setdefault(value,[]).append(row["node_id"])
    return {key:sorted(value) for key,value in groups.items()}


def cohort(node_id: str) -> str:
    return "original13" if int(node_id[5:],16) < 13 else "staging3"


def within_cohort_drift(rows: list[dict[str,Any]], path: tuple[str,...], label: str) -> dict[str,Any]:
    cohorts: dict[str,dict[str,list[str]]] = {}
    for name in ("original13","staging3"):
        cohorts[name] = group_values(
            [row for row in rows if cohort(row["node_id"]) == name],path,label
        )
    return cohorts


def compare(rows: list[dict[str,Any]]) -> dict[str,Any]:
    comparable = {
        "identity.kernel":("identity","kernel"),
        "identity.arch":("identity","arch"),
        "identity.os_release":("identity","os_release"),
        "identity.cpu":("identity","lscpu"),
        "identity.memory":("identity","memory"),
        "gpu":("gpu","rows"),
        "cuda.nvcc":("cuda","nvcc"),
        "cuda.libraries":("cuda","cuda_libraries"),
        "network.fabric_interfaces":("network","interfaces"),
        "network.routes":("network","routes"),
        "network.rules":("network","rules"),
        "network.rdma":("network","rdma"),
        "network.ibdev2netdev":("network","ibdev2netdev"),
        "network.sysctls":("network","sysctls"),
        "storage.mounts":("storage","mounts"),
        "storage.lsblk":("storage","lsblk"),
        "storage.nvme.inventory":("storage","nvme","inventory"),
        "storage.pci":("storage","pci"),
        "storage.usb_tree":("storage","usb_tree"),
        "software.packages":("software","packages"),
        "software.manual_packages":("software","manual_packages"),
        "software.usr_systemd_hash":("software","usr_systemd_hash"),
        "software.enabled_units":("software","enabled_units"),
        "health.firewall":("health","firewall"),
    }
    for path_name in CONFIG_PATHS:
        if path_name in {"/etc/ds4-node-rank","/etc/ds4-ring-rank","/etc/hosts","/etc/hostname","/etc/fstab"}:
            continue
        comparable[f"software.config:{path_name}"] = ("software","config_hashes")
    expected_cohort_split = {
        "identity.kernel",
        "identity.os_release",
        "gpu",
        "cuda.nvcc",
        "cuda.libraries",
        "software.packages",
        "software.manual_packages",
        "software.usr_systemd_hash",
    }
    expected_role_variation = {
        "identity.memory",
        "storage.mounts",
        "storage.lsblk",
        "storage.nvme.inventory",
        "storage.pci",
        "storage.usb_tree",
        "software.config:/etc/netplan",
        "software.config:/etc/NetworkManager/system-connections",
    }
    details = {}
    unexpected = []
    for label,path in comparable.items():
        all_groups = group_values(rows,path,label)
        cohorts = within_cohort_drift(rows,path,label)
        cohort_drift = [name for name,groups in cohorts.items() if len(groups) > 1]
        if label in expected_role_variation:
            status = "expected_hardware_or_node_role_variation"
        elif label in expected_cohort_split:
            status = "expected_cohort_split" if not cohort_drift else "unexpected_within_cohort_drift"
        else:
            status = "uniform" if len(all_groups) <= 1 else "unexpected_drift"
        if status.startswith("unexpected"):
            unexpected.append(label)
        details[label] = {
            "status":status,
            "groups":all_groups,
            "within_cohort":cohorts,
        }
    return {"fields":details,"unexpected_fields":sorted(unexpected)}


def expected_address_checks(rows: list[dict[str,Any]], nodes: tuple[Any,...]) -> list[str]:
    by_name = {node.node_id:node for node in nodes}
    failures = []
    for row in rows:
        node = by_name[row["node_id"]]
        observed = row.get("observed",{})
        interfaces = get_path(observed,("network","interfaces")) or []
        addresses = [address for item in interfaces for address in item.get("ipv4",[])]
        if not any(str(address).startswith(node.management_ip + "/") for address in addresses):
            failures.append(f"{node.node_id}:management_address_missing")
        if not any(str(address).startswith(node.fabric_ip + "/") for address in addresses):
            failures.append(f"{node.node_id}:fabric_address_missing")
    return failures


def print_report(summary: dict[str,Any]) -> None:
    print("node    route       result       kernel                     100G  gpu  nvme")
    print("------  ----------  -----------  -------------------------  ----  ---  ----")
    for row in summary["results"]:
        observed = row.get("observed",{})
        interfaces = get_path(observed,("network","interfaces")) or []
        links = [item for item in interfaces if item.get("device") in FABRIC_DEVICES]
        qualified = sum(
            1 for item in links
            if item.get("operstate") == "up"
            and str(item.get("duplex")).lower() == "full"
            and str(item.get("speed_mbps")) == "100000"
        )
        nvme = get_path(observed,("storage","nvme","devices")) or []
        print(
            f"{row['node_id']:<6}  {row.get('route',''):<10}  "
            f"{('ERROR' if row.get('error') else 'OK'):<11}  "
            f"{str(get_path(observed,('identity','kernel')) or ''):<25}  "
            f"{qualified:>4}  {len(get_path(observed,('gpu','rows')) or []):>3}  "
            f"{len(nvme):>7}"
        )
        if row.get("error"):
            print(f"  ERROR {row['node_id']}: {row['error']}")
    comparison = summary["comparison"]
    for label,detail in comparison["fields"].items():
        if detail["status"] in ("uniform","expected_cohort_split"):
            continue
        prefix = "VARIATION" if detail["status"] == "expected_hardware_or_node_role_variation" else "DRIFT"
        print(f"{prefix} {label}: {detail['status']}")
        for value,names in detail["groups"].items():
            print(f"  {','.join(names)} value={value[:180]}")
    for item in summary["address_failures"]:
        print(f"DRIFT {item}")
    print(f"unexpected_fields={len(comparison['unexpected_fields'])}")
    print(f"address_failures={len(summary['address_failures'])}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology",default=str(DEFAULT_TOPOLOGY))
    parser.add_argument("--nodes",default="",help="comma-separated node ids; default is the full topology")
    parser.add_argument("--route",choices=("auto","fabric","mgmt","tailscale"),default="auto")
    parser.add_argument("--timeout-s",type=int,default=12)
    parser.add_argument("--workers",type=int,default=16)
    parser.add_argument("--json-output",default="")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    topology = Path(args.topology).expanduser()
    nodes = parse_nodes(args.nodes,preflight.load_nodes(str(topology)))
    ssh_options = preflight.load_ssh_options(str(topology))
    workers = max(1,min(args.workers,len(nodes)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(
            lambda node:audit_node(node,args.route,str(topology),ssh_options,args.timeout_s),nodes
        ))
    valid = [row for row in results if not row.get("error")]
    summary = {
        "completed_at":datetime.now(timezone.utc).isoformat(),
        "topology":str(topology),
        "route_policy":args.route,
        "node_count":len(results),
        "successful_nodes":len(valid),
        "results":results,
        "comparison":compare(valid) if valid else {"fields":{},"unexpected_fields":[]},
        "address_failures":expected_address_checks(valid,nodes),
    }
    print_report(summary)
    if args.json_output:
        output = Path(args.json_output).expanduser()
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(summary,indent=2,sort_keys=True) + "\n",encoding="utf-8")
        print(f"receipt={output}")
    return 1 if len(valid) != len(results) or summary["comparison"]["unexpected_fields"] or summary["address_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
