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


def ssh_exec(peer: str, timeout: float) -> dict[str,Any]:
    cmd = ssh_base(timeout) + [peer,"printf ds4-peer-ok"]
    result = run_cmd(cmd,timeout + 2.0)
    result["ok"] = result.get("rc") == 0 and "ds4-peer-ok" in str(result.get("stdout",""))
    return(result)


def write_record(peer: str, observer: str, remote_dir: str, record: dict[str,Any], timeout: float) -> dict[str,Any]:
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
            "-b","-",
            peer,
        ]
        result = run_cmd(cmd,timeout + 2.0,batch)
        result["ok"] = result.get("rc") == 0
        result["remote_path"] = remote_final
        return(result)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def build_record(observer: str, target: str, ssh_result: dict[str,Any]) -> dict[str,Any]:
    now = time.time()
    return({
        "schema": "ds4.peer_ssh_observation.v1",
        "observer": observer,
        "target": target,
        "checked_at_unix": int(now),
        "checked_at_iso": dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat(),
        "ssh_exec_ok": bool(ssh_result.get("ok",False)),
        "ssh_rc": ssh_result.get("rc"),
        "ssh_seconds": ssh_result.get("seconds"),
        "ssh_error": ssh_result.get("error",""),
        "ssh_stderr": str(ssh_result.get("stderr",""))[-500:],
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
    return(p.parse_args())


def main() -> int:
    args = parse_args()
    observer = safe_name(args.node)
    results = []
    for peer,target in parse_peers(args.peers,observer):
        ssh_result = ssh_exec(target,args.timeout)
        record = build_record(observer,peer,ssh_result)
        write_result = write_record(target,observer,args.remote_dir,record,args.timeout)
        results.append({
            "peer": peer,
            "target": target,
            "ssh_exec_ok": bool(ssh_result.get("ok",False)),
            "write_ok": bool(write_result.get("ok",False)),
            "ssh_error": ssh_result.get("error","") or ssh_result.get("stderr",""),
            "write_error": write_result.get("error","") or write_result.get("stderr",""),
        })
    print(json.dumps({"schema":"ds4.peer_ssh_heartbeat.run.v1","observer":observer,"results":results},sort_keys=True),flush=True)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
