#!/usr/bin/env python3
"""Configure and maintain ordered Spark Internet uplinks."""

from __future__ import annotations

import argparse
from dataclasses import asdict,dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ASUS_SSID = "ASUS_40"
ASUS_GATEWAY = "192.168.50.1"
ASUS_STATIC_BASE = 128
MAC_STATIC_ADDRESS = "192.168.50.249"
MAX_SPARK_RANK = 120
MANAGEMENT_BASE = 10
MANAGEMENT_GATEWAY = "10.20.0.1"
WIRED_PROFILE = "ds4-uplink-wired"
ASUS_PROFILE = "ds4-uplink-asus"
TPLINK_PROFILE = "ds4-uplink-tplink"
TPLINK_SSIDS = ("TP-Link_D660_5G","TP-Link_D660")
WIRED_METRIC = 10
ASUS_METRIC = 100
TPLINK_METRIC = 200
ASUS_RETRY_SECONDS = 300
WIFI_ACTIVATION_SECONDS = 45
PROBE_ADDRESS = "1.1.1.1"
PROBE_URL = "https://1.1.1.1/cdn-cgi/trace"
NMCLI_RECOVERY_SECONDS = 30
NMCLI_RECOVERY_INTERVAL_SECONDS = 1
NMCLI_RECOVERABLE_ERRORS = (
    "networkmanager is not running",
    "message recipient disconnected from message bus",
    "could not create nmclient object",
    "networkmanager is not available",
)
DEFAULT_CONFIG = Path("/etc/ds4-uplink/config.json")
DEFAULT_STATE_DIR = Path("/run/ds4-uplink")


class UplinkError(RuntimeError):
    """Raised when the ordered uplink contract cannot be satisfied."""


@dataclass(frozen=True)
class UplinkPlan:
    node_id: str
    rank: int
    wired_interface: str
    wifi_interface: str
    management_cidr: str
    asus_wired_cidr: str
    asus_gateway: str
    asus_ssid: str
    tplink_ssids: tuple[str,...]
    wired_profile: str
    asus_profile: str
    tplink_profile: str
    wired_metric: int
    asus_metric: int
    tplink_metric: int
    asus_psk_file: str
    management_gateway: str = MANAGEMENT_GATEWAY

    @property
    def asus_wired_address(self) -> str:
        return(self.asus_wired_cidr.split("/",1)[0])


def nmcli_failure_is_recoverable(result: subprocess.CompletedProcess[str]) -> bool:
    detail = f"{result.stderr}\n{result.stdout}".lower()
    return(any(marker in detail for marker in NMCLI_RECOVERABLE_ERRORS))


