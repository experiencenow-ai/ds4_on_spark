#!/usr/bin/env python3
"""Apply and audit the canonical Spark anti-brick boot and OOM policy."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NODES = ("spark0","spark2","spark3","spark4","spark5","spark6","spark7")
DEFAULT_SPARKPIPE_REPO = Path.home() / "sparkpipe"
DEFAULT_RECOVERY_IDENTITY = Path.home() / ".ssh" / "sparkpipe_fleet_root"
REMOTE_SCRIPT = "/tmp/ds4-spark-brickproof.py"
REMOTE_PAYLOAD = "/tmp/ds4-spark-brickproof.json"
SWAP_FILES = (("/swap.img",16), ("/swap-extra-16g.img",16), ("/swap-extra-32g.img",32))
ASSET_SOURCES = {
    "/etc/systemd/system/sparkpipe_model_residentd.service": ("tools/devcycle/sparkpipe_model_residentd.service",0o644),
    "/usr/local/bin/sparkpipe_fsck_health.sh": ("tools/devcycle/sparkpipe_fsck_health.sh",0o755),
    "/etc/systemd/system/sparkpipe-fsck-health.service": ("tools/devcycle/sparkpipe-fsck-health.service",0o644),
}
BOOT_TIMEOUT_SOURCES = {
    "ceph-b52b3459-74b2-428d-b944-1bb691b263c7@.service": "ceph-b52b3459-74b2-428d-b944-1bb691b263c7@.service.conf",
    "rbdmap.service": "rbdmap.service.conf",
    "nvmf-autoconnect.service": "nvmf-autoconnect.service.conf",
    "open-iscsi.service": "open-iscsi.service.conf",
    "pollinate.service": "pollinate.service.conf",
}
LOCAL_ASSET_SOURCES = {
    "/etc/systemd/system/ds4-switched-fabric.service": ("deploy/systemd/ds4-switched-fabric.service",0o644),
    "/etc/systemd/system/ds4-switched-fabric.timer": ("deploy/systemd/ds4-switched-fabric.timer",0o644),
    "/etc/systemd/system/ds4-direct-pair-fabric.service": ("deploy/systemd/ds4-direct-pair-fabric.service",0o644),
    "/etc/systemd/system/ds4-direct-pair-fabric.timer": ("deploy/systemd/ds4-direct-pair-fabric.timer",0o644),
    "/usr/local/sbin/ds4-switched-fabric-apply": ("scripts/ds4_switched_fabric_apply.sh",0o755),
    "/usr/local/sbin/ds4-direct-pair-fabric-apply": ("scripts/ds4_direct_pair_fabric_apply.sh",0o755),
    "/etc/systemd/system/ds4-optional-storage.service": ("deploy/systemd/ds4-optional-storage.service",0o644),
    "/etc/systemd/system/ds4-optional-storage.timer": ("deploy/systemd/ds4-optional-storage.timer",0o644),
    "/etc/systemd/system/sparkpipe-fsck-health.timer": ("deploy/systemd/sparkpipe-fsck-health.timer",0o644),
    "/etc/systemd/system/spark-firewall.service.d/10-ds4-timeout.conf": ("deploy/systemd/spark-firewall-timeout.conf",0o644),
}
USER_SLICE = """[Slice]
MemoryHigh=100G
MemoryMax=108G
MemorySwapMax=0
"""
EARLYOOM_DEFAULT = 'EARLYOOM_ARGS="-m 7 -s 25 -r 5 --avoid sshd|systemd|init"\n'
NO_THRASH_SYSCTL = "vm.swappiness=10\n"
RECOVERY_SYSCTL = """kernel.panic=60
kernel.softlockup_panic=1
kernel.hung_task_panic=1
"""
SYSTEMD_RECOVERY = """[Manager]
RuntimeWatchdogSec=10min
RebootWatchdogSec=5min
"""
EMERGENCY_SSH_CONFIG = """Port 2222
Protocol 2
ListenAddress 0.0.0.0
UsePAM no
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
AllowUsers root
PidFile /run/sshd-spark-emergency.pid
PrintMotd no
UseDNS no
"""
EMERGENCY_SSH_SERVICE = """[Unit]
Description=Spark emergency public-key SSH on port 2222
After=network.target
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/sbin/sshd -D -e -f /etc/ssh/sshd_config_spark_emergency
Restart=always
RestartSec=2s

