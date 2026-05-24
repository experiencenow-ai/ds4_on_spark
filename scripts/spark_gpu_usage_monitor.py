#!/usr/bin/env python3
"""Poll Spark GPU utilization over ssh and write a CSV time series."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Tuple


BASE_FIELDS = [
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "memory.total",
    "power.draw",
    "pstate",
]

EXTRA_FIELDS = [
    "temperature.gpu",
    "fan.speed",
    "clocks.gr",
    "clocks.mem",
]

FIELDS = BASE_FIELDS + EXTRA_FIELDS


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nodes", default="spark0,spark1,spark2,spark3,spark4,spark5,spark6,spark7")
    p.add_argument("--local-node-name", default="")
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--duration", type=float, default=0.0)
    p.add_argument("--out", required=True)
    p.add_argument("--summary", default="")
    p.add_argument("--ssh-timeout", type=float, default=4.0)
    return(p.parse_args())


def parse_gpu_line(line: str, fields: List[str]) -> Dict[str, str]:
    values = [item.strip() for item in line.split(",")]
    out: Dict[str, str] = {}
    for field,value in zip(fields,values):
        out[field] = value
    return(out)


def poll_node_fields(node: str, timeout: float, local_node_name: str, fields: List[str]) -> Tuple[str,List[Dict[str,str]],str]:
    query = "nvidia-smi --query-gpu=%s --format=csv,noheader,nounits" % ",".join(fields)
    outnode = local_node_name if node == "local" and local_node_name else node
    if node == "local":
        cmd = query.split(" ")
    else:
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=%d" % max(1,int(timeout)),
            node,
            query,
        ]
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except Exception as e:
        return(outnode,[],"%s" % e)
    if p.returncode != 0:
        return(outnode,[],p.stderr.strip() or ("command exited %d" % p.returncode))
    rows = [parse_gpu_line(line,fields) for line in p.stdout.splitlines() if line.strip()]
    return(outnode,rows,"")


def poll_node(node: str, timeout: float, local_node_name: str) -> Tuple[str,List[Dict[str,str]],str]:
    last_node = local_node_name if node == "local" and local_node_name else node
    last_error = ""
    for fields in [FIELDS,BASE_FIELDS + ["temperature.gpu"],BASE_FIELDS]:
        outnode,rows,error = poll_node_fields(node,timeout,local_node_name,fields)
        last_node = outnode
        if error == "":
            return(outnode,rows,"")
        last_error = error
        if "timed out" in error.lower():
            break
    return(last_node,[],last_error)


def row_float(row: Dict[str,str], key: str) -> float:
    try:
        val = row.get(key,"").replace(" W","").replace(" %","").replace(" MHz","")
        return(float(val))
    except Exception:
        return(0.0)


def write_summary(path: str, samples: List[Dict[str,object]]) -> None:
    by_node: Dict[str,List[float]] = {}
    temps_by_node: Dict[str,List[float]] = {}
    for row in samples:
        if row.get("error"):
            continue
        by_node.setdefault(str(row["node"]),[]).append(float(row["gpu_util_pct"]))
        if float(row.get("gpu_temp_c",0.0)) > 0.0:
            temps_by_node.setdefault(str(row["node"]),[]).append(float(row["gpu_temp_c"]))
    summary = {
        "updated_unix": int(time.time()),
        "samples": len(samples),
        "nodes": {},
    }
    for node,vals in sorted(by_node.items()):
        hot = [v for v in vals if v >= 90.0]
        temps = temps_by_node.get(node,[])
        summary["nodes"][node] = {
            "sample_count": len(vals),
            "avg_gpu_util_pct": round(sum(vals) / len(vals),2) if vals else 0.0,
            "max_gpu_util_pct": round(max(vals),2) if vals else 0.0,
            "samples_ge_90_pct": len(hot),
            "pct_samples_ge_90": round((100.0 * len(hot) / len(vals)),2) if vals else 0.0,
            "last_gpu_util_pct": round(vals[-1],2) if vals else 0.0,
            "avg_gpu_temp_c": round(sum(temps) / len(temps),2) if temps else 0.0,
            "max_gpu_temp_c": round(max(temps),2) if temps else 0.0,
            "last_gpu_temp_c": round(temps[-1],2) if temps else 0.0,
        }
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(summary,f,indent=2,sort_keys=True)
        f.write("\n")
    os.replace(tmp,path)


def main() -> int:
    args = parse_args()
    nodes = [node.strip() for node in args.nodes.split(",") if node.strip()]
    if len(nodes) == 0:
        raise SystemExit("no nodes selected")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)),exist_ok=True)
    summary_path = args.summary or (args.out + ".summary.json")
    new_file = not os.path.exists(args.out)
    samples: List[Dict[str,object]] = []
    start = time.time()
    with open(args.out,"a",encoding="utf-8",newline="") as f:
        cols = ["unix_ts","iso_ts","node","gpu_index","gpu_util_pct","mem_util_pct","mem_used_mib","mem_total_mib","power_w","gpu_temp_c","fan_pct","clock_sm_mhz","clock_mem_mhz","pstate","error"]
        writer = csv.DictWriter(f,fieldnames=cols)
        if new_file:
            writer.writeheader()
        while True:
            now = time.time()
            iso = dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(nodes)) as pool:
                futs = [pool.submit(poll_node,node,args.ssh_timeout,args.local_node_name) for node in nodes]
                for fut in concurrent.futures.as_completed(futs):
                    node,rows,error = fut.result()
                    if error:
                        row = {"unix_ts":int(now),"iso_ts":iso,"node":node,"gpu_index":"","gpu_util_pct":0.0,"mem_util_pct":0.0,"mem_used_mib":0.0,"mem_total_mib":0.0,"power_w":0.0,"gpu_temp_c":0.0,"fan_pct":0.0,"clock_sm_mhz":0.0,"clock_mem_mhz":0.0,"pstate":"","error":error}
                        writer.writerow(row)
                        samples.append(row)
                        continue
                    for i,gpu in enumerate(rows):
                        row = {
                            "unix_ts": int(now),
                            "iso_ts": iso,
                            "node": node,
                            "gpu_index": i,
                            "gpu_util_pct": row_float(gpu,"utilization.gpu"),
                            "mem_util_pct": row_float(gpu,"utilization.memory"),
                            "mem_used_mib": row_float(gpu,"memory.used"),
                            "mem_total_mib": row_float(gpu,"memory.total"),
                            "power_w": row_float(gpu,"power.draw"),
                            "gpu_temp_c": row_float(gpu,"temperature.gpu"),
                            "fan_pct": row_float(gpu,"fan.speed"),
                            "clock_sm_mhz": row_float(gpu,"clocks.gr"),
                            "clock_mem_mhz": row_float(gpu,"clocks.mem"),
                            "pstate": gpu.get("pstate",""),
                            "error": "",
                        }
                        writer.writerow(row)
                        samples.append(row)
            f.flush()
            write_summary(summary_path,samples)
            if args.duration > 0.0 and (time.time() - start) >= args.duration:
                break
            time.sleep(args.interval)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
