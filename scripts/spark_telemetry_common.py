#!/usr/bin/env python3
"""Shared Spark telemetry constants and helpers."""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List


SPARK_NODE_COUNT = 8
SPARK_NODES = tuple("spark%d" % i for i in range(SPARK_NODE_COUNT))
DEFAULT_NODES = ",".join(SPARK_NODES)
TELEMETRY_DIR = "/tmp/ds4_telemetry"
MAC_TELEMETRY_DIR = os.path.join(TELEMETRY_DIR,"mac")
NODE_TELEMETRY_CSV = "node_telemetry.csv"
NODE_TELEMETRY_SUMMARY = "node_telemetry.summary.json"
QUEUE_DB_GLOB = "/tmp/ds4_v2_queue/queue.sqlite3,/tmp/ds4_queue/queue.sqlite3,/tmp/ds4_queue_saturation_*/queue/queue.sqlite3"

BASE_GPU_FIELDS = [
    "index",
    "name",
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "memory.total",
    "power.draw",
    "pstate",
]

EXTRA_GPU_FIELDS = [
    "temperature.gpu",
    "fan.speed",
    "clocks.gr",
    "clocks.mem",
]

GPU_FIELDS = BASE_GPU_FIELDS + EXTRA_GPU_FIELDS

CSV_FIELDS = [
    "unix_ts",
    "iso_ts",
    "node",
    "hostname",
    "cpu_util_pct",
    "load1",
    "load5",
    "load15",
    "mem_total_mib",
    "mem_available_mib",
    "mem_used_mib",
    "mem_used_pct",
    "swap_total_mib",
    "swap_used_mib",
    "swap_used_pct",
    "thermal_avg_c",
    "thermal_max_c",
    "thermal_sources",
    "root_disk_total_gib",
    "root_disk_used_gib",
    "root_disk_available_gib",
    "root_disk_used_pct",
    "net_rx_bytes",
    "net_tx_bytes",
    "net_rx_mbps",
    "net_tx_mbps",
    "proc_count",
    "thread_count",
    "uptime_s",
    "ds4_gateway_up",
    "ds4_gateway_active",
    "ds4_gateway_idle_s",
    "ds4_gateway_current_model",
    "ds4_gateway_cpu_pending",
    "ds4_gateway_cpu_active",
    "ds4_gateway_cpu_completed",
    "ds4_gateway_cpu_failed",
    "vllm_metrics_up",
    "vllm_requests_running",
    "vllm_requests_waiting",
    "vllm_kv_cache_pct",
    "vllm_prompt_tokens_total",
    "vllm_generation_tokens_total",
    "vllm_metrics_sources",
    "local_queue_db",
    "local_queue_total",
    "local_queue_depth",
    "local_queue_queued",
    "local_queue_running",
    "local_queue_completed",
    "local_queue_failed",
    "local_queue_model_depth",
    "local_queue_cpu_depth",
    "local_queue_by_node",
    "gpu_index",
    "gpu_name",
    "gpu_util_pct",
    "gpu_mem_util_pct",
    "gpu_mem_used_mib",
    "gpu_mem_total_mib",
    "gpu_power_w",
    "gpu_temp_c",
    "gpu_fan_pct",
    "gpu_clock_sm_mhz",
    "gpu_clock_mem_mhz",
    "gpu_pstate",
    "error",
]


def parse_nodes(raw: str) -> List[str]:
    text = (raw or "").strip()
    if text == "" or text.lower() in ("all","8x","spark8","sparks"):
        return(list(SPARK_NODES))
    return([node.strip() for node in text.split(",") if node.strip()])


def node_csv_path(root: str = TELEMETRY_DIR) -> str:
    return(os.path.join(root.rstrip("/"),NODE_TELEMETRY_CSV))


def node_summary_path(root: str = TELEMETRY_DIR) -> str:
    return(os.path.join(root.rstrip("/"),NODE_TELEMETRY_SUMMARY))