[Install]
WantedBy=multi-user.target
"""


class BrickproofError(RuntimeError):
    pass


def run(argv: list[str],input_bytes: bytes | None = None,timeout: int = 120,check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(argv,input=input_bytes,capture_output=True,timeout=timeout)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8",errors="replace").strip()
        raise BrickproofError(f"command failed ({result.returncode}): {' '.join(argv)}: {detail}")
    return(result)


def command(argv: list[str],timeout: int = 120,check: bool = True) -> str:
    return(run(argv,timeout=timeout,check=check).stdout.decode("utf-8",errors="replace").strip())


def atomic_write(path: Path,data: str,mode: int) -> bool:
    encoded = data.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded and (path.stat().st_mode & 0o777) == mode:
        return(False)
    path.parent.mkdir(parents=True,exist_ok=True)
    handle,temp_name = tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
    try:
        with os.fdopen(handle,"wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp_name,mode)
        os.replace(temp_name,path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return(True)


def shell_assignment(text: str,name: str) -> str:
    match = re.search(rf"^[ \t]*{re.escape(name)}[ \t]*=(.*)$",text,re.MULTILINE)
    if match is None:
        return("")
    values = shlex.split(match.group(1),comments=False,posix=True)
    return(values[0] if values else "")


def set_shell_assignment(text: str,name: str,value: str) -> str:
    line = f"{name}={shlex.quote(value)}"
    pattern = re.compile(rf"^[ \t]*{re.escape(name)}[ \t]*=.*$",re.MULTILINE)
    if pattern.search(text) is not None:
        return(pattern.sub(line,text,count=1))
    suffix = "" if text.endswith("\n") else "\n"
    return(f"{text}{suffix}{line}\n")


def canonical_grub(text: str) -> str:
    cmdline = shell_assignment(text,"GRUB_CMDLINE_LINUX_DEFAULT")
    tokens = shlex.split(cmdline)
    if not any(token.startswith("ip=") for token in tokens):
        raise BrickproofError("GRUB_CMDLINE_LINUX_DEFAULT has no static initramfs ip= argument")
    if not any(token.startswith("console=ttyS0") for token in tokens):
        raise BrickproofError("GRUB_CMDLINE_LINUX_DEFAULT has no serial console argument")
    tokens = [token for token in tokens if not token.startswith("fsck.mode=") and not token.startswith("fsck.repair=")]
    tokens.extend(("fsck.mode=skip","fsck.repair=no"))
    text = set_shell_assignment(text,"GRUB_CMDLINE_LINUX_DEFAULT",shlex.join(tokens))
    return(set_shell_assignment(text,"GRUB_DEFAULT","0"))


def merge_public_key(text: str,public_key: str) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    fingerprint = " ".join(public_key.strip().split()[:2])
    if not any(" ".join(line.split()[:2]) == fingerprint for line in lines):
        lines.append(public_key.strip())
    return("\n".join(lines) + "\n")


def package_installed(name: str) -> bool:
    result = run(["dpkg-query","-W","-f=${Status}",name],check=False)
    return(result.returncode == 0 and b"install ok installed" in result.stdout)


def install_packages() -> None:
    missing = [name for name in ("earlyoom","dropbear-initramfs") if not package_installed(name)]
    if missing:
        run(["apt-get","install","-y",*missing],timeout=600)


def ensure_swap_file(path_text: str,size_gib: int) -> None:
    path = Path(path_text)
    expected = size_gib * 1024 * 1024 * 1024
    active = {line.split()[0] for line in Path("/proc/swaps").read_text().splitlines()[1:]}
    if path.exists() and path.stat().st_size != expected:
        raise BrickproofError(f"{path} has {path.stat().st_size} bytes, expected {expected}")
    if not path.exists():
        run(["fallocate","-l",f"{size_gib}G",path_text],timeout=600)
        os.chmod(path,0o600)
        run(["mkswap",path_text],timeout=120)
    elif path_text not in active:
        os.chmod(path,0o600)
        run(["mkswap",path_text],timeout=120)
    if path_text not in active:
        run(["swapon",path_text],timeout=120)


def ensure_swap() -> None:
    for path,size_gib in SWAP_FILES:
        ensure_swap_file(path,size_gib)
    fstab_path = Path("/etc/fstab")
    fstab = fstab_path.read_text()
    fields = {line.split()[0] for line in fstab.splitlines() if line.strip() and not line.lstrip().startswith("#")}
    additions = [f"{path} none swap sw 0 0" for path,_ in SWAP_FILES if path not in fields]
    if additions:
        suffix = "" if fstab.endswith("\n") else "\n"
        atomic_write(fstab_path,f"{fstab}{suffix}" + "\n".join(additions) + "\n",0o644)


def install_sshd_config() -> None:
    target = Path("/etc/ssh/sshd_config_spark_emergency")
    handle,temp_name = tempfile.mkstemp(prefix="sshd-spark-emergency.",dir="/etc/ssh")
    try:
        with os.fdopen(handle,"w",encoding="utf-8") as output:
            output.write(EMERGENCY_SSH_CONFIG)
        os.chmod(temp_name,0o644)
        run(["/usr/sbin/sshd","-t","-f",temp_name])
        os.replace(temp_name,target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def install_recovery_keys(public_key: str) -> bool:
    changed = False
    root_keys = Path("/root/.ssh/authorized_keys")
    root_keys.parent.mkdir(parents=True,exist_ok=True)
    root_text = root_keys.read_text() if root_keys.exists() else ""
    changed |= atomic_write(root_keys,merge_public_key(root_text,public_key),0o600)
    os.chmod(root_keys.parent,0o700)
    dropbear_keys = Path("/etc/dropbear/initramfs/authorized_keys")
    dropbear_keys.parent.mkdir(parents=True,exist_ok=True)
    dropbear_text = dropbear_keys.read_text() if dropbear_keys.exists() else ""
    changed |= atomic_write(dropbear_keys,merge_public_key(dropbear_text,public_key),0o600)
    return(changed)


def install_assets(payload: dict[str,object]) -> bool:
    changed = False
    assets = payload["assets"]
    if not isinstance(assets,dict):
        raise BrickproofError("payload assets are invalid")
    for path_text,specification in assets.items():
        if not isinstance(specification,dict):
            raise BrickproofError(f"invalid asset specification for {path_text}")
        changed |= atomic_write(Path(path_text),str(specification["text"]),int(specification["mode"]))
    return(changed)


def install_grub_policy() -> bool:
    path = Path("/etc/default/grub")
    before = path.read_text()
    changed = atomic_write(path,canonical_grub(before),0o644)
    legacy = Path("/etc/grub.d/40_ds4_fastboot")
    if legacy.exists():
        legacy.unlink()
        changed = True
    if changed:
        run(["update-grub"],timeout=300)
    return(changed)


def enable_policy_services() -> None:
    run(["systemctl","daemon-reload"])
    run(["sysctl","--system"],timeout=180)
    run(["systemctl","enable","earlyoom.service"])
    run(["systemctl","restart","earlyoom.service"])
    run(["systemctl","enable","--now","ssh-emergency.service"])
    run(["systemctl","disable","sparkpipe-fsck-health.service"],check=False)
    run(["systemctl","enable","--now","sparkpipe-fsck-health.timer"])
    run(["systemctl","enable","serial-getty@ttyS0.service"])
    run(["systemctl","disable","ds4-switched-fabric.service"],check=False)
    run(["systemctl","disable","ds4-direct-pair-fabric.service"],check=False)
    run(["systemctl","enable","--now","ds4-switched-fabric.timer"])
    run(["systemctl","enable","--now","ds4-direct-pair-fabric.timer"])
    run(["systemctl","disable","sparkpipe_model_residentd.service"],check=False)
    run(["systemctl","reset-failed","sparkpipe_model_residentd.service"],check=False)
    run(["systemctl","enable","--now","ds4-optional-storage.timer"])
    run(["systemctl","set-default","multi-user.target"])
    run(["systemctl","set-property","--runtime","user-1000.slice","MemoryHigh=100G","MemoryMax=108G","MemorySwapMax=0"])


def has_configured_remote_storage() -> list[str]:
    configured = []
    rbdmap = read_optional(Path("/etc/ceph/rbdmap"))
    if any(line.strip() and not line.lstrip().startswith("#") for line in rbdmap.splitlines()):
        configured.append("rbdmap")
    fstab = read_optional(Path("/etc/fstab"))
    for line in fstab.splitlines():
        fields = line.split()
        if line.strip() and not line.lstrip().startswith("#") and len(fields) >= 4:
            if fields[2] in ("nfs","nfs4","cifs","ceph") or "_netdev" in fields[3].split(","):
                configured.append("remote-fstab")
    iscsi = Path("/etc/iscsi/nodes")
    if iscsi.exists() and any(path.is_file() for path in iscsi.rglob("*")):
        configured.append("iscsi")
    discovery = read_optional(Path("/etc/nvme/discovery.conf"))
    if any(line.strip() and not line.lstrip().startswith("#") for line in discovery.splitlines()):
        configured.append("nvme-of")
    return(sorted(set(configured)))


def decouple_optional_boot_work() -> None:
    configured = has_configured_remote_storage()
    if configured:
        raise BrickproofError(f"remote storage configuration exists; refusing to mask initiators: {configured}")
    ceph_targets = command(["systemctl","list-unit-files","--type=target","--no-legend","ceph*.target"],check=False)
    for row in ceph_targets.splitlines():
        unit = row.split()[0] if row.split() else ""
        if unit:
            run(["systemctl","disable",unit],check=False)
    for unit in ("rbdmap.service","nvmf-autoconnect.service","open-iscsi.service","iscsid.service","srp_daemon.service"):
        run(["systemctl","disable",unit],check=False)
        run(["systemctl","mask",unit],check=False)
    for unit in ("cloud-init.service","cloud-init-local.service","cloud-config.service","cloud-final.service","pollinate.service","nvidia-spark-run-apt-upgrade-once.service","systemd-networkd-wait-online.service"):
        run(["systemctl","disable",unit],check=False)
        run(["systemctl","mask",unit],check=False)
    atomic_write(Path("/etc/cloud/cloud-init.disabled"),"commissioned by ds4_spark_brickproof\n",0o644)


def remote_apply(payload_path: Path) -> dict[str,object]:
    if os.geteuid() != 0:
        raise BrickproofError("remote apply must run as root")
    payload = json.loads(payload_path.read_text())
    memory_current = int(command(["systemctl","show","user-1000.slice","-p","MemoryCurrent","--value"]) or "0")
    if memory_current >= 108 * 1024 * 1024 * 1024:
        raise BrickproofError(f"user-1000.slice already uses {memory_current} bytes; refusing a 108G cap")
    install_packages()
    ensure_swap()
    install_assets(payload)
    atomic_write(Path("/etc/systemd/system/user-1000.slice.d/20-ds4-brickproof.conf"),USER_SLICE,0o644)
    atomic_write(Path("/etc/default/earlyoom"),EARLYOOM_DEFAULT,0o644)
    atomic_write(Path("/etc/sysctl.d/90-sparkpipe-no-thrash.conf"),NO_THRASH_SYSCTL,0o644)
    atomic_write(Path("/etc/sysctl.d/99-spark-recovery.conf"),RECOVERY_SYSCTL,0o644)
    atomic_write(Path("/etc/systemd/system.conf.d/90-ds4-recovery.conf"),SYSTEMD_RECOVERY,0o644)
    install_sshd_config()
    atomic_write(Path("/etc/systemd/system/ssh-emergency.service"),EMERGENCY_SSH_SERVICE,0o644)
    obsolete = Path("/etc/systemd/system/sparkpipe_model_residentd.service.d/10-oom-guardrails.conf")
    if obsolete.exists():
        obsolete.unlink()
    for unit in ("ds4-switched-fabric.service","ds4-direct-pair-fabric.service"):
        legacy_timeout = Path(f"/etc/systemd/system/{unit}.d/10-boot-timeout.conf")
        if legacy_timeout.exists():
            legacy_timeout.unlink()
    keys_changed = install_recovery_keys(str(payload["fleet_public_key"]))
    grub_changed = install_grub_policy()
    if keys_changed:
        run(["update-initramfs","-u"],timeout=600)
    decouple_optional_boot_work()
    enable_policy_services()
    return({"grub_changed":grub_changed,"keys_changed":keys_changed,"memory_current_before":memory_current,"source_commit":payload["source_commit"]})


def read_optional(path: Path) -> str:
    try:
        return(path.read_text())
    except (FileNotFoundError,PermissionError):
        return("")


def service_value(unit: str,property_name: str) -> str:
    return(command(["systemctl","show",unit,"-p",property_name,"--value"],check=False))


def is_enabled(unit: str) -> str:
    return(command(["systemctl","is-enabled",unit],check=False))


def remote_audit(payload_path: Path) -> dict[str,object]:
    payload = json.loads(payload_path.read_text())
    public_key = str(payload["fleet_public_key"])
    failures = []
    observations: dict[str,object] = {}
    swaps = Path("/proc/swaps").read_text()
    swap_bytes = sum(int(line.split()[2]) * 1024 for line in swaps.splitlines()[1:] if len(line.split()) >= 3)
    observations["swap_bytes"] = swap_bytes
    if swap_bytes < 63 * 1024 * 1024 * 1024:
        failures.append("swap<63GiB")
    observations["swappiness"] = command(["sysctl","-n","vm.swappiness"],check=False)
    observations["panic"] = command(["sysctl","-n","kernel.panic"],check=False)
    observations["earlyoom_process"] = command(["pgrep","-af","earlyoom"],check=False)
    if "-m 7 -s 25 -r 5" not in str(observations["earlyoom_process"]):
        failures.append("earlyoom-runtime-args")
    for unit in ("earlyoom.service","ssh-emergency.service"):
        state = service_value(unit,"ActiveState")
        observations[f"{unit}.active"] = state
        if state != "active":
            failures.append(f"{unit}:{state}")
    for unit in ("serial-getty@ttyS0.service","sparkpipe-fsck-health.timer","ds4-switched-fabric.timer","ds4-direct-pair-fabric.timer","ds4-optional-storage.timer"):
        state = is_enabled(unit)
        observations[f"{unit}.enabled"] = state
        if state != "enabled":
            failures.append(f"{unit}:not-enabled")
    for unit in ("ds4-switched-fabric.service","ds4-direct-pair-fabric.service","sparkpipe-fsck-health.service","sparkpipe_model_residentd.service"):
        state = is_enabled(unit)
        observations[f"{unit}.enabled"] = state
        if state not in ("disabled","static"):
            failures.append(f"boot-critical-link:{unit}={state}")
    for unit in ("rbdmap.service","nvmf-autoconnect.service","open-iscsi.service","iscsid.service","srp_daemon.service","cloud-init.service","cloud-init-local.service","cloud-config.service","cloud-final.service","pollinate.service","nvidia-spark-run-apt-upgrade-once.service","systemd-networkd-wait-online.service"):
        state = is_enabled(unit)
        observations[f"{unit}.enabled"] = state
        if state != "masked":
            failures.append(f"optional-boot-unit:{unit}={state}")
    for unit in ("ds4-switched-fabric.service","ds4-direct-pair-fabric.service"):
        before = service_value(unit,"Before")
        timeout = service_value(unit,"TimeoutStartUSec")
        observations[f"{unit}.before"] = before
        observations[f"{unit}.timeout"] = timeout
        if "network-online.target" in before or "multi-user.target" in before:
            failures.append(f"fabric-boot-order:{unit}")
        if timeout not in ("1min","60s"):
            failures.append(f"fabric-timeout:{unit}={timeout}")
    firewall_timeout = service_value("spark-firewall.service","TimeoutStartUSec")
    observations["spark-firewall.timeout"] = firewall_timeout
    if firewall_timeout not in ("15s","15sec"):
        failures.append(f"spark-firewall-timeout={firewall_timeout}")
    expected_limits = {"MemoryHigh":str(100 * 1024**3),"MemoryMax":str(108 * 1024**3),"MemorySwapMax":"0"}
    for unit in ("user-1000.slice","sparkpipe_model_residentd.service"):
        for property_name,expected in expected_limits.items():
            value = service_value(unit,property_name)
            observations[f"{unit}.{property_name}"] = value
            if value != expected:
                failures.append(f"{unit}.{property_name}={value}")
    watchdog = service_value("sparkpipe_model_residentd.service","WatchdogUSec")
    observations["resident_watchdog"] = watchdog
    if watchdog not in ("0","0us","infinity"):
        failures.append(f"resident-watchdog={watchdog}")
    if Path("/etc/systemd/system/sparkpipe_model_residentd.service.d/10-oom-guardrails.conf").exists():
        failures.append("obsolete-resident-dropin")
    key_id = " ".join(public_key.split()[:2])
    for path in (Path("/root/.ssh/authorized_keys"),Path("/etc/dropbear/initramfs/authorized_keys")):
        present = any(" ".join(line.split()[:2]) == key_id for line in read_optional(path).splitlines())
        observations[f"key:{path}"] = present
        if not present:
            failures.append(f"missing-key:{path}")
    grub = read_optional(Path("/etc/default/grub"))
    cmdline = shell_assignment(grub,"GRUB_CMDLINE_LINUX_DEFAULT")
    observations["grub_default"] = shell_assignment(grub,"GRUB_DEFAULT")
    observations["grub_cmdline"] = cmdline
    if shell_assignment(grub,"GRUB_DEFAULT") != "0":
        failures.append("grub-default")
    for token in ("fsck.mode=skip","fsck.repair=no"):
        if token not in shlex.split(cmdline):
            failures.append(f"grub-missing:{token}")
    if not any(token.startswith("ip=") for token in shlex.split(cmdline)):
        failures.append("grub-missing:ip")
    if not any(token.startswith("console=ttyS0") for token in shlex.split(cmdline)):
        failures.append("grub-missing:serial")
    if Path("/etc/grub.d/40_ds4_fastboot").exists():
        failures.append("legacy-fastboot-entry")
    listeners = command(["ss","-ltn"],check=False)
    if not re.search(r"(?:\*|0\.0\.0\.0):2222\b",listeners):
        failures.append("emergency-port-not-listening")
    root_options = command(["findmnt","-n","-o","OPTIONS","/"],check=False)
    observations["root_options"] = root_options
    if "rw" not in root_options.split(","):
        failures.append("root-read-only")
    observations["hostname"] = command(["hostname","-s"],check=False)
    observations["kernel"] = command(["uname","-r"],check=False)
    observations["system_state"] = command(["systemctl","is-system-running"],check=False)
    health_path = Path("/var/lib/sparkpipe/fsck-health/last.json")
    if health_path.exists():
        try:
            observations["fsck_health"] = json.loads(health_path.read_text()).get("classification","unknown")
        except json.JSONDecodeError:
            failures.append("fsck-health-json")
    else:
        observations["fsck_health"] = "pending-next-boot"
    return({"failures":failures,"observations":observations,"source_commit":payload["source_commit"]})


def git_show(repo: Path,ref: str,path: str) -> str:
    return(command(["git","-C",str(repo),"show",f"{ref}:{path}"]))


def build_payload(repo: Path,ref: str) -> dict[str,object]:
    commit = command(["git","-C",str(repo),"rev-parse","--verify",ref])
    assets: dict[str,dict[str,object]] = {}
    for destination,(source,mode) in ASSET_SOURCES.items():
        assets[destination] = {"mode":mode,"text":git_show(repo,ref,source)}
        if not str(assets[destination]["text"]).endswith("\n"):
            assets[destination]["text"] = str(assets[destination]["text"]) + "\n"
    for unit,source_name in BOOT_TIMEOUT_SOURCES.items():
        destination = f"/etc/systemd/system/{unit}.d/10-boot-timeout.conf"
        source = f"tools/devcycle/boot-unblock/{source_name}"
        assets[destination] = {"mode":0o644,"text":git_show(repo,ref,source) + "\n"}
    for destination,(source,mode) in LOCAL_ASSET_SOURCES.items():
        text = (ROOT / source).read_text(encoding="utf-8")
        assets[destination] = {"mode":mode,"text":text if text.endswith("\n") else text + "\n"}
    public_key = git_show(repo,ref,"tools/devcycle/sparkpipe_fleet_root.pub").strip()
    if not public_key.startswith("ssh-ed25519 "):
        raise BrickproofError("fleet recovery key is not an Ed25519 public key")
    return({"assets":assets,"fleet_public_key":public_key,"source_commit":commit})


def ssh(host: str,*argv: str,input_bytes: bytes | None = None,timeout: int = 120,check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return(run(["ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=8",host,*argv],input_bytes=input_bytes,timeout=timeout,check=check))


def stage_remote(host: str,payload: dict[str,object]) -> None:
    script_data = Path(__file__).read_bytes()
    payload_data = (json.dumps(payload,sort_keys=True) + "\n").encode("utf-8")
    ssh(host,"tee",REMOTE_SCRIPT,input_bytes=script_data)
    ssh(host,"tee",REMOTE_PAYLOAD,input_bytes=payload_data)
    ssh(host,"chmod","0700",REMOTE_SCRIPT)
    ssh(host,"chmod","0600",REMOTE_PAYLOAD)


def remote_action(host: str,action: str,payload: dict[str,object]) -> dict[str,object]:
    stage_remote(host,payload)
    try:
        result = ssh(host,"sudo","-n","python3",REMOTE_SCRIPT,f"--remote-{action}",REMOTE_PAYLOAD,timeout=1200)
        document = json.loads(result.stdout.decode("utf-8"))
        document["node"] = host
        return(document)
    finally:
        ssh(host,"rm","-f",REMOTE_SCRIPT,REMOTE_PAYLOAD,check=False)


def emergency_probe(host: str,identity: Path) -> str:
    result = run(["ssh","-T","-p","2222","-i",str(identity),"-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","StrictHostKeyChecking=accept-new","-o","ConnectTimeout=8",f"root@{host}","true"],timeout=20,check=False)
    return("ok" if result.returncode == 0 else (result.stderr or result.stdout).decode("utf-8",errors="replace").strip())


def apply_one(host: str,payload: dict[str,object],identity: Path) -> dict[str,object]:
    applied = remote_action(host,"apply",payload)
    audited = remote_action(host,"audit",payload)
    audited["apply"] = applied
    audited["emergency_login"] = emergency_probe(host,identity)
    if audited["emergency_login"] != "ok":
        audited["failures"].append("controller-emergency-login")
    if audited["failures"]:
        raise BrickproofError(f"{host} failed post-apply audit: {json.dumps(audited,sort_keys=True)}")
    return(audited)


def write_receipt(action: str,documents: list[dict[str,object]]) -> Path:
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(tempfile.gettempdir()) / f"ds4_spark_brickproof_{action}_{timestamp}.json"
    path.write_text(json.dumps({"action":action,"nodes":documents},indent=2,sort_keys=True) + "\n")
    return(path)


def parse_nodes(value: str) -> tuple[str,...]:
    nodes = tuple(item.strip() for item in value.split(",") if item.strip())
    if not nodes:
        raise BrickproofError("at least one node is required")
    return(nodes)


def controller_main(args: argparse.Namespace) -> int:
    nodes = parse_nodes(args.nodes)
    payload = build_payload(args.sparkpipe_repo,args.source_ref)
    documents = []
    if args.action == "apply":
        if not args.recovery_identity.is_file():
            raise BrickproofError(f"missing recovery identity: {args.recovery_identity}")
        canary = args.canary if args.canary in nodes else nodes[0]
        print(f"canary={canary}",flush=True)
        documents.append(apply_one(canary,payload,args.recovery_identity))
        remaining = [node for node in nodes if node != canary]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.jobs,len(remaining) or 1)) as executor:
            futures = {executor.submit(apply_one,node,payload,args.recovery_identity):node for node in remaining}
            for future in concurrent.futures.as_completed(futures):
                document = future.result()
                documents.append(document)
                print(f"{document['node']}: PASS",flush=True)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.jobs,len(nodes))) as executor:
            futures = {executor.submit(remote_action,node,"audit",payload):node for node in nodes}
            for future in concurrent.futures.as_completed(futures):
                document = future.result()
                documents.append(document)
                print(f"{document['node']}: {'PASS' if not document['failures'] else 'FAIL'}",flush=True)
    documents.sort(key=lambda item:str(item["node"]))
    receipt = write_receipt(args.action,documents)
    print(f"receipt={receipt}")
    return(1 if any(document.get("failures") for document in documents) else 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",nargs="?",choices=("audit","apply"),default="audit")
    parser.add_argument("--nodes",default=",".join(DEFAULT_NODES))
    parser.add_argument("--canary",default="spark3")
    parser.add_argument("--jobs",type=int,default=3)
    parser.add_argument("--sparkpipe-repo",type=Path,default=DEFAULT_SPARKPIPE_REPO)
    parser.add_argument("--source-ref",default="origin/main")
    parser.add_argument("--recovery-identity",type=Path,default=DEFAULT_RECOVERY_IDENTITY)
    parser.add_argument("--remote-apply",type=Path,help=argparse.SUPPRESS)
    parser.add_argument("--remote-audit",type=Path,help=argparse.SUPPRESS)
    return(parser.parse_args())


def main() -> int:
    args = parse_args()
    if args.remote_apply is not None:
        print(json.dumps(remote_apply(args.remote_apply),sort_keys=True))
        return(0)
    if args.remote_audit is not None:
        print(json.dumps(remote_audit(args.remote_audit),sort_keys=True))
        return(0)
    return(controller_main(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BrickproofError,subprocess.TimeoutExpired,json.JSONDecodeError) as error:
        print(f"ds4_spark_brickproof: {error}",file=sys.stderr)
        raise SystemExit(1)
