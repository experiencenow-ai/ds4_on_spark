#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
import argparse
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any

V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V2_ROOT / "src"))

from ds4_infer.profiles import ModelProfile, ProfileRegistry
from ds4_infer.queue import InferenceQueue, queue_depths
from ds4_infer.runners import SparkHttpRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.topology import SparkTopology

LANE_PROFILES = (
    "qwen3_6_27b_fp8_efficient_v1",
    "dsv4_vllm_mtp_smartest_v1",
    "dsv4_antirez_smart_v1",
)
GROUP_INGRESS = {"spark4+spark5": "spark5"}


@dataclass(frozen=True)
class Lane:
    name: str
    profile: ModelProfile
    queue_nodes: tuple[str, ...]
    gpu_nodes: tuple[str, ...]
    target_depth: int


@dataclass(frozen=True)
class LoadPoint:
    target_depth: int
    worker_concurrency: int


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or f"sat-{int(time.time())}"
    out_dir = Path(args.out_dir or f"/tmp/ds4_queue_saturation_{run_id}")
    queue_dir = Path(args.queue_dir or out_dir / "queue")
    if args.stress_ladder:
        return run_stress_suite(args, run_id, out_dir)
    summary = run_saturation_phase(args, run_id, out_dir, queue_dir, args.target_depth, args.worker_concurrency)
    return 0 if summary["ok"] else 2


