#!/usr/bin/env python3
"""Serve a tiny local Spark telemetry dashboard."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_SUMMARY_JSON = "/tmp/ds4_telemetry/mac/cluster_summary.json"
DEFAULT_NODES_DIR = "/tmp/ds4_telemetry/mac/nodes"
DEFAULT_HISTORY_LIMIT = 720
HISTORY_METRICS = [
    {"key": "gpu_pct", "label": "GPU", "field": "gpu_util_pct", "unit": "%"},
    {"key": "kv_pct", "label": "KV", "field": "vllm_kv_cache_pct", "unit": "%"},
    {"key": "cpu_pct", "label": "CPU", "field": "cpu_util_pct", "unit": "%"},
    {"key": "mem_pct", "label": "MEM", "field": "mem_used_pct", "unit": "%"},
    {"key": "temp_c", "label": "TEMP", "field": "gpu_temp_c", "unit": "C"},
    {"key": "power_w", "label": "PWR", "field": "gpu_power_w", "unit": "W"},
    {"key": "vllm_running", "label": "RUN", "field": "vllm_requests_running", "unit": ""},
    {"key": "vllm_waiting", "label": "WAIT", "field": "vllm_requests_waiting", "unit": ""},
    {"key": "queue_depth", "label": "QUEUE", "field": "local_queue_depth", "unit": ""},
    {"key": "tok_s", "label": "TOK/S", "field": "vllm_tokens_per_s", "unit": ""},
]
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
h1{font-size:22px;line-height:1.1;margin:0}.meta{color:var(--muted);text-align:right;line-height:1.5}.summary{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:10px;margin-bottom:14px}
.metric,.card{background:var(--panel);border:1px solid var(--line);border-radius:8px}.metric{padding:12px}.label{color:var(--muted);font-size:12px}.value{font-size:23px;font-weight:700;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}.card{padding:12px;min-height:150px;cursor:pointer}.card.selected{border-color:var(--busy);box-shadow:0 0 0 1px var(--busy)}.card header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
.node{font-size:18px;font-weight:700}.pill{border-radius:999px;padding:3px 8px;font-size:12px;font-weight:700;color:#111316;background:var(--muted)}.busy .pill{background:var(--busy)}.idle .pill{background:var(--ok)}.warn .pill,.hot .pill{background:var(--warn)}.down .pill{background:var(--bad)}
.bars{display:grid;gap:8px}.barrow{display:grid;grid-template-columns:54px 1fr 48px;align-items:center;gap:8px;color:var(--muted)}.track{height:8px;background:#0d0f12;border-radius:999px;overflow:hidden}.fill{height:100%;width:0;background:var(--ok)}.busy .gpu .fill,.busy .kv .fill{background:var(--busy)}.warn .fill,.hot .fill{background:var(--warn)}.down .fill{background:var(--bad)}
.details{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-top:10px;color:var(--muted)}.details b{color:var(--text);font-weight:600}.error{margin-top:8px;color:var(--bad);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.history{margin-top:14px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}.history-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}.history-title{font-size:17px;font-weight:700}.modes{display:flex;gap:6px}.modes button{appearance:none;border:1px solid var(--line);background:#101318;color:var(--muted);border-radius:7px;padding:5px 10px;font:inherit;font-size:12px;font-weight:700;cursor:pointer}.modes button.active{background:var(--busy);border-color:var(--busy);color:#071018}.legend{display:flex;flex-wrap:wrap;gap:8px 14px;color:var(--muted);font-size:12px}.legend span{white-space:nowrap}.swatch{display:inline-block;width:9px;height:9px;border-radius:999px;margin-right:5px}.chart-wrap{height:270px;min-height:270px}.chart-wrap canvas{display:block;width:100%;height:100%}.empty{color:var(--muted);padding:24px 0;text-align:center}
@media (max-width:720px){main{padding:12px}.top{align-items:flex-start;flex-direction:column}.meta{text-align:left}.summary{grid-template-columns:repeat(2,minmax(120px,1fr))}}
</style>
</head>
<body><main>
<div class="top"><h1>Spark Telemetry</h1><div class="meta"><div id="updated">loading</div><div id="source"></div></div></div>
<section class="summary" id="summary"></section>
<section class="grid" id="nodes"></section>
<section class="history" id="history"><div class="empty">select a spark</div></section>
</main>
<script>
const fmt=n=>Number.isFinite(Number(n))?Number(n).toFixed(0):"";
const pct=n=>Number.isFinite(Number(n))?Number(n).toFixed(0)+"%":"n/a";
const val=(n,s="")=>Number.isFinite(Number(n))?Number(n).toFixed(1)+s:"n/a";
let selectedNode="";
let lastHistory=null;
let selectedMode="queue";
const metricModes={queue:["vllm_running","vllm_waiting","queue_depth","tok_s","cpu_pct"],gpu:["gpu_pct","kv_pct","mem_pct","temp_c","power_w"]};
const modeLabels={queue:"Queue",gpu:"GPU"};
const modeColors={queue:["#00e5ff","#ff4d4d","#ffe156","#53d18a","#a78bfa"],gpu:["#2f80ed","#ff7a00","#00c853","#e040fb","#f4d35e"]};
function metric(label,value){return `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div></div>`}
function bar(label,value,cls,known=true){let width=known?Math.max(0,Math.min(100,Number(value)||0)):0;return `<div class="barrow ${cls}"><span>${label}</span><div class="track"><div class="fill" style="width:${width}%"></div></div><span>${known?pct(value):"n/a"}</span></div>`}
function card(n){let err=n.error||n.fetch_error||"";return `<article class="card ${n.state} ${n.node===selectedNode?"selected":""}" data-node="${n.node}"><header><div class="node">${n.node}</div><div class="pill">${n.state_label}</div></header><div class="bars">${bar("GPU",n.gpu_pct,"gpu")}${bar("KV",n.kv_pct,"kv",n.kv_known)}${bar("MEM",n.mem_pct,"mem")}</div><div class="details"><span>Temp <b>${fmt(n.gpu_temp_c)}C</b></span><span>Power <b>${fmt(n.gpu_power_w)}W</b></span><span>Run <b>${fmt(n.vllm_running)}/${fmt(n.vllm_waiting)}</b></span><span>Queue <b>${fmt(n.local_q_depth)}</b></span><span>CPU <b>${pct(n.cpu_pct)}</b></span><span>Gateway <b>${n.gateway_up?"up":"down"}</b></span><span>Tok/s <b>${val(n.tok_s)}</b></span></div>${err?`<div class="error">${err}</div>`:""}</article>`}
function wireCards(){document.querySelectorAll(".card[data-node]").forEach(el=>el.onclick=()=>{selectedNode=el.dataset.node;document.querySelectorAll(".card").forEach(c=>c.classList.toggle("selected",c.dataset.node===selectedNode));refreshHistory()})}
function modeButtons(){return `<div class="modes">${Object.keys(metricModes).map(k=>`<button class="${k===selectedMode?"active":""}" data-mode="${k}">${modeLabels[k]}</button>`).join("")}</div>`}
function wireModes(){document.querySelectorAll(".modes button").forEach(el=>el.onclick=()=>{selectedMode=el.dataset.mode;drawHistory(lastHistory)})}
function activeMetrics(data){let allowed=new Set(metricModes[selectedMode]||metricModes.queue);return data.metrics.filter(m=>allowed.has(m.key))}
function metricLast(metric,points){let p=points[points.length-1]||{};let v=Number(p[metric.key]);return Number.isFinite(v)?v:null}
function metricScale(metric,points){if(metric.key==="tok_s")return Math.max(50,...points.map(p=>Number(p.tok_s)||0))*1.2;let fixed={gpu_pct:100,kv_pct:100,cpu_pct:100,mem_pct:100,temp_c:100,power_w:100,vllm_running:64,vllm_waiting:64,queue_depth:128};return fixed[metric.key]||100}
function emaValues(points,key){let out=[],acc=null,alpha=0.34;points.forEach(p=>{let v=Number(p[key]);v=Number.isFinite(v)?v:0;acc=acc===null?v:((alpha*v)+((1-alpha)*acc));out.push(acc)});return out}
function drawHistory(data){lastHistory=data;let el=document.getElementById("history");if(!data||!data.ok||!data.points.length){el.innerHTML=`<div class="history-head"><div class="history-title">${selectedNode||"spark"}</div>${modeButtons()}</div><div class="empty">no history</div>`;wireModes();return}let metrics=activeMetrics(data);let colors=modeColors[selectedMode]||modeColors.queue;let legend=metrics.map((m,i)=>{let v=metricLast(m,data.points);return `<span><i class="swatch" style="background:${colors[i%colors.length]}"></i>${m.label} <b>${v===null?"n/a":val(v,m.unit)}</b></span>`}).join("");el.innerHTML=`<div class="history-head"><div><div class="history-title">${data.node}</div><div class="label">last hour · ${data.points.length} samples · EMA</div></div>${modeButtons()}</div><div class="legend">${legend}</div><div class="chart-wrap"><canvas id="chart"></canvas></div>`;wireModes();paintChart(data,metrics,colors)}
function paintChart(data,metrics,colors){let canvas=document.getElementById("chart");if(!canvas)return;metrics=metrics||activeMetrics(data);colors=colors||modeColors[selectedMode]||modeColors.queue;let rect=canvas.getBoundingClientRect();let dpr=window.devicePixelRatio||1;canvas.width=Math.max(1,Math.floor(rect.width*dpr));canvas.height=Math.max(1,Math.floor(rect.height*dpr));let ctx=canvas.getContext("2d");ctx.scale(dpr,dpr);let w=rect.width,h=rect.height,pad=28;ctx.clearRect(0,0,w,h);ctx.strokeStyle="#313943";ctx.lineWidth=1;for(let i=0;i<=4;i++){let y=pad+((h-(pad*2))*i/4);ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke()}let points=data.points;metrics.forEach((m,i)=>{let scale=metricScale(m,points);let vals=emaValues(points,m.key);ctx.strokeStyle=colors[i%colors.length];ctx.lineWidth=2.2;ctx.beginPath();vals.forEach((v,idx)=>{let x=pad+((w-(pad*2))*idx/Math.max(1,points.length-1));let y=h-pad-((h-(pad*2))*Math.max(0,Math.min(scale,v))/scale);if(idx===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.stroke()});ctx.fillStyle="#a8b1bb";ctx.font="12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif";ctx.fillText("now",w-pad-24,h-8);ctx.fillText("then",pad,h-8)}
async function refreshHistory(){if(!selectedNode)return;try{let r=await fetch(`/api/history?node=${encodeURIComponent(selectedNode)}`,{cache:"no-store"});drawHistory(await r.json())}catch(e){document.getElementById("history").innerHTML=`<div class="empty">history read failed</div>`}}
async function refresh(){try{let r=await fetch("/api/summary",{cache:"no-store"});let d=await r.json();if(!selectedNode&&d.nodes&&d.nodes.length)selectedNode=d.nodes[0].node;document.getElementById("updated").textContent="updated "+(d.updated_iso||"unknown");document.getElementById("source").textContent=d.summary_path||"";document.getElementById("summary").innerHTML=[metric("Busy GPUs",`${d.busy_gpu_nodes}/${d.reachable_nodes}`),metric("Run/Wait",`${fmt(d.vllm_running)}/${fmt(d.vllm_waiting)}`),metric("Max KV",d.kv_known?pct(d.max_kv_pct):"n/a"),metric("Hot Nodes",fmt(d.hot_nodes)),metric("Queue Depth",fmt(d.queue_depth)),metric("Tok/s",val(d.tok_s))].join("");document.getElementById("nodes").innerHTML=d.nodes.map(card).join("");wireCards();refreshHistory()}catch(e){document.getElementById("updated").textContent="dashboard read failed: "+e}}
window.addEventListener("resize",()=>{if(lastHistory)paintChart(lastHistory)});
refresh();setInterval(refresh,3000);
</script></body></html>
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary-json", default=DEFAULT_SUMMARY_JSON)
    p.add_argument("--nodes-dir", default=DEFAULT_NODES_DIR)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    return(p.parse_args())


def fnum(value: Any) -> float:
    try:
        return(float(value))
    except Exception:
        return(0.0)


def valid_node_name(node: str) -> bool:
    return(node.startswith("spark") and all(ch.isalnum() or ch in "-_" for ch in node))


def node_state(row: dict[str,Any]) -> tuple[str,str]:
    if int(fnum(row.get("sample_count"))) <= 0 or str(row.get("error","")) != "":
        return("down","down")
    if fnum(row.get("stale_data")) > 0.0 or str(row.get("fetch_error","")) != "":
        return("warn","stale")
    if fnum(row.get("last_gpu_temp_c")) >= 80.0 or fnum(row.get("last_thermal_max_c")) >= 85.0:
        return("hot","hot")
    if fnum(row.get("last_vllm_requests_waiting")) > 0.0 or fnum(row.get("last_vllm_kv_cache_pct")) >= 90.0:
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
        "last_sample_age_s": fnum(row.get("last_sample_age_s")),
        "gpu_pct": fnum(row.get("last_gpu_util_pct")),
        "gpu_temp_c": fnum(row.get("last_gpu_temp_c")),
        "gpu_power_w": fnum(row.get("last_gpu_power_w")),
        "thermal_max_c": fnum(row.get("last_thermal_max_c")),
        "cpu_pct": fnum(row.get("last_cpu_util_pct")),
        "mem_pct": fnum(row.get("last_mem_used_pct")),
        "vllm_running": fnum(row.get("last_vllm_requests_running")),
        "vllm_waiting": fnum(row.get("last_vllm_requests_waiting")),
        "vllm_metrics_up": fnum(row.get("last_vllm_metrics_up")) > 0.0,
        "kv_pct": fnum(row.get("last_vllm_kv_cache_pct")),
        "kv_known": fnum(row.get("last_vllm_metrics_up")) > 0.0,
        "tok_s": fnum(row.get("last_vllm_tokens_per_s")),
        "gateway_up": fnum(row.get("last_ds4_gateway_up")) > 0.0,
        "gateway_active": fnum(row.get("last_ds4_gateway_active")) > 0.0,
        "local_q_depth": fnum(row.get("last_local_queue_depth")),
        "error": str(row.get("error","")),
        "fetch_error": str(row.get("fetch_error","")),
    })


def node_metric_map(raw: Any) -> dict[str,float]:
    out: dict[str,float] = {}
    for item in str(raw or "").split(";"):
        if ":" not in item:
            continue
        key,value = item.split(":",1)
        key = key.strip()
        if key:
            out[key] = fnum(value)
    return(out)


def build_snapshot(summary_path: str) -> dict[str,Any]:
    path = Path(summary_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return({"ok":False,"summary_path":str(path),"updated_iso":"","error":str(exc),"nodes":[]})
    queue = raw.get("queue",{}) if isinstance(raw.get("queue"),dict) else {}
    queue_depth_by_node = node_metric_map(queue.get("local_queue_by_node",""))
    queue_running_by_node = node_metric_map(queue.get("local_queue_running_by_node",""))
    queue_queued_by_node = node_metric_map(queue.get("local_queue_queued_by_node",""))
    queue_tok_s_by_node = node_metric_map(queue.get("local_queue_completion_tok_s_by_node",""))
    nodes = [normalize_node(node,row) for node,row in sorted(raw.get("nodes",{}).items()) if isinstance(row,dict)]
    for node in nodes:
        name = str(node.get("node",""))
        if name in queue_depth_by_node:
            node["local_q_depth"] = queue_depth_by_node[name]
        if not node.get("vllm_metrics_up"):
            node["vllm_running"] = max(fnum(node.get("vllm_running")),queue_running_by_node.get(name,0.0))
            node["vllm_waiting"] = max(fnum(node.get("vllm_waiting")),queue_queued_by_node.get(name,0.0))
        node["tok_s"] = max(fnum(node.get("tok_s")),queue_tok_s_by_node.get(name,0.0))
    reachable = [node for node in nodes if node["state"] != "down"]
    known_kv = [node["kv_pct"] for node in reachable if node.get("kv_known")]
    tok_s = sum(fnum(node.get("tok_s")) for node in reachable)
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
        "kv_known": len(known_kv) > 0,
        "max_kv_pct": max(known_kv or [0.0]),
        "queue_depth": fnum(queue.get("local_queue_depth",0.0)),
        "tok_s": max(tok_s,fnum(queue.get("local_queue_completion_tok_s",0.0))),
    })


def history_limit(value: str | None) -> int:
    try:
        limit = int(value or str(DEFAULT_HISTORY_LIMIT))
    except ValueError:
        limit = DEFAULT_HISTORY_LIMIT
    return(max(1,min(2000,limit)))


def build_history(nodes_dir: str, node: str, limit: int = 360) -> dict[str,Any]:
    if not valid_node_name(node):
        return({"ok":False,"node":node,"error":"invalid node","metrics":HISTORY_METRICS,"points":[]})
    path = Path(nodes_dir) / ("%s.csv" % node)
    rows: deque[dict[str,str]] = deque(maxlen=limit)
    try:
        with path.open("r",encoding="utf-8",newline="") as fp:
            for row in csv.DictReader(fp):
                if row.get("iso_ts","") != "":
                    rows.append(row)
    except Exception as exc:
        return({"ok":False,"node":node,"history_path":str(path),"error":str(exc),"metrics":HISTORY_METRICS,"points":[]})
    points = []
    for row in rows:
        point: dict[str,Any] = {"iso_ts": row.get("iso_ts",""), "unix_ts": fnum(row.get("unix_ts"))}
        for metric in HISTORY_METRICS:
            point[metric["key"]] = fnum(row.get(metric["field"]))
        points.append(point)
    return({"ok":True,"node":node,"history_path":str(path),"metrics":HISTORY_METRICS,"points":points})


def make_handler(summary_path: str, nodes_dir: str) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/","/index.html"):
                self._send(200,"text/html; charset=utf-8",DASHBOARD_HTML.encode("utf-8"))
            elif path == "/api/summary":
                payload = json.dumps(build_snapshot(summary_path),sort_keys=True).encode("utf-8")
                self._send(200,"application/json",payload)
            elif path == "/api/history":
                qs = parse_qs(parsed.query)
                node = (qs.get("node") or [""])[0]
                limit = history_limit((qs.get("limit") or [""])[0])
                payload = json.dumps(build_history(nodes_dir,node,limit),sort_keys=True).encode("utf-8")
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
    server = ThreadingHTTPServer((args.host,args.port),make_handler(args.summary_json,args.nodes_dir))
    print("serving Spark telemetry dashboard on http://%s:%d" % (args.host,args.port),flush=True)
    server.serve_forever()
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
