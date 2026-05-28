#!/usr/bin/env python3
"""Shared Spark telemetry constants and helpers."""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Tuple


SPARK_NODE_COUNT = 8
SPARK_NODES = tuple("spark%d" % i for i in range(SPARK_NODE_COUNT))
DEFAULT_NODES = ",".join(SPARK_NODES)
TELEMETRY_DIR = "/tmp/ds4_telemetry"
MAC_TELEMETRY_DIR = os.path.join(TELEMETRY_DIR,"mac")
NODE_TELEMETRY_CSV = "node_telemetry.csv"
NODE_TELEMETRY_SUMMARY = "node_telemetry.summary.json"
QUEUE_DB_GLOB = "/tmp/ds4_v2_queue/queue.sqlite3,/tmp/ds4_queue/queue.sqlite3,/tmp/ds4_queue_saturation_*/queue/queue.sqlite3,/private/tmp/ds4_queue*/queue.sqlite3,/private/tmp/*/ds4_queue*/queue.sqlite3,/private/tmp/*/queue/queue.sqlite3"
QUEUE_RATE_WINDOW_S = float(os.environ.get("DS4_QUEUE_RATE_WINDOW_S","300"))

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
    "vllm_requests_total",
    "vllm_requests_per_s",
    "vllm_kv_cache_pct",
    "vllm_prompt_tokens_total",
    "vllm_generation_tokens_total",
    "vllm_prompt_tokens_local_compute_total",
    "vllm_prompt_tokens_local_cache_hit_total",
    "vllm_prompt_tokens_external_kv_transfer_total",
    "vllm_prompt_tokens_cached_total",
    "vllm_prefix_cache_queries_total",
    "vllm_prefix_cache_hits_total",
    "vllm_external_prefix_cache_queries_total",
    "vllm_external_prefix_cache_hits_total",
    "vllm_tokens_total",
    "vllm_tokens_per_s",
    "vllm_prompt_tokens_per_s",
    "vllm_generation_tokens_per_s",
    "vllm_prompt_tokens_cached_per_s",
    "vllm_prompt_tokens_local_compute_per_s",
    "vllm_prompt_tokens_local_cache_hit_per_s",
    "vllm_prompt_tokens_external_kv_transfer_per_s",
    "vllm_prompt_cache_hit_pct",
    "vllm_prefix_cache_hit_pct",
    "vllm_external_prefix_cache_hit_pct",
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
    "local_queue_queued_by_node",
    "local_queue_running_by_node",
    "local_queue_prompt_tokens_recent",
    "local_queue_prompt_tok_s",
    "local_queue_prompt_tok_s_by_node",
    "local_queue_completion_requests_recent",
    "local_queue_completion_req_s",
    "local_queue_completion_req_s_by_node",
    "local_queue_completion_tokens_recent",
    "local_queue_completion_tok_s",
    "local_queue_completion_tok_s_by_node",
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


def parse_node_targets(raw: str) -> List[Tuple[str,str]]:
    out: List[Tuple[str,str]] = []
    for item in parse_nodes(raw):
        if "=" in item:
            label,target = item.split("=",1)
            label = label.strip()
            target = target.strip()
        else:
            label = item
            target = item
        if label and target:
            out.append((label,target))
    return(out)


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


def node_metric_map(raw: object) -> Dict[str,float]:
    out: Dict[str,float] = {}
    for item in str(raw or "").split(";"):
        if ":" not in item:
            continue
        key,value = item.split(":",1)
        key = key.strip()
        if key:
            out[key] = num(value)
    return(out)


def format_node_map(values: Dict[str,float]) -> str:
    parts: List[str] = []
    for key in sorted(values):
        value = values[key]
        text = str(int(value)) if float(value).is_integer() else ("%.3f" % value).rstrip("0").rstrip(".")
        parts.append("%s:%s" % (key,text))
    return(";".join(parts)[:240])


def result_usage_tokens(raw: object, key: str) -> int:
    try:
        data = json.loads(str(raw or "{}"))
    except Exception:
        return(0)
    usage = data.get("usage") if isinstance(data,dict) else None
    if not isinstance(usage,dict):
        response = data.get("response") if isinstance(data,dict) else None
        usage = response.get("usage") if isinstance(response,dict) else None
    if not isinstance(usage,dict):
        result = data.get("result") if isinstance(data,dict) else None
        usage = result.get("usage") if isinstance(result,dict) else None
    if not isinstance(usage,dict):
        return(0)
    return(int(num(usage.get(key,0))))


def result_prompt_tokens(raw: object) -> int:
    return(result_usage_tokens(raw,"prompt_tokens"))


def result_completion_tokens(raw: object) -> int:
    return(result_usage_tokens(raw,"completion_tokens"))