def run_stress_suite(args: argparse.Namespace, run_id: str, out_dir: Path) -> int:
    load_points = parse_stress_ladder(args.stress_ladder)
    suite: dict[str, Any] = {"format": "ds4-queue-stress-suite-v1", "run_id": run_id, "load_points": [load_point_public(item) for item in load_points], "phases": []}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stress_plan.json").write_text(json.dumps(suite, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "stress_planned", **suite}, sort_keys=True), flush=True)
    if args.dry_run:
        return 0
    for idx, load_point in enumerate(load_points):
        phase_id = f"{run_id}-d{load_point.target_depth}-c{load_point.worker_concurrency}"
        phase_out = out_dir / f"phase_{idx:02d}_d{load_point.target_depth}_c{load_point.worker_concurrency}"
        phase_queue = phase_out / "queue"
        phase_args = copy.copy(args)
        phase_args.target_depth = load_point.target_depth
        phase_args.worker_concurrency = load_point.worker_concurrency
        phase_summary = run_saturation_phase(phase_args, phase_id, phase_out, phase_queue, load_point.target_depth, load_point.worker_concurrency)
        phase_summary["phase_id"] = phase_id
        phase_summary["load_point"] = load_point_public(load_point)
        suite["phases"].append(phase_summary)
        (out_dir / "stress_summary.json").write_text(json.dumps(finalize_stress_suite(suite), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    final = finalize_stress_suite(suite)
    (out_dir / "stress_summary.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(final, sort_keys=True), flush=True)
    return 0 if final["ok"] else 2


def run_saturation_phase(args: argparse.Namespace, run_id: str, out_dir: Path, queue_dir: Path, target_depth: int, worker_concurrency: int) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["DS4_SPARK_NODE_MAP_JSON"] = json.dumps(GROUP_INGRESS, sort_keys=True)
    registry = ProfileRegistry.load(args.profiles_dir)
    topology = SparkTopology.load(args.topology)
    lanes = build_lanes(registry, topology, target_depth)
    gpu_nodes = sorted({node for lane in lanes for node in lane.gpu_nodes})
    plan = {"run_id": run_id, "duration_s": args.duration_s, "target_depth": target_depth, "worker_concurrency": worker_concurrency, "gpu_nodes": gpu_nodes, "lanes": [lane_public(lane) for lane in lanes]}
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "planned", **plan}, sort_keys=True), flush=True)
    if args.dry_run:
        return {"format": "ds4-queue-saturation-summary-v1", "ok": True, "dry_run": True, "plan": plan}
    queue = InferenceQueue(queue_dir)
    stats: dict[str, Any] = {"submitted": 0, "workers": {}, "submitter_errors": []}
    lock = threading.Lock()
    stop_submit = threading.Event()
    stop_workers = threading.Event()
    monitor_stop = threading.Event()
    monitor_thread = threading.Thread(target=monitor_gpus, args=(gpu_nodes, out_dir / "gpu_samples.jsonl", args.sample_interval_s, monitor_stop), daemon=True)
    monitor_thread.start()
    worker_threads = [
        threading.Thread(target=worker_loop, args=(queue, registry, lane, node_id, args, stop_workers, lock, stats), daemon=True)
        for lane in lanes
        for node_id in lane.queue_nodes
    ]
    for thread in worker_threads:
        thread.start()
    submit_thread = threading.Thread(target=submit_loop, args=(queue, registry, topology, lanes, args, run_id, stop_submit, lock, stats), daemon=True)
    submit_thread.start()
    time.sleep(args.duration_s)
    stop_submit.set()
    submit_thread.join(timeout=30)
    drained = wait_for_drain(queue.db_path, args.drain_timeout_s)
    stop_workers.set()
    for thread in worker_threads:
        thread.join(timeout=args.request_timeout_s + 20)
    monitor_stop.set()
    monitor_thread.join(timeout=10)
    summary = summarize(out_dir, queue.db_path, args, drained, stats)
    summary["load_point"] = {"target_depth": target_depth, "worker_concurrency": worker_concurrency}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keep the 7 production Sparks saturated through the v2 queue")
    parser.add_argument("--profiles-dir", default=str(V2_ROOT / "profiles" / "models"))
    parser.add_argument("--topology", default=str(V2_ROOT / "profiles" / "topology" / "static_sparks.json"))
    parser.add_argument("--out-dir")
    parser.add_argument("--queue-dir")
    parser.add_argument("--run-id")
    parser.add_argument("--duration-s", type=int, default=300)
    parser.add_argument("--target-depth", type=int, default=4)
    parser.add_argument("--worker-concurrency", type=int, default=4)
    parser.add_argument("--stress-ladder", default="", help="Optional comma-separated target_depth x worker_concurrency ladder, for example 1x1,2x2,4x4,8x8")
    parser.add_argument("--request-timeout-s", type=int, default=240)
    parser.add_argument("--drain-timeout-s", type=int, default=300)
    parser.add_argument("--sample-interval-s", type=float, default=1.0)
    parser.add_argument("--active-threshold", type=float, default=50.0)
    parser.add_argument("--required-active-s", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.duration_s < 1:
        raise ValueError("duration-s must be positive")
    if args.target_depth < 1:
        raise ValueError("target-depth must be positive")
    if args.worker_concurrency < 1:
        raise ValueError("worker-concurrency must be positive")
    return args


def parse_stress_ladder(value: str) -> list[LoadPoint]:
    out: list[LoadPoint] = []
    for item in value.split(","):
        raw = item.strip().lower()
        if not raw:
            continue
        if "x" in raw:
            left, right = raw.split("x", 1)
            depth = int(left)
            concurrency = int(right)
        elif ":" in raw:
            left, right = raw.split(":", 1)
            depth = int(left)
            concurrency = int(right)
        else:
            depth = int(raw)
            concurrency = depth
        if depth < 1 or concurrency < 1:
            raise ValueError("stress ladder values must be positive")
        out.append(LoadPoint(target_depth=depth, worker_concurrency=concurrency))
    if not out:
        raise ValueError("stress ladder cannot be empty")
    return out


def load_point_public(item: LoadPoint) -> dict[str, int]:
    return {"target_depth": item.target_depth, "worker_concurrency": item.worker_concurrency}


def build_lanes(registry: ProfileRegistry, topology: SparkTopology, target_depth: int) -> list[Lane]:
    lanes: list[Lane] = []
    for profile_id in LANE_PROFILES:
        profile = registry.get(profile_id)
        grouped = topology.profile_node_groups.get(profile.profile_id)
        if grouped:
            queue_nodes = ("+".join(grouped),)
            gpu_nodes = grouped
        else:
            nodes = topology.nodes_for_profile(profile)
            queue_nodes = tuple(node.node_id for node in nodes if "production" in node.roles or "urgent" in node.roles)
            gpu_nodes = queue_nodes
        if not queue_nodes:
            raise ValueError(f"profile {profile_id} has no production lane")
        per_queue_multiplier = max(1, len(gpu_nodes) // max(1, len(queue_nodes)))
        lanes.append(Lane(name=profile_id.replace("_v1", ""), profile=profile, queue_nodes=queue_nodes, gpu_nodes=gpu_nodes, target_depth=(target_depth * per_queue_multiplier)))
    return lanes


def lane_public(lane: Lane) -> dict[str, Any]:
    return {"name": lane.name, "profile_id": lane.profile.profile_id, "model_id": lane.profile.model_id, "queue_nodes": list(lane.queue_nodes), "gpu_nodes": list(lane.gpu_nodes), "target_depth": lane.target_depth}


def submit_loop(queue: InferenceQueue, registry: ProfileRegistry, topology: SparkTopology, lanes: list[Lane], args: argparse.Namespace, run_id: str, stop: threading.Event, lock: threading.Lock, stats: dict[str, Any]) -> None:
    seq = 0
    while not stop.is_set():
        try:
            counts = queue_depths(queue.db_path, request_kind="model")
            requests: list[InferenceRequest] = []
            for lane in lanes:
                missing = 0
                for queue_node in lane.queue_nodes:
                    missing += max(0, lane.target_depth - counts.get(queue_node, 0))
                for _ in range(missing):
                    seq += 1
                    requests.append(make_request(lane.profile, f"{run_id}-{seq:08d}"))
            if requests:
                queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id=f"{run_id}-{seq:08d}")
                with lock:
                    stats["submitted"] += len(requests)
            time.sleep(0.5)
        except Exception as exc:
            with lock:
                stats["submitter_errors"].append(str(exc))
            time.sleep(1.0)


def make_request(profile: ModelProfile, request_id: str) -> InferenceRequest:
    if profile.profile_id == "dsv4_antirez_smart_v1":
        chat = False
        job_class = "analysis"
        prompt = "Write a dense DS4 queue saturation paragraph with numbered observations. Continue until the token budget is used."
        payload_input = {"prompt": prompt, "suffix": prompt}
    elif profile.profile_id == "dsv4_vllm_mtp_smartest_v1":
        chat = True
        job_class = "tool_chat"
        payload_input = {"messages": [{"role": "user", "content": "Produce a detailed DS4 queue saturation analysis. Keep generating until the token budget is used."}]}
    else:
        chat = True
        job_class = "triage"
        payload_input = {"messages": [{"role": "user", "content": "Produce a detailed DS4 queue triage note. Keep generating until the token budget is used."}]}
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": None,
            "chat": chat,
            "immediate": False,
            "job_class": job_class,
            "max_output_tokens": 512,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": payload_input,
            "output_contract": {"format": "text"},
            "model_pin": {"profile_id": profile.profile_id},
        }
    )


