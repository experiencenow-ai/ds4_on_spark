#!/usr/bin/env python3
"""Collect Spark node telemetry logs onto the Mac Studio and summarize them."""

from __future__ import annotations

import argparse
import csv
import os
import shlex
import subprocess
import time
from typing import Dict, List, Tuple

try:
    from . import spark_telemetry_common as telemetry
except ImportError:
    import spark_telemetry_common as telemetry


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nodes", default=telemetry.DEFAULT_NODES)
    p.add_argument("--remote-dir", default=telemetry.TELEMETRY_DIR)
    p.add_argument("--out-dir", default=telemetry.MAC_TELEMETRY_DIR)
    p.add_argument("--tail-lines", type=int, default=17280)
    p.add_argument("--loop-interval", type=float, default=0.0)
    p.add_argument("--ssh-timeout", type=float, default=8.0)
    p.add_argument("--queue-db", default=os.environ.get("DS4_QUEUE_DB",""))
    p.add_argument("--queue-db-glob", default=telemetry.QUEUE_DB_GLOB)
    return(p.parse_args())


def fetch_node(node: str, remote_dir: str, timeout: float, lines: int) -> Tuple[str,str,str]:
    remote_path = shlex.quote(telemetry.node_csv_path(remote_dir))
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


def summarize_node(rows: List[Dict[str,str]], error: str) -> Dict[str,object]:
    if len(rows) == 0:
        return({"sample_count":0,"error":error})
    good = [r for r in rows if not r.get("error")]
    latest = rows[-1]
    gpu_vals = [telemetry.fnum(r,"gpu_util_pct") for r in good if telemetry.gpu_index(r) >= 0]
    gpu_temps = [telemetry.fnum(r,"gpu_temp_c") for r in good if telemetry.gpu_index(r) >= 0 and telemetry.fnum(r,"gpu_temp_c") > 0.0]
    hot = [v for v in gpu_vals if v >= 90.0]
    hot_temps = [v for v in gpu_temps if v >= 80.0]
    return({
        "sample_count": len(rows),
        "first_iso_ts": rows[0].get("iso_ts",""),
        "last_iso_ts": latest.get("iso_ts",""),
        "last_cpu_util_pct": telemetry.fnum(latest,"cpu_util_pct"),
        "last_mem_used_pct": telemetry.fnum(latest,"mem_used_pct"),
        "last_thermal_avg_c": telemetry.fnum(latest,"thermal_avg_c"),
        "last_thermal_max_c": telemetry.fnum(latest,"thermal_max_c"),
        "last_root_disk_used_pct": telemetry.fnum(latest,"root_disk_used_pct"),
        "last_net_rx_mbps": telemetry.fnum(latest,"net_rx_mbps"),
        "last_net_tx_mbps": telemetry.fnum(latest,"net_tx_mbps"),
        "last_proc_count": telemetry.fnum(latest,"proc_count"),
        "last_thread_count": telemetry.fnum(latest,"thread_count"),
        "last_uptime_s": telemetry.fnum(latest,"uptime_s"),
        "last_ds4_gateway_up": telemetry.fnum(latest,"ds4_gateway_up"),
        "last_ds4_gateway_active": telemetry.fnum(latest,"ds4_gateway_active"),
        "last_ds4_gateway_idle_s": telemetry.fnum(latest,"ds4_gateway_idle_s"),
        "last_ds4_gateway_current_model": latest.get("ds4_gateway_current_model",""),
        "last_ds4_gateway_cpu_pending": telemetry.fnum(latest,"ds4_gateway_cpu_pending"),
        "last_ds4_gateway_cpu_active": telemetry.fnum(latest,"ds4_gateway_cpu_active"),
        "last_ds4_gateway_cpu_completed": telemetry.fnum(latest,"ds4_gateway_cpu_completed"),
        "last_ds4_gateway_cpu_failed": telemetry.fnum(latest,"ds4_gateway_cpu_failed"),
        "last_vllm_metrics_up": telemetry.fnum(latest,"vllm_metrics_up"),
        "last_vllm_requests_running": telemetry.fnum(latest,"vllm_requests_running"),
        "last_vllm_requests_waiting": telemetry.fnum(latest,"vllm_requests_waiting"),
        "last_vllm_kv_cache_pct": telemetry.fnum(latest,"vllm_kv_cache_pct"),
        "last_vllm_prompt_tokens_total": telemetry.fnum(latest,"vllm_prompt_tokens_total"),
        "last_vllm_generation_tokens_total": telemetry.fnum(latest,"vllm_generation_tokens_total"),
        "last_vllm_metrics_sources": latest.get("vllm_metrics_sources",""),
        "last_local_queue_db": latest.get("local_queue_db",""),
        "last_local_queue_total": telemetry.fnum(latest,"local_queue_total"),
        "last_local_queue_depth": telemetry.fnum(latest,"local_queue_depth"),
        "last_local_queue_queued": telemetry.fnum(latest,"local_queue_queued"),
        "last_local_queue_running": telemetry.fnum(latest,"local_queue_running"),
        "last_local_queue_completed": telemetry.fnum(latest,"local_queue_completed"),
        "last_local_queue_failed": telemetry.fnum(latest,"local_queue_failed"),
        "last_local_queue_model_depth": telemetry.fnum(latest,"local_queue_model_depth"),
        "last_local_queue_cpu_depth": telemetry.fnum(latest,"local_queue_cpu_depth"),
        "last_local_queue_by_node": latest.get("local_queue_by_node",""),
        "last_gpu_util_pct": telemetry.fnum(latest,"gpu_util_pct"),
        "last_gpu_temp_c": telemetry.fnum(latest,"gpu_temp_c"),
        "last_gpu_fan_pct": telemetry.fnum(latest,"gpu_fan_pct"),
        "last_gpu_clock_sm_mhz": telemetry.fnum(latest,"gpu_clock_sm_mhz"),
        "last_gpu_clock_mem_mhz": telemetry.fnum(latest,"gpu_clock_mem_mhz"),
        "last_gpu_power_w": telemetry.fnum(latest,"gpu_power_w"),
        "last_gpu_pstate": latest.get("gpu_pstate",""),
        "cpu_util_pct": telemetry.stats(telemetry.fnum(r,"cpu_util_pct") for r in rows),
        "mem_used_pct": telemetry.stats(telemetry.fnum(r,"mem_used_pct") for r in rows),
        "thermal_max_c": telemetry.stats(telemetry.fnum(r,"thermal_max_c") for r in rows if telemetry.fnum(r,"thermal_max_c") > 0.0),
        "root_disk_used_pct": telemetry.stats(telemetry.fnum(r,"root_disk_used_pct") for r in rows),
        "net_rx_mbps": telemetry.stats(telemetry.fnum(r,"net_rx_mbps") for r in rows),
        "net_tx_mbps": telemetry.stats(telemetry.fnum(r,"net_tx_mbps") for r in rows),
        "ds4_gateway_cpu_pending": telemetry.stats(telemetry.fnum(r,"ds4_gateway_cpu_pending") for r in rows),
        "ds4_gateway_cpu_active": telemetry.stats(telemetry.fnum(r,"ds4_gateway_cpu_active") for r in rows),
        "vllm_requests_running": telemetry.stats(telemetry.fnum(r,"vllm_requests_running") for r in rows),
        "vllm_requests_waiting": telemetry.stats(telemetry.fnum(r,"vllm_requests_waiting") for r in rows),
        "vllm_kv_cache_pct": telemetry.stats(telemetry.fnum(r,"vllm_kv_cache_pct") for r in rows),
        "local_queue_depth": telemetry.stats(telemetry.fnum(r,"local_queue_depth") for r in rows),
        "local_queue_running": telemetry.stats(telemetry.fnum(r,"local_queue_running") for r in rows),
        "gpu_util_pct": telemetry.stats(gpu_vals),
        "gpu_temp_c": telemetry.stats(gpu_temps),
        "gpu_samples_ge_90": len(hot),
        "pct_gpu_samples_ge_90": round(100.0 * len(hot) / len(gpu_vals),2) if gpu_vals else 0.0,
        "gpu_temp_samples_ge_80": len(hot_temps),
        "pct_gpu_temp_samples_ge_80": round(100.0 * len(hot_temps) / len(gpu_temps),2) if gpu_temps else 0.0,
        "error": error,
    })


