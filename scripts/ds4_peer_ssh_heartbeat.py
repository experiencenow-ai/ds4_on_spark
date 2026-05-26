#!/usr/bin/env python3
"""Publish peer-observed SSH health records onto Spark nodes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


DEFAULT_PEERS = ",".join("spark%d" % i for i in range(8))
DEFAULT_REMOTE_DIR = ".ds4-rescue/peer-heartbeats"
DEFAULT_CONTROL_DIR = ".ds4-rescue/ssh-control"
DEFAULT_RESCUE_STATE_DIR = ".ds4-rescue/remote-rescue-state"


def safe_name(value: str) -> str:
    out = "".join(ch for ch in value if ch.isalnum() or ch in "-_")
    return(out or "unknown")


def run_cmd(argv: list[str], timeout: float, stdin: str | None = None) -> dict[str,Any]:
    start = time.time()
    try:
        cp = subprocess.run(argv,input=stdin,text=True,capture_output=True,timeout=timeout)
        return({
            "argv": argv,
            "rc": cp.returncode,
            "stdout": cp.stdout[-2000:],
            "stderr": cp.stderr[-2000:],
            "seconds": round(time.time() - start,3),
        })
    except Exception as exc:
        return({"argv":argv,"error":repr(exc),"seconds":round(time.time() - start,3)})


def ssh_base(timeout: float) -> list[str]:
    seconds = str(max(1,int(timeout)))
    return([
        "ssh",
        "-o","BatchMode=yes",
        "-o","ConnectTimeout=%s" % seconds,
        "-o","ServerAliveInterval=2",
        "-o","ServerAliveCountMax=1",
        "-o","StrictHostKeyChecking=no",
        "-o","UserKnownHostsFile=/dev/null",
    ])


def control_options(control_dir: str, persist_seconds: int) -> list[str]:
    if persist_seconds <= 0:
        return([])
    return([
        "-o","ControlMaster=auto",
        "-o","ControlPersist=%ds" % persist_seconds,
        "-o","ControlPath=%s/ds4-peer-%%C" % control_dir.rstrip("/"),
    ])


def ssh_exec(peer: str, timeout: float) -> dict[str,Any]:
    cmd = ssh_base(timeout) + [peer,"printf ds4-peer-ok"]
    result = run_cmd(cmd,timeout + 2.0)
    result["ok"] = result.get("rc") == 0 and "ds4-peer-ok" in str(result.get("stdout",""))
    return(result)


def ssh_control_exec(peer: str, timeout: float, control_dir: str, persist_seconds: int) -> dict[str,Any]:
    if persist_seconds <= 0:
        return({"ok":False,"disabled":True})
    Path(control_dir).expanduser().mkdir(parents=True,exist_ok=True)
    cmd = ssh_base(timeout) + control_options(control_dir,persist_seconds) + [peer,"printf ds4-peer-control-ok"]
    result = run_cmd(cmd,timeout + 2.0)
    result["ok"] = result.get("rc") == 0 and "ds4-peer-control-ok" in str(result.get("stdout",""))
    return(result)


def rescue_owner_matches(observer: str, owner: str) -> bool:
    for item in owner.replace(";",",").split(","):
        name = safe_name(item.strip())
        if name in ("any","all","star") or item.strip() == "*":
            return(True)
        if name == observer:
            return(True)
    return(False)


def should_attempt_remote_rescue(observer: str, owner: str, ssh_result: dict[str,Any], control_result: dict[str,Any]) -> bool:
    if owner == "" or not rescue_owner_matches(observer,owner):
        return(False)
    return(bool(control_result.get("ok",False)) and not bool(ssh_result.get("ok",False)))


def remote_rescue_state_path(state_dir: str, peer: str) -> Path:
    return(Path(state_dir).expanduser() / ("%s.json" % safe_name(peer)))


def remote_rescue_in_cooldown(path: Path, now: float, cooldown_seconds: int) -> bool:
    if cooldown_seconds <= 0 or not path.exists():
        return(False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        attempted_at = float(data.get("attempted_at_unix",0))
    except Exception:
        return(False)
    return((now - attempted_at) < cooldown_seconds)


def trigger_remote_rescue(peer: str, observer: str, target: str, timeout: float, control_dir: str, persist_seconds: int, state_dir: str, cooldown_seconds: int) -> dict[str,Any]:
    now = time.time()
    path = remote_rescue_state_path(state_dir,target)
    path.parent.mkdir(parents=True,exist_ok=True)
    if remote_rescue_in_cooldown(path,now,cooldown_seconds):
        return({"ok":False,"skipped":"cooldown","state_path":str(path)})
    cmd = ssh_base(timeout) + control_options(control_dir,persist_seconds) + [peer,"sudo -n /usr/local/sbin/ds4-sshd-watchdog --peer-force"]
    result = run_cmd(cmd,timeout + 35.0)
    result["ok"] = result.get("rc") == 0
    path.write_text(json.dumps({
        "observer": observer,
        "target": target,
        "attempted_at_unix": int(now),
        "ok": bool(result.get("ok",False)),
        "rc": result.get("rc"),
    },sort_keys=True) + "\n",encoding="utf-8")
    return(result)


def write_record(peer: str, observer: str, remote_dir: str, record: dict[str,Any], timeout: float, control_dir: str, persist_seconds: int) -> dict[str,Any]:
    name = safe_name(observer)
    remote_tmp = "%s/%s.json.tmp" % (remote_dir.rstrip("/"),name)
    remote_final = "%s/%s.json" % (remote_dir.rstrip("/"),name)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",delete=False) as fp:
        tmp_path = fp.name
        json.dump(record,fp,sort_keys=True)
        fp.write("\n")
    try:
        batch = "put %s %s\nrename %s %s\n" % (tmp_path,remote_tmp,remote_tmp,remote_final)
        cmd = [
            "sftp",
            "-q",
            "-o","BatchMode=yes",
            "-o","ConnectTimeout=%s" % max(1,int(timeout)),
            "-o","StrictHostKeyChecking=no",
            "-o","UserKnownHostsFile=/dev/null",
        ] + control_options(control_dir,persist_seconds) + ["-b","-",peer]
        result = run_cmd(cmd,timeout + 2.0,batch)
        result["ok"] = result.get("rc") == 0
        result["remote_path"] = remote_final
        return(result)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def build_record(observer: str, target: str, ssh_result: dict[str,Any], control_result: dict[str,Any] | None = None, rescue_result: dict[str,Any] | None = None) -> dict[str,Any]:
    now = time.time()
    control_result = control_result or {}
    rescue_result = rescue_result or {}
    return({
        "schema": "ds4.peer_ssh_observation.v1",
        "observer": observer,
        "target": target,
        "checked_at_unix": int(now),
        "checked_at_iso": dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat(),
        "probe_mode": "fresh_ssh_plus_persistent_control",
        "ssh_exec_ok": bool(ssh_result.get("ok",False)),
        "ssh_rc": ssh_result.get("rc"),
        "ssh_seconds": ssh_result.get("seconds"),
        "ssh_error": ssh_result.get("error",""),
        "ssh_stderr": str(ssh_result.get("stderr",""))[-500:],
        "control_exec_ok": bool(control_result.get("ok",False)),
        "control_rc": control_result.get("rc"),
        "control_seconds": control_result.get("seconds"),
        "control_error": control_result.get("error",""),
        "control_stderr": str(control_result.get("stderr",""))[-500:],
        "remote_rescue_attempted": "argv" in rescue_result,
        "remote_rescue_ok": bool(rescue_result.get("ok",False)),
        "remote_rescue_skipped": rescue_result.get("skipped",""),
    })


def parse_peers(raw: str, observer: str) -> list[tuple[str,str]]:
    out: list[tuple[str,str]] = []
    seen = set()
    aliases = {observer,socket.gethostname(),socket.gethostname().split(".")[0]}
    for item in raw.replace(";",",").split(","):
        spec = item.strip()
        if spec == "":
            continue
        if "=" in spec:
            label,target = spec.split("=",1)
        elif "@" in spec:
            label,target = spec.split("@",1)[0],spec
        else:
            label,target = spec,spec
        label = safe_name(label.strip())
        target = target.strip()
        if label == "" or target == "" or label in aliases or label in seen:
            continue
        seen.add(label)
        out.append((label,target))
    return(out)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--node", default=os.environ.get("USER","") or socket.gethostname().split(".")[0])
    p.add_argument("--peers", default=DEFAULT_PEERS)
    p.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR)
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--control-dir", default=DEFAULT_CONTROL_DIR)
    p.add_argument("--control-persist-seconds", type=int, default=86400)
    p.add_argument("--remote-rescue-owner", default="any")
    p.add_argument("--remote-rescue-state-dir", default=DEFAULT_RESCUE_STATE_DIR)
    p.add_argument("--remote-rescue-cooldown-seconds", type=int, default=300)
    return(p.parse_args())


def main() -> int:
    args = parse_args()
    observer = safe_name(args.node)
    results = []
    for peer,target in parse_peers(args.peers,observer):
        control_result = ssh_control_exec(target,args.timeout,args.control_dir,args.control_persist_seconds)
        ssh_result = ssh_exec(target,args.timeout)
        rescue_result: dict[str,Any] = {}
        if should_attempt_remote_rescue(observer,args.remote_rescue_owner,ssh_result,control_result):
            rescue_result = trigger_remote_rescue(target,observer,peer,args.timeout,args.control_dir,args.control_persist_seconds,args.remote_rescue_state_dir,args.remote_rescue_cooldown_seconds)
        record = build_record(observer,peer,ssh_result,control_result,rescue_result)
        write_result = write_record(target,observer,args.remote_dir,record,args.timeout,args.control_dir,args.control_persist_seconds)
        results.append({
            "peer": peer,
            "target": target,
            "control_exec_ok": bool(control_result.get("ok",False)),
            "ssh_exec_ok": bool(ssh_result.get("ok",False)),
            "remote_rescue_ok": bool(rescue_result.get("ok",False)),
            "remote_rescue_skipped": rescue_result.get("skipped",""),
            "write_ok": bool(write_result.get("ok",False)),
            "control_error": control_result.get("error","") or control_result.get("stderr",""),
            "ssh_error": ssh_result.get("error","") or ssh_result.get("stderr",""),
            "remote_rescue_error": rescue_result.get("error","") or rescue_result.get("stderr",""),
            "write_error": write_result.get("error","") or write_result.get("stderr",""),
        })
    print(json.dumps({"schema":"ds4.peer_ssh_heartbeat.run.v1","observer":observer,"results":results},sort_keys=True),flush=True)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