def worker_loop(queue: InferenceQueue, registry: ProfileRegistry, lane: Lane, node_id: str, args: argparse.Namespace, stop: threading.Event, lock: threading.Lock, stats: dict[str, Any]) -> None:
    runner = SparkHttpRunner(timeout_s=args.request_timeout_s)
    worker_id = f"saturation-{node_id}-{threading.get_ident()}"
    while not stop.is_set() or queue_depths(queue.db_path, request_kind="model").get(node_id, 0) > 0:
        result = queue.work(registry=registry, runner=runner, node_id=node_id, limit=lane.target_depth, concurrency=args.worker_concurrency, worker_id=worker_id, lease_ttl_s=max(args.request_timeout_s * 2, 60), heartbeat_interval_s=5)
        with lock:
            item = stats["workers"].setdefault(node_id, {"claimed": 0, "completed": 0, "failed": 0, "lost": 0})
            item["claimed"] += int(result.get("claimed_count", 0))
            item["completed"] += int(result.get("completed_count", 0))
            item["failed"] += int(result.get("failed_count", 0))
            item["lost"] += int(result.get("lost_lease_count", 0))
        if int(result.get("claimed_count", 0)) == 0:
            time.sleep(0.2)


def wait_for_drain(db_path: Path, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if sum(queue_depths(db_path, request_kind="model").values()) == 0:
            return True
        time.sleep(1)
    return sum(queue_depths(db_path, request_kind="model").values()) == 0


def monitor_gpus(nodes: list[str], path: Path, interval_s: float, stop: threading.Event) -> None:
    start = time.time()
    with path.open("w", encoding="utf-8") as handle:
        while not stop.is_set():
            sample_start = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(nodes)) as pool:
                records = dict(zip(nodes, pool.map(sample_gpu, nodes)))
            vector = [records[node].get("gpu_util") if records[node].get("ok") else None for node in nodes]
            handle.write(json.dumps({"t": sample_start, "elapsed_s": round(sample_start - start, 3), "gpu_nodes": nodes, "gpu_util_vector": vector, "nodes": records}, sort_keys=True) + "\n")
            handle.flush()
            stop.wait(max(0.1, interval_s - (time.time() - sample_start)))


