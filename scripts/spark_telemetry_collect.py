#!/usr/bin/env python3
"""Collect Spark node telemetry logs onto the Mac Studio and summarize them."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shlex
import subprocess
import time
from typing import Dict, Iterable, List, Tuple


DEFAULT_NODES = "spark0,spark1,spark2,spark3,spark4,spark5,spark6,spark7"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nodes", default=DEFAULT_NODES)
    p.add_argument("--remote-dir", default="/tmp/ds4_telemetry")
    p.add_argument("--out-dir", default="/tmp/ds4_telemetry/mac")
    p.add_argument("--tail-lines", type=int, default=17280)
    p.add_argument("--loop-interval", type=float, default=0.0)
    p.add_argument("--ssh-timeout", type=float, default=8.0)
    return(p.parse_args())


def nodes(raw: str) -> List[str]:
    return([n.strip() for n in raw.split(",") if n.strip()])


def fetch_node(node: str, remote_dir: str, timeout: float, lines: int) -> Tuple[str,str,str]:
    remote_path = shlex.quote(remote_dir.rstrip("/") + "/node_telemetry.csv")
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=%d" % max(1,int(timeout)),
        node,
        "if [ -r %s ]; then head -n 1 %s; tail -n %d %s; else exit 1; fi" % (remote_path,remote_path,lines,remote_path),
    ]
    try:
        p = subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    except Exception as e:
        return(node,"","%s" % e)
    if p.returncode != 0:
        return(node,"",p.stderr.strip() or ("ssh exited %d" % p.returncode))
    return(node,p.stdout,"")


def write_text_atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp,path)


def read_rows(text: str) -> List[Dict[str,str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) == 0:
        return([])
    while lines and not lines[0].startswith("unix_ts,"):
        lines.pop(0)
    if len(lines) == 0:
        return([])
    rows: List[Dict[str,str]] = []
    for row in csv.DictReader(lines):
        row.pop(None,None)
        if row.get("unix_ts","") == "unix_ts":
            continue
        rows.append(row)
    return(rows)


def fnum(row: Dict[str,str], key: str) -> float:
    try:
        return(float(row.get(key,"0") or 0.0))
    except Exception:
        return(0.0)


def gpu_index(row: Dict[str,str]) -> int:
    try:
        return(int(float(row.get("gpu_index","-1") or -1)))
    except Exception:
        return(-1)


def stats(vals: Iterable[float]) -> Dict[str,float]:
    data = list(vals)
    if len(data) == 0:
        return({"avg":0.0,"max":0.0,"min":0.0})
    return({"avg":round(sum(data) / len(data),2),"max":round(max(data),2),"min":round(min(data),2)})


def summarize_node(rows: List[Dict[str,str]], error: str) -> Dict[str,object]:
    if len(rows) == 0:
        return({"sample_count":0,"error":error})
    good = [r for r in rows if not r.get("error")]
    latest = rows[-1]
    gpu_vals = [fnum(r,"gpu_util_pct") for r in good if gpu_index(r) >= 0]
    gpu_temps = [fnum(r,"gpu_temp_c") for r in good if gpu_index(r) >= 0 and fnum(r,"gpu_temp_c") > 0.0]
    hot = [v for v in gpu_vals if v >= 90.0]
    hot_temps = [v for v in gpu_temps if v >= 80.0]
    return({
        "sample_count": len(rows),
        "first_iso_ts": rows[0].get("iso_ts",""),
        "last_iso_ts": latest.get("iso_ts",""),
        "last_cpu_util_pct": fnum(latest,"cpu_util_pct"),
        "last_mem_used_pct": fnum(latest,"mem_used_pct"),
        "last_thermal_avg_c": fnum(latest,"thermal_avg_c"),
        "last_thermal_max_c": fnum(latest,"thermal_max_c"),
        "last_root_disk_used_pct": fnum(latest,"root_disk_used_pct"),
        "last_net_rx_mbps": fnum(latest,"net_rx_mbps"),
        "last_net_tx_mbps": fnum(latest,"net_tx_mbps"),
        "last_proc_count": fnum(latest,"proc_count"),
        "last_thread_count": fnum(latest,"thread_count"),
        "last_uptime_s": fnum(latest,"uptime_s"),
        "last_gpu_util_pct": fnum(latest,"gpu_util_pct"),
        "last_gpu_temp_c": fnum(latest,"gpu_temp_c"),
        "last_gpu_fan_pct": fnum(latest,"gpu_fan_pct"),
        "last_gpu_clock_sm_mhz": fnum(latest,"gpu_clock_sm_mhz"),
        "last_gpu_clock_mem_mhz": fnum(latest,"gpu_clock_mem_mhz"),
        "last_gpu_power_w": fnum(latest,"gpu_power_w"),
        "last_gpu_pstate": latest.get("gpu_pstate",""),
        "cpu_util_pct": stats(fnum(r,"cpu_util_pct") for r in rows),
        "mem_used_pct": stats(fnum(r,"mem_used_pct") for r in rows),
        "thermal_max_c": stats(fnum(r,"thermal_max_c") for r in rows if fnum(r,"thermal_max_c") > 0.0),
        "root_disk_used_pct": stats(fnum(r,"root_disk_used_pct") for r in rows),
        "net_rx_mbps": stats(fnum(r,"net_rx_mbps") for r in rows),
        "net_tx_mbps": stats(fnum(r,"net_tx_mbps") for r in rows),
        "gpu_util_pct": stats(gpu_vals),
        "gpu_temp_c": stats(gpu_temps),
        "gpu_samples_ge_90": len(hot),
        "pct_gpu_samples_ge_90": round(100.0 * len(hot) / len(gpu_vals),2) if gpu_vals else 0.0,
        "gpu_temp_samples_ge_80": len(hot_temps),
        "pct_gpu_temp_samples_ge_80": round(100.0 * len(hot_temps) / len(gpu_temps),2) if gpu_temps else 0.0,
        "error": error,
    })


def write_combined(out_dir: str, all_rows: Dict[str,List[Dict[str,str]]], errors: Dict[str,str]) -> Dict[str,object]:
    os.makedirs(out_dir,exist_ok=True)
    combined_path = os.path.join(out_dir,"combined_latest.csv")
    summary_path = os.path.join(out_dir,"cluster_summary.json")
    md_path = os.path.join(out_dir,"cluster_summary.md")
    fieldnames: List[str] = []
    seen = set()
    for rows in all_rows.values():
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with open(combined_path + ".tmp","w",encoding="utf-8",newline="") as f:
        if fieldnames:
            w = csv.DictWriter(f,fieldnames=fieldnames)
            w.writeheader()
            for node in sorted(all_rows):
                for row in all_rows[node]:
                    w.writerow({key:row.get(key,"") for key in fieldnames})
    os.replace(combined_path + ".tmp",combined_path)
    summary = {
        "updated_unix": int(time.time()),
        "updated_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
        "combined_csv": combined_path,
        "nodes": {},
    }
    for node in sorted(set(all_rows) | set(errors)):
        summary["nodes"][node] = summarize_node(all_rows.get(node,[]),errors.get(node,""))
    write_text_atomic(summary_path,json.dumps(summary,indent=2,sort_keys=True) + "\n")
    lines = ["# Spark telemetry summary",""]
    lines.append("| node | samples | last gpu % | avg gpu % | last gpu C | max gpu C | last CPU C | disk % | rx Mbps | tx Mbps | last cpu % | last mem % | error |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for node,row in summary["nodes"].items():
        gpu = row.get("gpu_util_pct",{}) if isinstance(row.get("gpu_util_pct"),dict) else {}
        gpu_temp = row.get("gpu_temp_c",{}) if isinstance(row.get("gpu_temp_c"),dict) else {}
        lines.append("| %s | %s | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f | %.4f | %.4f | %.2f | %.2f | %s |" % (
            node,
            row.get("sample_count",0),
            float(row.get("last_gpu_util_pct",0.0)),
            float(gpu.get("avg",0.0)),
            float(row.get("last_gpu_temp_c",0.0)),
            float(gpu_temp.get("max",0.0)),
            float(row.get("last_thermal_max_c",0.0)),
            float(row.get("last_root_disk_used_pct",0.0)),
            float(row.get("last_net_rx_mbps",0.0)),
            float(row.get("last_net_tx_mbps",0.0)),
            float(row.get("last_cpu_util_pct",0.0)),
            float(row.get("last_mem_used_pct",0.0)),
            str(row.get("error","")).replace("|","/"),
        ))
    write_text_atomic(md_path,"\n".join(lines) + "\n")
    return(summary)


def collect_once(args: argparse.Namespace) -> Dict[str,object]:
    raw_dir = os.path.join(args.out_dir,"nodes")
    os.makedirs(raw_dir,exist_ok=True)
    all_rows: Dict[str,List[Dict[str,str]]] = {}
    errors: Dict[str,str] = {}
    for node in nodes(args.nodes):
        name,text,error = fetch_node(node,args.remote_dir,args.ssh_timeout,args.tail_lines)
        if error:
            errors[name] = error
            all_rows[name] = []
            continue
        write_text_atomic(os.path.join(raw_dir,name + ".csv"),text)
        all_rows[name] = read_rows(text)
    return(write_combined(args.out_dir,all_rows,errors))


def main() -> int:
    args = parse_args()
    while True:
        summary = collect_once(args)
        print("wrote %s" % summary["combined_csv"],flush=True)
        if args.loop_interval <= 0.0:
            break
        time.sleep(args.loop_interval)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