class Runner:
    def run(
        self,
        argv: list[str],
        *,
        check: bool = True,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        deadline = time.monotonic() + NMCLI_RECOVERY_SECONDS
        recovery_reported = False
        while True:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0 or argv[0] != "nmcli":
                break
            if not nmcli_failure_is_recoverable(result):
                break
            if time.monotonic() >= deadline:
                break
            if not recovery_reported:
                print("uplink_recovery networkmanager=waiting",file=sys.stderr)
                recovery_reported = True
            time.sleep(NMCLI_RECOVERY_INTERVAL_SECONDS)
        if recovery_reported and result.returncode == 0:
            print("uplink_recovery networkmanager=ready",file=sys.stderr)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise UplinkError(f"command failed ({result.returncode}): {argv[0]}: {detail}")
        return(result)


def spark_rank(node_id: str) -> int:
    match = re.fullmatch(r"spark([0-9a-f]+)",node_id.lower())
    if match is None:
        raise UplinkError(f"invalid Spark node id: {node_id}")
    rank = int(match.group(1),16)
    if rank > MAX_SPARK_RANK:
        raise UplinkError(f"Spark rank {rank} exceeds reserved static range")
    return(rank)


def plan_for_node(node_id: str,asus_psk_file: str = "/etc/ds4-uplink/asus.psk") -> UplinkPlan:
    rank = spark_rank(node_id)
    management_octet = MANAGEMENT_BASE + rank
    asus_octet = ASUS_STATIC_BASE + rank
    if management_octet > 254 or asus_octet > 248:
        raise UplinkError(f"Spark rank {rank} cannot be represented by the reserved ranges")
    return(UplinkPlan(
        node_id=node_id.lower(),
        rank=rank,
        wired_interface="enP7s7",
        wifi_interface="wlP9s9",
        management_cidr=f"10.20.0.{management_octet}/24",
        asus_wired_cidr=f"192.168.50.{asus_octet}/24",
        asus_gateway=ASUS_GATEWAY,
        asus_ssid=ASUS_SSID,
        tplink_ssids=TPLINK_SSIDS,
        wired_profile=WIRED_PROFILE,
        asus_profile=ASUS_PROFILE,
        tplink_profile=TPLINK_PROFILE,
        wired_metric=WIRED_METRIC,
        asus_metric=ASUS_METRIC,
        tplink_metric=TPLINK_METRIC,
        asus_psk_file=asus_psk_file,
    ))


def plan_to_json(plan: UplinkPlan) -> str:
    payload = asdict(plan)
    payload["format"] = "ds4-spark-uplink-v1"
    payload["tplink_ssids"] = list(plan.tplink_ssids)
    return(json.dumps(payload,indent=2,sort_keys=True) + "\n")


def load_plan(path: Path) -> UplinkPlan:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as error:
        raise UplinkError(f"cannot read uplink config {path}: {error}") from error
    if payload.pop("format","") != "ds4-spark-uplink-v1":
        raise UplinkError(f"unsupported uplink config format: {path}")
    payload["tplink_ssids"] = tuple(payload["tplink_ssids"])
    try:
        return(UplinkPlan(**payload))
    except (KeyError,TypeError) as error:
        raise UplinkError(f"invalid uplink config {path}: {error}") from error


def require_root() -> None:
    if os.geteuid() != 0:
        raise UplinkError("this command must run as root")


def connection_uuid(runner: Runner,name: str) -> str:
    result = runner.run([
        "nmcli","-g","connection.uuid","con","show","id",name,
    ],check=False)
    if result.returncode != 0:
        return("")
    values = [item.strip() for item in result.stdout.splitlines() if item.strip()]
    if len(values) > 1:
        raise UplinkError(f"connection id is ambiguous: {name}")
    return(values[0] if values else "")


def connection_field(runner: Runner,uuid: str,field: str) -> str:
    result = runner.run(["nmcli","-g",field,"con","show","uuid",uuid])
    return(result.stdout.strip())


def listed_connections(runner: Runner) -> list[tuple[str,str,str]]:
    result = runner.run(["nmcli","-t","--escape","no","-f","NAME,UUID,TYPE","con","show"])
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split(":",2)
        if len(parts) == 3:
            rows.append((parts[0],parts[1],parts[2]))
    return(rows)


def ensure_wired_profile(runner: Runner,plan: UplinkPlan) -> str:
    uuid = connection_uuid(runner,plan.wired_profile)
    if uuid == "":
        runner.run([
            "nmcli","con","add","type","ethernet",
            "ifname",plan.wired_interface,"con-name",plan.wired_profile,
        ])
        uuid = connection_uuid(runner,plan.wired_profile)
    addresses = f"{plan.management_cidr},{plan.asus_wired_cidr}"
    runner.run([
        "nmcli","con","mod","uuid",uuid,
        "connection.interface-name",plan.wired_interface,
        "connection.autoconnect","yes",
        "connection.autoconnect-priority","300",
        "ipv4.method","manual",
        "ipv4.addresses",addresses,
        "ipv4.gateway",plan.asus_gateway,
        "ipv4.dns",f"{plan.asus_gateway},1.1.1.1",
        "ipv4.ignore-auto-routes","yes",
        "ipv4.ignore-auto-dns","yes",
        "ipv4.never-default","no",
        "ipv4.route-metric",str(plan.wired_metric),
        "ipv6.method","disabled",
    ])
    return(uuid)


def ensure_asus_profile(runner: Runner,plan: UplinkPlan,psk: str) -> str:
    uuid = connection_uuid(runner,plan.asus_profile)
    if uuid == "":
        runner.run([
            "nmcli","con","add","type","wifi",
            "ifname",plan.wifi_interface,"con-name",plan.asus_profile,
            "ssid",plan.asus_ssid,
        ])
        uuid = connection_uuid(runner,plan.asus_profile)
    runner.run([
        "nmcli","con","mod","uuid",uuid,
        "connection.interface-name",plan.wifi_interface,
        "connection.autoconnect","yes",
        "connection.autoconnect-priority","200",
        "802-11-wireless.ssid",plan.asus_ssid,
        "802-11-wireless.powersave","2",
        "802-11-wireless-security.key-mgmt","wpa-psk",
        "802-11-wireless-security.psk",psk,
        "ipv4.method","auto",
        "ipv4.never-default","no",
        "ipv4.route-metric",str(plan.asus_metric),
        "ipv6.method","auto",
        "ipv6.route-metric",str(plan.asus_metric),
    ])
    return(uuid)


def find_tplink_profile(runner: Runner,plan: UplinkPlan) -> str:
    canonical = connection_uuid(runner,plan.tplink_profile)
    if canonical != "":
        return(canonical)
    matches = []
    for _,uuid,kind in listed_connections(runner):
        if kind != "802-11-wireless":
            continue
        ssid = connection_field(runner,uuid,"802-11-wireless.ssid")
        if ssid in plan.tplink_ssids:
            matches.append((plan.tplink_ssids.index(ssid),uuid))
    if not matches:
        raise UplinkError("no saved TP-Link_D660 WiFi profile; refusing incomplete fallback setup")
    matches.sort()
    return(matches[0][1])


def ensure_tplink_profile(runner: Runner,plan: UplinkPlan) -> str:
    uuid = find_tplink_profile(runner,plan)
    runner.run([
        "nmcli","con","mod","uuid",uuid,
        "connection.id",plan.tplink_profile,
        "connection.interface-name",plan.wifi_interface,
        "connection.autoconnect","yes",
        "connection.autoconnect-priority","100",
        "802-11-wireless.powersave","2",
        "ipv4.never-default","no",
        "ipv4.route-metric",str(plan.tplink_metric),
        "ipv6.route-metric",str(plan.tplink_metric),
    ])
    return(uuid)


def read_psk(path: Path) -> str:
    try:
        psk = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise UplinkError(f"cannot read ASUS PSK file {path}: {error}") from error
    if len(psk) < 8 or len(psk) > 63:
        raise UplinkError("ASUS PSK must contain 8 to 63 characters")
    return(psk)


def current_wifi_profile(runner: Runner,plan: UplinkPlan) -> str:
    result = runner.run([
        "nmcli","-g","GENERAL.CONNECTION","device","show",plan.wifi_interface,
    ],check=False)
    return(result.stdout.strip() if result.returncode == 0 else "")


def wifi_profile_ready(runner: Runner,plan: UplinkPlan,profile: str) -> bool:
    if current_wifi_profile(runner,plan) != profile:
        return(False)
    result = runner.run([
        "nmcli","-g","GENERAL.STATE","device","show",plan.wifi_interface,
    ],check=False)
    if result.returncode != 0:
        return(False)
    return(result.stdout.strip().split(" ",1)[0] == "100")


def wait_for_wifi_profile(
    runner: Runner,
    plan: UplinkPlan,
    profile: str,
    timeout_seconds: int,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if wifi_profile_ready(runner,plan,profile):
            return(True)
        if time.monotonic() >= deadline:
            return(False)
        time.sleep(1)


def ensure_asus_active(runner: Runner,plan: UplinkPlan,asus_uuid: str) -> None:
    if current_wifi_profile(runner,plan) == plan.asus_profile:
        if wait_for_wifi_profile(runner,plan,plan.asus_profile,WIFI_ACTIVATION_SECONDS):
            return
        raise UplinkError("ASUS WiFi did not reach connected state")
    result = runner.run([
        "nmcli","--wait",str(WIFI_ACTIVATION_SECONDS),
        "con","up","uuid",asus_uuid,"ifname",plan.wifi_interface,
    ],check=False,timeout=WIFI_ACTIVATION_SECONDS + 10)
    if wait_for_wifi_profile(runner,plan,plan.asus_profile,10):
        return
    detail = result.stderr.strip() or result.stdout.strip()
    raise UplinkError(f"ASUS WiFi activation failed: {detail or 'not connected'}")


def apply_profiles(runner: Runner,plan: UplinkPlan) -> None:
    require_root()
    for interface in (plan.wired_interface,plan.wifi_interface):
        if not Path(f"/sys/class/net/{interface}").exists():
            raise UplinkError(f"required interface is missing: {interface}")
    psk = read_psk(Path(plan.asus_psk_file))
    wired_uuid = ensure_wired_profile(runner,plan)
    asus_uuid = ensure_asus_profile(runner,plan,psk)
    tplink_uuid = ensure_tplink_profile(runner,plan)
    runner.run(["nmcli","--wait","15","con","up","uuid",wired_uuid,"ifname",plan.wired_interface])
    ensure_asus_active(runner,plan,asus_uuid)
    print(
        f"uplink_profiles_ready node={plan.node_id} wired={wired_uuid} "
        f"asus={asus_uuid} tplink={tplink_uuid}"
    )


def interface_probe(runner: Runner,interface: str) -> bool:
    result = runner.run([
        "curl","-4","--interface",interface,
        "--connect-timeout","2","--max-time","5",
        "--silent","--show-error","--fail","--output","/dev/null",
        PROBE_URL,
    ],check=False,timeout=7)
    return(result.returncode == 0)


def wired_probe(runner: Runner,plan: UplinkPlan) -> bool:
    carrier_path = Path(f"/sys/class/net/{plan.wired_interface}/carrier")
    try:
        if carrier_path.read_text(encoding="ascii").strip() != "1":
            return(False)
    except OSError:
        return(False)
    runner.run([
        "ip","route","replace",f"{PROBE_ADDRESS}/32",
        "via",plan.asus_gateway,"dev",plan.wired_interface,
        "src",plan.asus_wired_address,"metric","5",
    ],check=False)
    try:
        return(interface_probe(runner,plan.wired_interface))
    finally:
        runner.run([
            "ip","route","del",f"{PROBE_ADDRESS}/32",
            "via",plan.asus_gateway,"dev",plan.wired_interface,
            "src",plan.asus_wired_address,"metric","5",
        ],check=False)


def set_wired_default(runner: Runner,plan: UplinkPlan,enabled: bool) -> None:
    if enabled:
        runner.run([
            "ip","route","replace","default",
            "via",plan.asus_gateway,"dev",plan.wired_interface,
            "src",plan.asus_wired_address,"metric",str(plan.wired_metric),
        ])
    else:
        runner.run([
            "ip","route","del","default",
            "via",plan.asus_gateway,"dev",plan.wired_interface,
            "metric",str(plan.wired_metric),
        ],check=False)


def activate_wifi(runner: Runner,plan: UplinkPlan,profile: str) -> bool:
    uuid = connection_uuid(runner,profile)
    if uuid == "":
        return(False)
    result = runner.run([
        "nmcli","--wait","12","con","up","uuid",uuid,
        "ifname",plan.wifi_interface,
    ],check=False,timeout=20)
    return(result.returncode == 0)


def asus_retry_due(state_dir: Path,now: int) -> bool:
    retry_path = state_dir / "asus_retry_after"
    try:
        retry_after = int(retry_path.read_text(encoding="ascii").strip())
    except (OSError,ValueError):
        return(True)
    return(now >= retry_after)


def defer_asus_retry(state_dir: Path,now: int) -> None:
    (state_dir / "asus_retry_after").write_text(
        f"{now + ASUS_RETRY_SECONDS}\n",encoding="ascii"
    )


def record_path(state_dir: Path,path: str,reason: str) -> None:
    path_file = state_dir / "path"
    try:
        previous = path_file.read_text(encoding="ascii").strip()
    except OSError:
        previous = "unknown"
    if previous != path:
        print(f"uplink_transition from={previous} to={path} reason={reason}")
    else:
        print(f"uplink_state path={path} reason={reason}")
    path_file.write_text(f"{path}\n",encoding="ascii")


def ensure_asus_standby(runner: Runner,plan: UplinkPlan,state_dir: Path,now: int) -> None:
    if current_wifi_profile(runner,plan) == plan.asus_profile:
        return
    if not asus_retry_due(state_dir,now):
        return
    if not activate_wifi(runner,plan,plan.asus_profile):
        defer_asus_retry(state_dir,now)
        print("uplink_warning path=wired asus_standby=activation_failed")


def monitor_uplink(runner: Runner,plan: UplinkPlan,state_dir: Path) -> None:
    require_root()
    state_dir.mkdir(parents=True,exist_ok=True)
    lock_path = state_dir / "lock"
    with lock_path.open("a+",encoding="ascii") as lock_handle:
        fcntl.flock(lock_handle.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = int(time.time())
        if wired_probe(runner,plan):
            set_wired_default(runner,plan,True)
            ensure_asus_standby(runner,plan,state_dir,now)
            record_path(state_dir,"wired","wired_internet_ok")
            return
        set_wired_default(runner,plan,False)
        if current_wifi_profile(runner,plan) == plan.asus_profile:
            if interface_probe(runner,plan.wifi_interface):
                record_path(state_dir,"asus_wifi","wired_failed_asus_ok")
                return
            defer_asus_retry(state_dir,now)
        elif asus_retry_due(state_dir,now):
            if activate_wifi(runner,plan,plan.asus_profile):
                if interface_probe(runner,plan.wifi_interface):
                    record_path(state_dir,"asus_wifi","wired_failed_asus_ok")
                    return
            defer_asus_retry(state_dir,now)
        if activate_wifi(runner,plan,plan.tplink_profile):
            if interface_probe(runner,plan.wifi_interface):
                record_path(state_dir,"tplink_wifi","wired_and_asus_failed")
                return
        record_path(state_dir,"failed","no_healthy_uplink")
        raise UplinkError("wired, ASUS WiFi, and TP-Link WiFi probes all failed")


def audit(runner: Runner,plan: UplinkPlan) -> None:
    print(f"node={plan.node_id} rank={plan.rank}")
    print(f"expected_management={plan.management_cidr}")
    print(f"expected_asus_wired={plan.asus_wired_cidr}")
    for command,label in (
        (["ip","-o","-4","addr","show","dev",plan.wired_interface],"wired_addresses"),
        (["ip","-4","route","show","default"],"defaults"),
        (["nmcli","-t","-f","NAME,TYPE,DEVICE","con","show","--active"],"active"),
    ):
        result = runner.run(command,check=False)
        value = "|".join(line.strip() for line in result.stdout.splitlines() if line.strip())
        print(f"{label}={value}")
    for profile in (plan.wired_profile,plan.asus_profile,plan.tplink_profile):
        uuid = connection_uuid(runner,profile)
        print(f"profile_{profile}={uuid or 'missing'}")


def write_plan(plan: UplinkPlan,output: Path | None) -> None:
    content = plan_to_json(plan)
    if output is None:
        print(content,end="")
        return
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(content,encoding="utf-8")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir",type=Path,default=DEFAULT_STATE_DIR)
    subparsers = parser.add_subparsers(dest="command",required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--node-id",required=True)
    plan_parser.add_argument("--asus-psk-file",default="/etc/ds4-uplink/asus.psk")
    plan_parser.add_argument("--output",type=Path)
    subparsers.add_parser("apply")
    subparsers.add_parser("monitor")
    subparsers.add_parser("audit")
    return(parser.parse_args(argv))


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    runner = Runner()
    try:
        if arguments.command == "plan":
            write_plan(
                plan_for_node(arguments.node_id,arguments.asus_psk_file),
                arguments.output,
            )
            return(0)
        plan = load_plan(arguments.config)
        if arguments.command == "apply":
            apply_profiles(runner,plan)
        elif arguments.command == "monitor":
            monitor_uplink(runner,plan,arguments.state_dir)
        elif arguments.command == "audit":
            audit(runner,plan)
        return(0)
    except (OSError,subprocess.TimeoutExpired,UplinkError,BlockingIOError) as error:
        print(f"ds4_spark_uplink: {error}",file=sys.stderr)
        return(1)


if __name__ == "__main__":
    raise SystemExit(main())