def sample_gpu(node: str) -> dict[str, Any]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", node, "nvidia-smi --query-gpu=utilization.gpu,power.draw --format=csv,noheader,nounits"]
    start = time.time()
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False)
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr.strip()[-400:], "elapsed_s": round(time.time() - start, 3)}
    line = completed.stdout.splitlines()[0] if completed.stdout.splitlines() else ""
    parts = [part.strip() for part in line.split(",")]
    return {"ok": True, "gpu_util": parse_float(parts[0]), "power_w": parse_float(parts[1]) if len(parts) > 1 else None, "elapsed_s": round(time.time() - start, 3)}


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def summarize(out_dir: Path, db_path: Path, args: argparse.Namespace, drained: bool, stats: dict[str, Any]) -> dict[str, Any]:
    gpu = summarize_gpu(out_dir / "gpu_samples.jsonl", args.active_threshold, args.sample_interval_s)
    gpu_vector = summarize_gpu_vector(out_dir / "gpu_samples.jsonl", gpu)
    queue = summarize_queue(db_path)
    throughput = summarize_throughput(db_path)
    failed_requests = int(queue["states"].get("failed", 0))
    active_ok = all(item["active_seconds"] >= args.required_active_s for item in gpu.values()) if args.required_active_s > 0 else True
    ok = drained and failed_requests == 0 and not stats.get("submitter_errors") and active_ok
    return {"format": "ds4-queue-saturation-summary-v1", "ok": ok, "drained": drained, "required_active_s": args.required_active_s, "active_threshold": args.active_threshold, "throughput": throughput, "gpu": gpu, "gpu_vector": gpu_vector, "queue": queue, "stats": stats}


