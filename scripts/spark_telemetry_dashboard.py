#!/usr/bin/env python3
"""Serve a tiny local Spark telemetry dashboard."""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_SUMMARY_JSON = "/tmp/ds4_telemetry/mac/cluster_summary.json"
DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spark Telemetry</title>
<style>
:root{color-scheme:dark;--bg:#111316;--panel:#1b1f24;--line:#313943;--text:#f2f5f8;--muted:#a8b1bb;--ok:#53d18a;--busy:#63b3ff;--warn:#f4bf5f;--bad:#ff6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;letter-spacing:0}
main{max-width:1280px;margin:0 auto;padding:18px}.top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:14px}
h1{font-size:22px;line-height:1.1;margin:0}.meta{color:var(--muted);text-align:right;line-height:1.5}.summary{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:10px;margin-bottom:14px}
.metric,.card{background:var(--panel);border:1px solid var(--line);border-radius:8px}.metric{padding:12px}.label{color:var(--muted);font-size:12px}.value{font-size:23px;font-weight:700;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}.card{padding:12px;min-height:150px}.card header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
.node{font-size:18px;font-weight:700}.pill{border-radius:999px;padding:3px 8px;font-size:12px;font-weight:700;color:#111316;background:var(--muted)}.busy .pill{background:var(--busy)}.idle .pill{background:var(--ok)}.warn .pill,.hot .pill{background:var(--warn)}.down .pill{background:var(--bad)}
.bars{display:grid;gap:8px}.barrow{display:grid;grid-template-columns:54px 1fr 48px;align-items:center;gap:8px;color:var(--muted)}.track{height:8px;background:#0d0f12;border-radius:999px;overflow:hidden}.fill{height:100%;width:0;background:var(--ok)}.busy .gpu .fill,.busy .kv .fill{background:var(--busy)}.warn .fill,.hot .fill{background:var(--warn)}.down .fill{background:var(--bad)}
.details{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-top:10px;color:var(--muted)}.details b{color:var(--text);font-weight:600}.error{margin-top:8px;color:var(--bad);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media (max-width:720px){main{padding:12px}.top{align-items:flex-start;flex-direction:column}.meta{text-align:left}.summary{grid-template-columns:repeat(2,minmax(120px,1fr))}}
</style>
</head>
<body><main>
<div class="top"><h1>Spark Telemetry</h1><div class="meta"><div id="updated">loading</div><div id="source"></div></div></div>
<section class="summary" id="summary"></section>
<section class="grid" id="nodes"></section>
</main>
<script>
const fmt=n=>Number.isFinite(Number(n))?Number(n).toFixed(0):"";
const pct=n=>Number.isFinite(Number(n))?Number(n).toFixed(0)+"%":"n/a";
const val=(n,s="")=>Number.isFinite(Number(n))?Number(n).toFixed(1)+s:"n/a";
function metric(label,value){return `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`}
function bar(label,value,cls){let width=Math.max(0,Math.min(100,Number(value)||0));return `<div class="barrow ${cls}"><span>${label}</span><div class="track"><div class="fill" style="width:${width}%"></div></div><span>${pct(value)}</span></div>`}
function card(n){return `<article class="card ${n.state}"><header><div class="node">${n.node}</div><div class="pill">${n.state_label}</div></header><div class="bars">${bar("GPU",n.gpu_pct,"gpu")}${bar("KV",n.kv_pct,"kv")}${bar("MEM",n.mem_pct,"mem")}</div><div class="details"><span>Temp <b>${fmt(n.gpu_temp_c)}C</b></span><span>Power <b>${fmt(n.gpu_power_w)}W</b></span><span>vLLM <b>${fmt(n.vllm_running)}/${fmt(n.vllm_waiting)}</b></span><span>Queue <b>${fmt(n.local_q_depth)}</b></span><span>CPU <b>${pct(n.cpu_pct)}</b></span><span>Gateway <b>${n.gateway_up?"up":"down"}</b></span></div>${n.error?`<div class="error">${n.error}</div>`:""}</article>`}
async function refresh(){try{let r=await fetch("/api/summary",{cache:"no-store"});let d=await r.json();document.getElementById("updated").textContent="updated "+(d.updated_iso||"unknown");document.getElementById("source").textContent=d.summary_path||"";document.getElementById("summary").innerHTML=[metric("Busy GPUs",`${d.busy_gpu_nodes}/${d.reachable_nodes}`),metric("vLLM Run/Wait",`${fmt(d.vllm_running)}/${fmt(d.vllm_waiting)}`),metric("Max KV",pct(d.max_kv_pct)),metric("Hot Nodes",fmt(d.hot_nodes)),metric("Queue Depth",fmt(d.queue_depth))].join("");document.getElementById("nodes").innerHTML=d.nodes.map(card).join("")}catch(e){document.getElementById("updated").textContent="dashboard read failed: "+e}}
refresh();setInterval(refresh,3000);
</script></body></html>
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary-json", default=DEFAULT_SUMMARY_JSON)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    return(p.parse_args())


def fnum(value: Any) -> float:
    try:
        return(float(value))
    except Exception:
        return(0.0)


def node_state(row: dict[str,Any]) -> tuple[str,str]:
    if int(fnum(row.get("sample_count"))) <= 0 or str(row.get("error","")) != "":
        return("down","down")
    if fnum(row.get("last_gpu_temp_c")) >= 80.0 or fnum(row.get("last_thermal_max_c")) >= 85.0:
        return("hot","hot")
    if fnum(row.get("last_vllm_waiting")) > 0.0 or fnum(row.get("last_vllm_kv_cache_pct")) >= 90.0:
        return("warn","queued")
    if fnum(row.get("last_gpu_util_pct")) >= 90.0 or fnum(row.get("last_vllm_requests_running")) > 0.0:
        return("busy","busy")
    return("idle","idle")


def normalize_node(node: str, row: dict[str,Any]) -> dict[str,Any]:
    state,label = node_state(row)
    return({
        "node": node,
        "state": state,
        "state_label": label,
        "sample_count": int(fnum(row.get("sample_count"))),
        "last_iso_ts": row.get("last_iso_ts",""),
        "gpu_pct": fnum(row.get("last_gpu_util_pct")),
        "gpu_temp_c": fnum(row.get("last_gpu_temp_c")),
        "gpu_power_w": fnum(row.get("last_gpu_power_w")),
        "thermal_max_c": fnum(row.get("last_thermal_max_c")),
        "cpu_pct": fnum(row.get("last_cpu_util_pct")),
        "mem_pct": fnum(row.get("last_mem_used_pct")),
        "vllm_running": fnum(row.get("last_vllm_requests_running")),
        "vllm_waiting": fnum(row.get("last_vllm_requests_waiting")),
        "kv_pct": fnum(row.get("last_vllm_kv_cache_pct")),
        "gateway_up": fnum(row.get("last_ds4_gateway_up")) > 0.0,
        "gateway_active": fnum(row.get("last_ds4_gateway_active")) > 0.0,
        "local_q_depth": fnum(row.get("last_local_queue_depth")),
        "error": str(row.get("error","")),
    })


def build_snapshot(summary_path: str) -> dict[str,Any]:
    path = Path(summary_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return({"ok":False,"summary_path":str(path),"updated_iso":"","error":str(exc),"nodes":[]})
    nodes = [normalize_node(node,row) for node,row in sorted(raw.get("nodes",{}).items()) if isinstance(row,dict)]
    reachable = [node for node in nodes if node["state"] != "down"]
    queue = raw.get("queue",{}) if isinstance(raw.get("queue"),dict) else {}
    return({
        "ok": True,
        "summary_path": str(path),
        "updated_iso": raw.get("updated_iso",""),
        "updated_unix": raw.get("updated_unix",0),
        "age_s": max(0,int(time.time()) - int(fnum(raw.get("updated_unix")))),
        "nodes": nodes,
        "reachable_nodes": len(reachable),
        "busy_gpu_nodes": sum(1 for node in reachable if node["gpu_pct"] >= 90.0),
        "hot_nodes": sum(1 for node in reachable if node["state"] == "hot"),
        "vllm_running": sum(node["vllm_running"] for node in reachable),
        "vllm_waiting": sum(node["vllm_waiting"] for node in reachable),
        "max_kv_pct": max([node["kv_pct"] for node in reachable] or [0.0]),
        "queue_depth": fnum(queue.get("local_queue_depth",0.0)),
    })


def make_handler(summary_path: str) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/","/index.html"):
                self._send(200,"text/html; charset=utf-8",DASHBOARD_HTML.encode("utf-8"))
            elif path == "/api/summary":
                payload = json.dumps(build_snapshot(summary_path),sort_keys=True).encode("utf-8")
                self._send(200,"application/json",payload)
            elif path == "/healthz":
                self._send(200,"text/plain; charset=utf-8",b"ok\n")
            else:
                self._send(404,"text/plain; charset=utf-8",b"not found\n")
        def log_message(self, fmt: str, *args: Any) -> None:
            return
        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return(DashboardHandler)


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host,args.port),make_handler(args.summary_json))
    print("serving Spark telemetry dashboard on http://%s:%d" % (args.host,args.port),flush=True)
    server.serve_forever()
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