def read_local_queue(raw_path: str, raw_globs: str, rate_window_s: float = QUEUE_RATE_WINDOW_S) -> Dict[str,object]:
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
        "local_queue_queued_by_node": "",
        "local_queue_running_by_node": "",
        "local_queue_prompt_tokens_recent": 0,
        "local_queue_prompt_tok_s": 0.0,
        "local_queue_prompt_tok_s_by_node": "",
        "local_queue_completion_requests_recent": 0,
        "local_queue_completion_req_s": 0.0,
        "local_queue_completion_req_s_by_node": "",
        "local_queue_completion_tokens_recent": 0,
        "local_queue_completion_tok_s": 0.0,
        "local_queue_completion_tok_s_by_node": "",
    }
    best: Tuple[int,float,int,int] | None = None
    best_out: Dict[str,object] | None = None
    for path in queue_db_candidates(raw_path,raw_globs):
        try:
            with sqlite3.connect(path,timeout=0.25) as conn:
                cols = {str(row[1]) for row in conn.execute("pragma table_info(requests)").fetchall()}
                states = {str(k):int(v) for k,v in conn.execute("select state,count(*) from requests group by state").fetchall()}
                kinds = {str(k):int(v) for k,v in conn.execute("select request_kind,count(*) from requests where state in ('queued','running') group by request_kind").fetchall()}
                nodes = conn.execute("select selected_node_id,count(*) from requests where state in ('queued','running') and selected_node_id is not null group by selected_node_id").fetchall()
                queued_nodes = conn.execute("select selected_node_id,count(*) from requests where state = 'queued' and selected_node_id is not null group by selected_node_id").fetchall()
                running_nodes = conn.execute("select selected_node_id,count(*) from requests where state = 'running' and selected_node_id is not null group by selected_node_id").fetchall()
                active_updated_at = 0.0
                if "updated_at" in cols:
                    active_updated_at = num(conn.execute("select max(updated_at) from requests where state in ('queued','running')").fetchone()[0])
                recent_prompt_tokens = 0
                recent_requests = 0
                recent_tokens = 0
                recent_prompt_by_node: Dict[str,float] = {}
                recent_requests_by_node: Dict[str,float] = {}
                recent_by_node: Dict[str,float] = {}
                if "completed_at" in cols and "result_json" in cols:
                    cutoff = time.time() - max(1.0,rate_window_s)
                    for node,raw_result in conn.execute("select selected_node_id,result_json from requests where state = 'completed' and completed_at is not null and completed_at >= ?", (cutoff,)).fetchall():
                        prompt_tokens = result_prompt_tokens(raw_result)
                        tokens = result_completion_tokens(raw_result)
                        recent_prompt_tokens += prompt_tokens
                        recent_requests += 1
                        recent_tokens += tokens
                        if node is not None:
                            recent_prompt_by_node[str(node)] = recent_prompt_by_node.get(str(node),0.0) + float(prompt_tokens)
                            recent_requests_by_node[str(node)] = recent_requests_by_node.get(str(node),0.0) + 1.0
                            recent_by_node[str(node)] = recent_by_node.get(str(node),0.0) + float(tokens)
        except Exception:
            continue
        queued = int(states.get("queued",0))
        running = int(states.get("running",0))
        window = max(1.0,rate_window_s)
        candidate = dict(out)
        candidate.update({
            "local_queue_db": path,
            "local_queue_total": sum(states.values()),
            "local_queue_depth": queued + running,
            "local_queue_queued": queued,
            "local_queue_running": running,
            "local_queue_completed": int(states.get("completed",0)),
            "local_queue_failed": int(states.get("failed",0)),
            "local_queue_model_depth": int(kinds.get("model",0)),
            "local_queue_cpu_depth": int(kinds.get("cpu",0)),
            "local_queue_by_node": format_node_map({str(node):float(count) for node,count in nodes}),
            "local_queue_queued_by_node": format_node_map({str(node):float(count) for node,count in queued_nodes}),
            "local_queue_running_by_node": format_node_map({str(node):float(count) for node,count in running_nodes}),
            "local_queue_prompt_tokens_recent": recent_prompt_tokens,
            "local_queue_prompt_tok_s": round(float(recent_prompt_tokens) / window,3),
            "local_queue_prompt_tok_s_by_node": format_node_map({node:tokens / window for node,tokens in recent_prompt_by_node.items()}),
            "local_queue_completion_requests_recent": recent_requests,
            "local_queue_completion_req_s": round(float(recent_requests) / window,3),
            "local_queue_completion_req_s_by_node": format_node_map({node:requests / window for node,requests in recent_requests_by_node.items()}),
            "local_queue_completion_tokens_recent": recent_tokens,
            "local_queue_completion_tok_s": round(float(recent_tokens) / window,3),
            "local_queue_completion_tok_s_by_node": format_node_map({node:tokens / window for node,tokens in recent_by_node.items()}),
        })
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0.0
        score = (1 if queued + running > 0 else 0, max(active_updated_at,mtime), queued + running, int(recent_tokens))
        if best is None or score > best:
            best = score
            best_out = candidate
    return(best_out if best_out is not None else out)