def summarize_gpu(path: Path, threshold: float, interval_s: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for node, item in record.get("nodes", {}).items():
            stats = out.setdefault(node, {"samples": 0, "ok_samples": 0, "active_samples": 0, "active_seconds": 0.0, "max_gpu": 0.0, "sum_gpu": 0.0})
            stats["samples"] += 1
            if item.get("ok"):
                stats["ok_samples"] += 1
                gpu = float(item.get("gpu_util") or 0.0)
                stats["sum_gpu"] += gpu
                stats["max_gpu"] = max(stats["max_gpu"], gpu)
                if gpu >= threshold:
                    stats["active_samples"] += 1
                    stats["active_seconds"] += interval_s
    for stats in out.values():
        stats["active_seconds"] = round(float(stats["active_seconds"]), 3)
        stats["avg_gpu"] = round(float(stats["sum_gpu"]) / max(1, int(stats["ok_samples"])), 3)
        del stats["sum_gpu"]
    return out


def summarize_gpu_vector(path: Path, gpu: dict[str, Any]) -> dict[str, Any]:
    order: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            raw_nodes = record.get("gpu_nodes")
            if isinstance(raw_nodes, list) and raw_nodes:
                order = [str(node) for node in raw_nodes]
                break
    if not order:
        order = sorted(gpu)
    return {
        "nodes": order,
        "avg_gpu": [gpu.get(node, {}).get("avg_gpu") for node in order],
        "max_gpu": [gpu.get(node, {}).get("max_gpu") for node in order],
        "active_seconds": [gpu.get(node, {}).get("active_seconds") for node in order],
    }


def summarize_queue(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"states": {}, "profiles": {}, "nodes": {}, "requests": 0}
    with sqlite3.connect(db_path) as conn:
        states = dict(conn.execute("select state, count(*) from requests group by state").fetchall())
        profiles = dict(conn.execute("select selected_profile_id, count(*) from requests group by selected_profile_id").fetchall())
        nodes = dict(conn.execute("select selected_node_id, count(*) from requests group by selected_node_id").fetchall())
    return {"states": {str(k): int(v) for k, v in states.items()}, "profiles": {str(k): int(v) for k, v in profiles.items()}, "nodes": {str(k): int(v) for k, v in nodes.items()}, "requests": sum(int(v) for v in states.values())}


def summarize_throughput(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return empty_throughput()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            select selected_profile_id, selected_node_id, started_at, completed_at, result_json
            from requests
            where state = 'completed' and result_json is not null
            """
        ).fetchall()
    if not rows:
        return empty_throughput()
    tokens = actual_tokens = estimated_tokens = requests = 0
    started: list[float] = []
    completed: list[float] = []
    per_profile: dict[str, dict[str, Any]] = {}
    per_node: dict[str, dict[str, Any]] = {}
    for profile_id, node_id, started_at, completed_at, result_json in rows:
        result = json.loads(str(result_json))
        token_count, estimated = completion_tokens(result)
        tokens += token_count
        if estimated:
            estimated_tokens += token_count
        else:
            actual_tokens += token_count
        requests += 1
        if started_at is not None:
            started.append(float(started_at))
        if completed_at is not None:
            completed.append(float(completed_at))
        add_throughput_group(per_profile, str(profile_id), token_count, estimated)
        add_throughput_group(per_node, str(node_id), token_count, estimated)
    window_s = (max(completed) - min(started)) if started and completed else 0.0
    tok_s = float(tokens) / window_s if window_s > 0 else 0.0
    return {
        "completed_requests": requests,
        "completion_tokens": tokens,
        "actual_completion_tokens": actual_tokens,
        "estimated_completion_tokens": estimated_tokens,
        "measurement_window_s": round(window_s, 6),
        "aggregate_completion_tok_s": round(tok_s, 6),
        "per_profile": finalize_throughput_groups(per_profile, window_s),
        "per_node": finalize_throughput_groups(per_node, window_s),
    }


def empty_throughput() -> dict[str, Any]:
    return {"completed_requests": 0, "completion_tokens": 0, "actual_completion_tokens": 0, "estimated_completion_tokens": 0, "measurement_window_s": 0.0, "aggregate_completion_tok_s": 0.0, "per_profile": {}, "per_node": {}}


def completion_tokens(result: dict[str, Any]) -> tuple[int, bool]:
    usage = result.get("usage", {}) if isinstance(result, dict) else {}
    if isinstance(usage, dict):
        for key in ("completion_tokens", "output_tokens", "generated_tokens", "num_generated_tokens", "completionTokenCount"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value), False
    output = result.get("output", {}) if isinstance(result, dict) else {}
    text = output.get("text", "") if isinstance(output, dict) else ""
    return max(0, len(str(text).encode("utf-8")) // 4), True


def add_throughput_group(groups: dict[str, dict[str, Any]], key: str, tokens: int, estimated: bool) -> None:
    item = groups.setdefault(key, {"completed_requests": 0, "completion_tokens": 0, "actual_completion_tokens": 0, "estimated_completion_tokens": 0})
    item["completed_requests"] += 1
    item["completion_tokens"] += tokens
    if estimated:
        item["estimated_completion_tokens"] += tokens
    else:
        item["actual_completion_tokens"] += tokens


def finalize_throughput_groups(groups: dict[str, dict[str, Any]], window_s: float) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in groups.items():
        value = dict(item)
        value["aggregate_completion_tok_s"] = round(float(item["completion_tokens"]) / window_s, 6) if window_s > 0 else 0.0
        out[key] = value
    return dict(sorted(out.items()))


def finalize_stress_suite(suite: dict[str, Any]) -> dict[str, Any]:
    phases = list(suite.get("phases", []))
    eligible = [phase for phase in phases if phase.get("ok") and phase.get("throughput", {}).get("completed_requests", 0) > 0]
    fallback = [phase for phase in phases if phase.get("throughput", {}).get("completed_requests", 0) > 0]
    if not eligible:
        eligible = fallback
    best = max(eligible, key=lambda phase: float(phase.get("throughput", {}).get("aggregate_completion_tok_s", 0.0)), default=None)
    final = dict(suite)
    final["ok"] = best is not None
    final["valid_phase_count"] = sum(1 for phase in phases if phase.get("ok"))
    final["invalid_phase_count"] = sum(1 for phase in phases if not phase.get("ok"))
    final["best"] = {
        "phase_id": best.get("phase_id") if best else None,
        "load_point": best.get("load_point") if best else None,
        "aggregate_completion_tok_s": best.get("throughput", {}).get("aggregate_completion_tok_s") if best else 0.0,
        "completed_requests": best.get("throughput", {}).get("completed_requests") if best else 0,
        "gpu_vector": best.get("gpu_vector") if best else {},
    }
    return final


if __name__ == "__main__":
    raise SystemExit(main())