def utc_iso() -> str:
    return(dt.datetime.now(dt.timezone.utc).isoformat())


def write_text_atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp,path)


def write_json_atomic(path: str, data: Dict[str,Any]) -> None:
    write_text_atomic(path,json.dumps(data,indent=2,sort_keys=True) + "\n")


def stats(vals: Iterable[float]) -> Dict[str,float]:
    data = list(vals)
    if len(data) == 0:
        return({"avg":0.0,"max":0.0,"min":0.0})
    return({"avg":round(sum(data) / len(data),2),"max":round(max(data),2),"min":round(min(data),2)})


def num(value: object) -> float:
    try:
        s = str(value).replace(" W","").replace(" %","").replace(" MHz","").strip()
        if s in ("","N/A","[N/A]","Not Supported"):
            return(0.0)
        return(float(s))
    except Exception:
        return(0.0)


def fnum(row: Dict[str,str], key: str) -> float:
    return(num(row.get(key,"0")))


def gpu_index(row: Dict[str,str]) -> int:
    try:
        return(int(float(row.get("gpu_index","-1") or -1)))
    except Exception:
        return(-1)


def parse_gpu_line(line: str, fields: List[str]) -> Dict[str,str]:
    vals = [value.strip() for value in line.split(",")]
    return({key:value for key,value in zip(fields,vals)})


def nvidia_smi_query(fields: List[str]) -> str:
    return("nvidia-smi --query-gpu=%s --format=csv,noheader,nounits" % ",".join(fields))


def summary_base() -> Dict[str,object]:
    return({"updated_unix":int(time.time()),"updated_iso":utc_iso()})


def queue_db_candidates(raw_path: str, raw_globs: str) -> List[str]:
    paths: List[str] = []
    if raw_path.strip():
        paths.append(raw_path.strip())
    for pattern in [item.strip() for item in raw_globs.split(",") if item.strip()]:
        paths.extend(glob.glob(pattern))
    uniq: Dict[str,float] = {}
    for path in paths:
        try:
            uniq[path] = os.path.getmtime(path)
        except Exception:
            pass
    return([item[0] for item in sorted(uniq.items(),key=lambda kv: kv[1],reverse=True)])


def read_local_queue(raw_path: str, raw_globs: str) -> Dict[str,object]:
    out: Dict[str,object] = {
        "local_queue_db": "",
        "local_queue_total": 0,
        "local_queue_depth": 0,
        "local_queue_queued": 0,
        "local_queue_running": 0,
        "local_queue_completed": 0,
        "local_queue_failed": 0,
        "local_queue_model_depth": 0,
        "local_queue_cpu_depth": 0,
        "local_queue_by_node": "",
    }
    for path in queue_db_candidates(raw_path,raw_globs):
        try:
            with sqlite3.connect(path,timeout=0.25) as conn:
                states = {str(k):int(v) for k,v in conn.execute("select state,count(*) from requests group by state").fetchall()}
                kinds = {str(k):int(v) for k,v in conn.execute("select request_kind,count(*) from requests where state in ('queued','running') group by request_kind").fetchall()}
                nodes = conn.execute("select selected_node_id,count(*) from requests where state in ('queued','running') and selected_node_id is not null group by selected_node_id").fetchall()
        except Exception:
            continue
        queued = int(states.get("queued",0))
        running = int(states.get("running",0))
        out.update({
            "local_queue_db": path,
            "local_queue_total": sum(states.values()),
            "local_queue_depth": queued + running,
            "local_queue_queued": queued,
            "local_queue_running": running,
            "local_queue_completed": int(states.get("completed",0)),
            "local_queue_failed": int(states.get("failed",0)),
            "local_queue_model_depth": int(kinds.get("model",0)),
            "local_queue_cpu_depth": int(kinds.get("cpu",0)),
            "local_queue_by_node": ";".join("%s:%d" % (node,count) for node,count in nodes)[:240],
        })
        break
    return(out)
