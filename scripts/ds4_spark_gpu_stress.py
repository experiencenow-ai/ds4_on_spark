#!/usr/bin/env python3
"""Run a bounded CUDA stress load across Spark nodes and summarize power/thermal headroom."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import csv
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from typing import Dict, List, Tuple

try:
    from . import spark_telemetry_common as telemetry
except ImportError:
    import spark_telemetry_common as telemetry


CSV_FIELDS = [
    "run_id",
    "poll_index",
    "unix_ts",
    "iso_ts",
    "node",
    "gpu_index",
    "gpu_name",
    "gpu_util_pct",
    "gpu_mem_util_pct",
    "gpu_mem_used_mib",
    "gpu_mem_total_mib",
    "gpu_power_raw_w",
    "gpu_power_limit_w",
    "gpu_temp_c",
    "gpu_clock_sm_mhz",
    "gpu_clock_mem_mhz",
    "gpu_pstate",
    "error",
]

REMOTE_STRESS_SOURCE = r"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time

stop = False

def _stop(signum, frame):
    global stop
    stop = True

signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

p = argparse.ArgumentParser()
p.add_argument("--duration-s", type=float, required=True)
p.add_argument("--matrix-size", type=int, required=True)
p.add_argument("--dtype", choices=("float16", "bfloat16", "float32"), default="float16")
p.add_argument("--sync-every", type=int, default=8)
args = p.parse_args()

import torch

dtype = {
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
    "float32": torch.float32,
}[args.dtype]
torch.cuda.set_device(0)
torch.backends.cuda.matmul.allow_tf32 = True
torch.set_float32_matmul_precision("high")
n = args.matrix_size
a = torch.randn((n, n), device="cuda", dtype=dtype)
b = torch.randn((n, n), device="cuda", dtype=dtype)
c = torch.empty((n, n), device="cuda", dtype=dtype)
torch.cuda.synchronize()
start = time.time()
deadline = start + args.duration_s
iters = 0
try:
    while not stop and time.time() < deadline:
        torch.mm(a, b, out=c)
        iters += 1
        if iters % max(1, args.sync_every) == 0:
            torch.cuda.synchronize()
    torch.cuda.synchronize()
    status = "stopped" if stop else "completed"
except Exception as exc:
    status = "error"
    print(json.dumps({"status": status, "error": "%s: %s" % (type(exc).__name__, exc)}), flush=True)
    raise
elapsed = max(0.001, time.time() - start)
print(json.dumps({
    "status": status,
    "matrix_size": n,
    "dtype": args.dtype,
    "iterations": iters,
    "elapsed_s": round(elapsed, 3),
    "iterations_per_s": round(iters / elapsed, 3),
}), flush=True)
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nodes", default=telemetry.DEFAULT_NODE_TARGETS)
    p.add_argument("--duration-s", type=float, default=120.0)
    p.add_argument("--interval-s", type=float, default=2.0)
    p.add_argument("--matrix-size", type=int, default=16384)
    p.add_argument("--dtype", choices=("float16", "bfloat16", "float32"), default="float16")
    p.add_argument("--sync-every", type=int, default=8)
    p.add_argument("--runtime-python", default="~/standard-runtimes/vllm-0.21.0/bin/python")
    p.add_argument("--out-dir", default="/private/tmp/ds4_gpu_stress")
    p.add_argument("--run-id", default="")
    p.add_argument("--ssh-timeout-s", type=float, default=8.0)
    p.add_argument("--abort-temp-c", type=float, default=88.0)
    p.add_argument("--min-hot-util-pct", type=float, default=90.0)
    return p.parse_args()


def utc_iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def ssh(target: str, command: str, timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=%d" % max(1, int(timeout_s)),
            target,
            command,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(1.0, timeout_s),
        check=False,
    )


def remote_path_word(path: str) -> str:
    if path.startswith("~/"):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)


def start_node(
    node: str,
    target: str,
    run_id: str,
    remote_python: str,
    duration_s: float,
    matrix_size: int,
    dtype: str,
    sync_every: int,
    timeout_s: float,
) -> Tuple[str, str]:
    remote_dir = f"/tmp/ds4_gpu_stress_{run_id}"
    remote_dir_q = shlex.quote(remote_dir)
    code = base64.b64encode(REMOTE_STRESS_SOURCE.encode("utf-8")).decode("ascii")
    py_expr = "import base64; exec(base64.b64decode(%r).decode('utf-8'))" % code
    python_word = remote_path_word(remote_python)
    cmd = (
        "set -eu; "
        f"mkdir -p {remote_dir_q}; "
        f"if [ ! -x {python_word} ]; then echo missing-runtime:{python_word} >&2; exit 12; fi; "
        f"nohup {python_word} -c {shlex.quote(py_expr)} "
        f"--duration-s {duration_s:.3f} --matrix-size {int(matrix_size)} --dtype {shlex.quote(dtype)} --sync-every {int(sync_every)} "
        f">{remote_dir_q}/stress.log 2>&1 & "
        f"pid=$!; echo $pid >{remote_dir_q}/stress.pid; echo $pid"
    )
    proc = ssh(target, cmd, timeout_s)
    if proc.returncode != 0:
        return node, (proc.stderr.strip() or proc.stdout.strip() or f"ssh exited {proc.returncode}")
    return node, ""


def stop_node(node: str, target: str, run_id: str, timeout_s: float) -> Tuple[str, str]:
    remote_dir = f"/tmp/ds4_gpu_stress_{run_id}"
    remote_dir_q = shlex.quote(remote_dir)
    cmd = (
        f"if [ -r {remote_dir_q}/stress.pid ]; then "
        f"pid=$(cat {remote_dir_q}/stress.pid); kill -TERM \"$pid\" 2>/dev/null || true; "
        "fi"
    )
    proc = ssh(target, cmd, timeout_s)
    return node, proc.stderr.strip() if proc.returncode != 0 else ""


def fetch_log(node: str, target: str, run_id: str, timeout_s: float) -> Tuple[str, str]:
    remote_dir = shlex.quote(f"/tmp/ds4_gpu_stress_{run_id}")
    proc = ssh(target, f"test -r {remote_dir}/stress.log && tail -n 20 {remote_dir}/stress.log || true", timeout_s)
    return node, (proc.stdout + proc.stderr).strip()


def poll_node(node: str, target: str, timeout_s: float) -> Tuple[str, List[Dict[str, str]], str]:
    fields = telemetry.GPU_FIELDS
    proc = ssh(target, telemetry.nvidia_smi_query(fields), timeout_s)
    if proc.returncode != 0:
        return node, [], proc.stderr.strip() or proc.stdout.strip() or f"nvidia-smi exited {proc.returncode}"
    rows = [telemetry.parse_gpu_line(line, fields) for line in proc.stdout.splitlines() if line.strip()]
    return node, rows, ""


def sample_row(run_id: str, poll_index: int, now: float, node: str, gpu_index: int, gpu: Dict[str, str]) -> Dict[str, object]:
    return {
        "run_id": run_id,
        "poll_index": poll_index,
        "unix_ts": int(now),
        "iso_ts": utc_iso(now),
        "node": node,
        "gpu_index": gpu_index,
        "gpu_name": gpu.get("name", ""),
        "gpu_util_pct": telemetry.num(gpu.get("utilization.gpu", "0")),
        "gpu_mem_util_pct": telemetry.num(gpu.get("utilization.memory", "0")),
        "gpu_mem_used_mib": telemetry.num(gpu.get("memory.used", "0")),
        "gpu_mem_total_mib": telemetry.num(gpu.get("memory.total", "0")),
        "gpu_power_raw_w": telemetry.num(gpu.get("power.draw", "0")),
        "gpu_power_limit_w": telemetry.num(gpu.get("power.limit", "0")),
        "gpu_temp_c": telemetry.num(gpu.get("temperature.gpu", "0")),
        "gpu_clock_sm_mhz": telemetry.num(gpu.get("clocks.gr", "0")),
        "gpu_clock_mem_mhz": telemetry.num(gpu.get("clocks.mem", "0")),
        "gpu_pstate": gpu.get("pstate", ""),
        "error": "",
    }


def error_row(run_id: str, poll_index: int, now: float, node: str, error: str) -> Dict[str, object]:
    row = {key: "" for key in CSV_FIELDS}
    row.update({
        "run_id": run_id,
        "poll_index": poll_index,
        "unix_ts": int(now),
        "iso_ts": utc_iso(now),
        "node": node,
        "gpu_index": -1,
        "error": error,
    })
    return row


def summarize(args: argparse.Namespace, run_id: str, samples: List[Dict[str, object]], start_errors: Dict[str, str], logs: Dict[str, str], aborted: str) -> Dict[str, object]:
    by_node: Dict[str, List[Dict[str, object]]] = {}
    by_poll: Dict[int, List[Dict[str, object]]] = {}
    for row in samples:
        if row.get("error"):
            continue
        by_node.setdefault(str(row["node"]), []).append(row)
        by_poll.setdefault(int(row["poll_index"]), []).append(row)
    nodes: Dict[str, object] = {}
    for node, rows in sorted(by_node.items()):
        utils = [float(row["gpu_util_pct"]) for row in rows]
        powers = [float(row["gpu_power_raw_w"]) for row in rows]
        temps = [float(row["gpu_temp_c"]) for row in rows]
        hot = [value for value in utils if value >= args.min_hot_util_pct]
        nodes[node] = {
            "samples": len(rows),
            "avg_gpu_util_pct": round(sum(utils) / len(utils), 2) if utils else 0.0,
            "max_gpu_util_pct": round(max(utils), 2) if utils else 0.0,
            "pct_samples_hot": round(100.0 * len(hot) / len(utils), 2) if utils else 0.0,
            "avg_power_raw_w": round(sum(powers) / len(powers), 2) if powers else 0.0,
            "max_power_raw_w": round(max(powers), 2) if powers else 0.0,
            "avg_temp_c": round(sum(temps) / len(temps), 2) if temps else 0.0,
            "max_temp_c": round(max(temps), 2) if temps else 0.0,
            "last_gpu_util_pct": round(utils[-1], 2) if utils else 0.0,
            "last_power_raw_w": round(powers[-1], 2) if powers else 0.0,
            "last_temp_c": round(temps[-1], 2) if temps else 0.0,
            "stress_log_tail": logs.get(node, ""),
        }
    total_power_by_poll = [sum(float(row["gpu_power_raw_w"]) for row in rows) for rows in by_poll.values()]
    return {
        "run_id": run_id,
        "nodes_requested": [node for node, _ in telemetry.parse_node_targets(args.nodes)],
        "duration_s": args.duration_s,
        "interval_s": args.interval_s,
        "matrix_size": args.matrix_size,
        "dtype": args.dtype,
        "abort_temp_c": args.abort_temp_c,
        "aborted": bool(aborted),
        "abort_reason": aborted,
        "start_errors": start_errors,
        "sample_count": len(samples),
        "nodes": nodes,
        "peak_total_power_raw_w": round(max(total_power_by_poll), 2) if total_power_by_poll else 0.0,
        "avg_total_power_raw_w": round(sum(total_power_by_poll) / len(total_power_by_poll), 2) if total_power_by_poll else 0.0,
        "updated_iso": telemetry.utc_iso(),
    }


def main() -> int:
    args = parse_args()
    run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    nodes = telemetry.parse_node_targets(args.nodes)
    if len(nodes) == 0:
        raise SystemExit("no nodes selected")
    out_dir = os.path.join(args.out_dir, run_id)
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "gpu_samples.csv")
    summary_path = os.path.join(out_dir, "summary.json")
    start_errors: Dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(nodes)) as pool:
        futs = [
            pool.submit(
                start_node,
                node,
                target,
                run_id,
                args.runtime_python,
                args.duration_s,
                args.matrix_size,
                args.dtype,
                args.sync_every,
                args.ssh_timeout_s,
            )
            for node, target in nodes
        ]
        for fut in concurrent.futures.as_completed(futs):
            node, error = fut.result()
            if error:
                start_errors[node] = error
    if start_errors:
        telemetry.write_json_atomic(summary_path, summarize(args, run_id, [], start_errors, {}, "start-failed"))
        print(f"start failed; summary={summary_path}", file=sys.stderr)
        return 1
    samples: List[Dict[str, object]] = []
    aborted = ""
    start = time.time()
    with open(csv_path, "w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        poll_index = 0
        while True:
            now = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(nodes)) as pool:
                futs = [pool.submit(poll_node, node, target, args.ssh_timeout_s) for node, target in nodes]
                for fut in concurrent.futures.as_completed(futs):
                    node, rows, error = fut.result()
                    if error:
                        row = error_row(run_id, poll_index, now, node, error)
                        writer.writerow(row)
                        samples.append(row)
                        continue
                    for gpu_index, gpu in enumerate(rows):
                        row = sample_row(run_id, poll_index, now, node, gpu_index, gpu)
                        writer.writerow(row)
                        samples.append(row)
                        if float(row["gpu_temp_c"]) >= args.abort_temp_c:
                            aborted = f"{node} temp {row['gpu_temp_c']} >= {args.abort_temp_c}"
            fp.flush()
            if aborted:
                break
            if time.time() - start >= args.duration_s:
                break
            poll_index += 1
            time.sleep(max(0.1, args.interval_s))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(nodes)) as pool:
        list(concurrent.futures.as_completed([pool.submit(stop_node, node, target, run_id, args.ssh_timeout_s) for node, target in nodes]))
    time.sleep(1.0)
    logs: Dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(nodes)) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(fetch_log, node, target, run_id, args.ssh_timeout_s) for node, target in nodes]):
            node, text = fut.result()
            logs[node] = text
    summary = summarize(args, run_id, samples, start_errors, logs, aborted)
    telemetry.write_json_atomic(summary_path, summary)
    print(json.dumps({"run_id": run_id, "out_dir": out_dir, "summary": summary_path, "aborted": bool(aborted), "peak_total_power_raw_w": summary["peak_total_power_raw_w"]}, sort_keys=True))
    return 2 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