def write_combined(out_dir: str, all_rows: Dict[str,List[Dict[str,str]]], errors: Dict[str,str], queue: Dict[str,object]) -> Dict[str,object]:
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
    summary = telemetry.summary_base()
    summary.update({"combined_csv":combined_path,"queue":queue,"nodes":{}})
    for node in sorted(set(all_rows) | set(errors)):
        summary["nodes"][node] = summarize_node(all_rows.get(node,[]),errors.get(node,""))
    telemetry.write_json_atomic(summary_path,summary)
    lines = ["# Spark telemetry summary",""]
    if str(queue.get("local_queue_db","")):
        lines.append("Queue: depth=%s queued=%s running=%s model=%s cpu=%s db=%s" % (
            queue.get("local_queue_depth",0),
            queue.get("local_queue_queued",0),
            queue.get("local_queue_running",0),
            queue.get("local_queue_model_depth",0),
            queue.get("local_queue_cpu_depth",0),
            queue.get("local_queue_db",""),
        ))
        by_node = str(queue.get("local_queue_by_node",""))
        if by_node:
            lines.append("Queue by node: %s" % by_node)
        lines.append("")
    lines.append("| node | samples | gpu % | gpu C | vLLM run/wait | KV % | local q | gateway cpu q | disk % | rx Mbps | tx Mbps | cpu % | mem % | model | error |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for node,row in summary["nodes"].items():
        lines.append("| %s | %s | %.2f | %.2f | %.0f/%.0f | %.2f | %.0f | %.0f/%.0f | %.2f | %.4f | %.4f | %.2f | %.2f | %s | %s |" % (
            node,
            row.get("sample_count",0),
            float(row.get("last_gpu_util_pct",0.0)),
            float(row.get("last_gpu_temp_c",0.0)),
            float(row.get("last_vllm_requests_running",0.0)),
            float(row.get("last_vllm_requests_waiting",0.0)),
            float(row.get("last_vllm_kv_cache_pct",0.0)),
            float(row.get("last_local_queue_depth",0.0)),
            float(row.get("last_ds4_gateway_cpu_pending",0.0)),
            float(row.get("last_ds4_gateway_cpu_active",0.0)),
            float(row.get("last_root_disk_used_pct",0.0)),
            float(row.get("last_net_rx_mbps",0.0)),
            float(row.get("last_net_tx_mbps",0.0)),
            float(row.get("last_cpu_util_pct",0.0)),
            float(row.get("last_mem_used_pct",0.0)),
            str(row.get("last_ds4_gateway_current_model","")).replace("|","/")[:40],
            str(row.get("error","")).replace("|","/"),
        ))
    telemetry.write_text_atomic(md_path,"\n".join(lines) + "\n")
    return(summary)


def collect_once(args: argparse.Namespace) -> Dict[str,object]:
    raw_dir = os.path.join(args.out_dir,"nodes")
    os.makedirs(raw_dir,exist_ok=True)
    all_rows: Dict[str,List[Dict[str,str]]] = {}
    errors: Dict[str,str] = {}
    for node in telemetry.parse_nodes(args.nodes):
        name,text,error = fetch_node(node,args.remote_dir,args.ssh_timeout,args.tail_lines)
        if error:
            errors[name] = error
            all_rows[name] = []
            continue
        telemetry.write_text_atomic(os.path.join(raw_dir,name + ".csv"),text)
        all_rows[name] = read_rows(text)
    queue = telemetry.read_local_queue(args.queue_db,args.queue_db_glob)
    return(write_combined(args.out_dir,all_rows,errors,queue))


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
