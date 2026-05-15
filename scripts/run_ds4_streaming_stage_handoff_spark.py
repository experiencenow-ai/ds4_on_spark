#!/usr/bin/env python3
"""Run a TCP binary DS4 stage-handoff pipeline across Spark nodes."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"
RUNTIME_ID = "antirez-ds4-3630e64+explicit-preload+stage-handoff+tcp"
QUANT_ID = "DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf"


@dataclass
class Stage:
	name: str
	host: str
	ds4_dir: str
	model: str
	layer_begin: int
	layer_end: int
	include_head: bool
	proxy: str = ""
	listen_ip: str = ""


def default_stages() -> list[Stage]:
	return [
		Stage("spark0", "spark0@aitopatom-9ab9.local", "/tmp/ds4_stage_handoff_src", "/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf", 0, 15, False),
		Stage("spark1", "spark1@edgexpert-d623.local", "/home/spark1/src/ds4", "/home/spark1/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf", 15, 29, False, "", "10.10.1.248"),
		Stage("spark2", "spark2@10.10.5.2", "/home/spark2/src/ds4", "/home/spark2/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf", 29, 43, True, "spark1@edgexpert-d623.local", "10.10.5.2"),
	]


def load_stage_manifest(path: str) -> list[Stage]:
	with open(path, "r", encoding="utf-8") as f:
		obj = json.load(f)
	items = obj.get("stages") if isinstance(obj, dict) else obj
	if not isinstance(items, list) or len(items) < 2:
		raise ValueError("stage manifest must contain at least two stages")
	stages: list[Stage] = []
	for idx, item in enumerate(items):
		if not isinstance(item, dict):
			raise ValueError(f"stage {idx} must be an object")
		layer_range = item.get("layer_range")
		if not isinstance(layer_range, list) or len(layer_range) != 2:
			raise ValueError(f"stage {idx} requires layer_range [begin,end]")
		stages.append(
			Stage(
				name=str(item["name"]),
				host=str(item["host"]),
				ds4_dir=str(item["ds4_dir"]),
				model=str(item["model"]),
				layer_begin=int(layer_range[0]),
				layer_end=int(layer_range[1]),
				include_head=bool(item.get("include_head", idx + 1 == len(items))),
				proxy=str(item.get("proxy", "")),
				listen_ip=str(item.get("listen_ip", "")),
			)
		)
	for idx in range(1, len(stages)):
		if stages[idx].layer_begin != stages[idx - 1].layer_end:
			raise ValueError("stage layer ranges must be contiguous")
		if not stages[idx].listen_ip:
			raise ValueError(f"stage {idx} requires listen_ip for direct transfer")
	return stages


RECV_CODE = r"""
import hashlib,json,os,socket,struct,sys,time
port=int(sys.argv[1]); path=sys.argv[2]; expected=int(sys.argv[3])
os.makedirs(os.path.dirname(path), exist_ok=True)
def recvn(c,n):
    b=bytearray()
    while len(b)<n:
        x=c.recv(n-len(b))
        if not x: raise RuntimeError("short read")
        b.extend(x)
    return bytes(b)
s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(("0.0.0.0",port)); s.listen(1)
c,addr=s.accept()
t0=time.time()
with c:
    n=struct.unpack(">Q",recvn(c,8))[0]
    if expected and n != expected: raise RuntimeError(f"size {n} expected {expected}")
    h=hashlib.sha256(); tmp=path+".tmp"; got=0
    with open(tmp,"wb") as f:
        while got<n:
            x=c.recv(min(1048576,n-got))
            if not x: raise RuntimeError("short payload")
            f.write(x); h.update(x); got += len(x)
    digest=recvn(c,32)
    if digest != h.digest(): raise RuntimeError("sha256 mismatch")
os.replace(tmp,path)
t1=time.time()
print(json.dumps({"bytes":n,"sha256":h.hexdigest(),"transfer_ms":(t1-t0)*1000.0,"peer":addr[0]}), flush=True)
"""


SEND_CODE = r"""
import hashlib,json,os,socket,struct,sys,time
host=sys.argv[1]; port=int(sys.argv[2]); path=sys.argv[3]; timeout=float(sys.argv[4])
t_wait=time.time()
while not os.path.exists(path):
    if (time.time()-t_wait) > timeout: raise RuntimeError(f"timeout waiting for {path}")
    time.sleep(0.01)
data=open(path,"rb").read()
h=hashlib.sha256(data).digest()
t0=time.time(); last=None
while True:
    try:
        s=socket.create_connection((host,port),timeout=5.0)
        break
    except OSError as e:
        last=e
        if (time.time()-t0) > timeout: raise RuntimeError(f"connect timeout: {last}")
        time.sleep(0.05)
with s:
    s.sendall(struct.pack(">Q",len(data)))
    s.sendall(data)
    s.sendall(h)
t1=time.time()
print(json.dumps({"bytes":len(data),"sha256":h.hex(),"transfer_ms":(t1-t0)*1000.0,"dest":host}), flush=True)
"""


def ssh_base(stage: Stage, known_hosts: str) -> list[str]:
	args = [
		"ssh",
		"-o",
		"BatchMode=yes",
		"-o",
		"ConnectTimeout=15",
		"-o",
		"StrictHostKeyChecking=accept-new",
		"-o",
		f"UserKnownHostsFile={known_hosts}",
	]
	if stage.proxy:
		proxy = "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={} {} -W %h:%p".format(
			shlex.quote(known_hosts), shlex.quote(stage.proxy)
		)
		args += ["-o", f"ProxyCommand={proxy}"]
	args.append(stage.host)
	return args


def run_remote(stage: Stage, known_hosts: str, command: str) -> subprocess.CompletedProcess[str]:
	return subprocess.run(ssh_base(stage, known_hosts) + [command], text=True, capture_output=True)


def popen_remote(stage: Stage, known_hosts: str, command: str) -> subprocess.Popen[str]:
	return subprocess.Popen(ssh_base(stage, known_hosts) + [command], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def q(s: str) -> str:
	return shlex.quote(s)


def stage_dir(run_root: str, stage_index: int) -> str:
	return f"{run_root}/stage{stage_index}"


def boundary_path(run_root: str, stage_index: int) -> str:
	return f"{stage_dir(run_root, stage_index)}/mb%u_boundary.bin"


def build_stage_command(stage: Stage, idx: int, total: int, args: argparse.Namespace) -> str:
	env = [
		"DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1",
		"DS4_CUDA_STACK_PROBE_PRELOAD_STAGE=1",
		f"DS4_CUDA_STACK_PROBE_PRELOAD_CHUNK_MB={args.preload_chunk_mb}",
		f"DS4_CUDA_STACK_PROBE_LAYER_BEGIN={stage.layer_begin}",
		f"DS4_CUDA_STACK_PROBE_LAYER_END={stage.layer_end}",
		"DS4_CUDA_STACK_PROBE_SPLIT_LAYERS=1",
		"DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1",
		"DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1",
		"DS4_CUDA_MOE_EXPERT_SLICE_STRICT=1",
	]
	if not stage.include_head:
		env.append("DS4_CUDA_STACK_PROBE_NO_HEAD=1")
	if idx == 0:
		env.append("DS4_CUDA_STACK_PROBE_EMBED_INPUT=1")
	else:
		env.append(f"DS4_CUDA_STACK_PROBE_INPUT_HC_FILE={q(boundary_path(args.remote_run_root, idx - 1))}")
		env.append(f"DS4_CUDA_STACK_PROBE_INPUT_WAIT_MS={args.input_wait_ms}")
	if idx + 1 < total:
		env.append(f"DS4_CUDA_STACK_PROBE_OUTPUT_HC_FILE={q(boundary_path(args.remote_run_root, idx))}")
	cmd = " ".join(env + [
		"./ds4",
		"-m",
		q(stage.model),
		"--cuda-batch-stack-probe",
		"--cuda-moe-tokens",
		str(args.batch),
		"--cuda-moe-iters",
		str(args.microbatches),
		"--ctx",
		str(args.ctx),
	])
	return f"mkdir -p {q(stage_dir(args.remote_run_root, idx))}; cd {q(stage.ds4_dir)}; env {cmd}"


def parse_last_json(text: str) -> dict[str, Any]:
	for line in reversed(text.splitlines()):
		line = line.strip()
		if line.startswith("{") and line.endswith("}"):
			return json.loads(line)
	raise ValueError("no JSON object in stdout")


def write_log(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8")


def run_stage_thread(stage: Stage, idx: int, total: int, args: argparse.Namespace, outdir: Path, results: list[dict[str, Any]], errors: "queue.Queue[str]") -> None:
	cmd = build_stage_command(stage, idx, total, args)
	t0 = time.time()
	proc = popen_remote(stage, args.known_hosts, cmd)
	stdout, stderr = proc.communicate()
	t1 = time.time()
	write_log(outdir / f"stage{idx}.out", stdout or "")
	write_log(outdir / f"stage{idx}.err", stderr or "")
	if proc.returncode != 0:
		errors.put(f"stage{idx} failed rc={proc.returncode}: {(stderr or '').splitlines()[-8:]}")
		return
	try:
		obj = parse_last_json(stdout or "")
	except Exception as e:
		errors.put(f"stage{idx} JSON parse failed: {e}")
		return
	obj["stage_process_wall_ms"] = (t1 - t0) * 1000.0
	obj["stage_node"] = stage.name
	results[idx] = obj


def run_transfer_pair(
	src: Stage,
	dst: Stage,
	link_idx: int,
	mb: int,
	port: int,
	expected_bytes: int,
	args: argparse.Namespace,
	outdir: Path,
) -> dict[str, Any]:
	src_path = boundary_path(args.remote_run_root, link_idx).replace("%u", str(mb))
	dst_path = boundary_path(args.remote_run_root, link_idx).replace("%u", str(mb))
	recv_cmd = "python3 -c {} {} {} {}".format(q(RECV_CODE), port, q(dst_path), expected_bytes)
	send_cmd = "python3 -c {} {} {} {} {}".format(q(SEND_CODE), q(dst.listen_ip), port, q(src_path), args.transfer_wait_s)
	recv = popen_remote(dst, args.known_hosts, recv_cmd)
	time.sleep(0.15)
	send = popen_remote(src, args.known_hosts, send_cmd)
	send_out, send_err = send.communicate()
	recv_out, recv_err = recv.communicate()
	prefix = outdir / f"transfer{link_idx}_mb{mb}"
	write_log(prefix.with_suffix(".send.out"), send_out or "")
	write_log(prefix.with_suffix(".send.err"), send_err or "")
	write_log(prefix.with_suffix(".recv.out"), recv_out or "")
	write_log(prefix.with_suffix(".recv.err"), recv_err or "")
	if send.returncode != 0 or recv.returncode != 0:
		raise RuntimeError(f"transfer link={link_idx} mb={mb} send_rc={send.returncode} recv_rc={recv.returncode}")
	send_obj = parse_last_json(send_out or "")
	recv_obj = parse_last_json(recv_out or "")
	return {
		"boundary": link_idx,
		"microbatch": mb,
		"bytes": recv_obj["bytes"],
		"sha256": recv_obj["sha256"],
		"send_ms": send_obj["transfer_ms"],
		"recv_ms": recv_obj["transfer_ms"],
		"transfer_ms": max(float(send_obj["transfer_ms"]), float(recv_obj["transfer_ms"])),
		"src": src.name,
		"dst": dst.name,
		"dst_ip": dst.listen_ip,
	}


def transfer_thread(stages: list[Stage], link_idx: int, args: argparse.Namespace, outdir: Path, transfers: list[list[dict[str, Any]]], errors: "queue.Queue[str]") -> None:
	try:
		for mb in range(args.microbatches):
			port = args.base_port + link_idx * 1000 + mb
			item = run_transfer_pair(stages[link_idx], stages[link_idx + 1], link_idx, mb, port, args.boundary_bytes, args, outdir)
			transfers[link_idx][mb] = item
	except Exception as e:
		errors.put(f"transfer link={link_idx} failed: {e}")


def compute_schedule(stage_results: list[dict[str, Any]], transfers: list[list[dict[str, Any]]], batch: int, microbatches: int) -> dict[str, Any]:
	stage_iters: list[list[float]] = []
	for result in stage_results:
		values = result.get("iter_ms")
		if not isinstance(values, list) or len(values) != microbatches:
			values = [float(result["best_ms"])] * microbatches
		stage_iters.append([float(v) for v in values])
	transfer_ms = [[float(item["transfer_ms"]) for item in link] for link in transfers]
	stage_finish = [[0.0 for _ in range(microbatches)] for _ in stage_results]
	for mb in range(microbatches):
		prev = stage_finish[0][mb - 1] if mb else 0.0
		stage_finish[0][mb] = prev + stage_iters[0][mb]
		for s in range(1, len(stage_results)):
			ready = stage_finish[s - 1][mb] + transfer_ms[s - 1][mb]
			prev_stage = stage_finish[s][mb - 1] if mb else 0.0
			stage_finish[s][mb] = max(ready, prev_stage) + stage_iters[s][mb]
	last_ms = stage_finish[-1][-1]
	service = []
	for s in range(len(stage_results)):
		cur = []
		for mb in range(microbatches):
			v = stage_iters[s][mb]
			if s + 1 < len(stage_results):
				v += transfer_ms[s][mb]
			cur.append(v)
		service.append(cur)
	bottleneck = max(max(v) for v in service)
	return {
		"stage_ms_by_microbatch": stage_iters,
		"transfer_ms_by_boundary": transfer_ms,
		"streaming_schedule_finish_ms": stage_finish,
		"achieved_streaming_rows_per_s": (batch * microbatches * 1000.0 / last_ms) if last_ms > 0 else 0.0,
		"pipeline_rows_per_s_bound": (batch * 1000.0 / bottleneck) if bottleneck > 0 else 0.0,
		"bubble_overhead_ratio": (last_ms / (microbatches * bottleneck) - 1.0) if bottleneck > 0 else 0.0,
	}


def build_artifact(args: argparse.Namespace, stages: list[Stage], results: list[dict[str, Any]], transfers: list[list[dict[str, Any]]], schedule: dict[str, Any], outdir: Path, wall_ms: float) -> dict[str, Any]:
	final = results[-1]
	hashes = [f"fnv64:{h}" for h in final.get("logits_fnv64s", [])]
	if not hashes and final.get("logits_fnv64"):
		hashes = [f"fnv64:{final['logits_fnv64']}"]
	nonfinites = final.get("logits_nonfinites", [final.get("logits_nonfinite", 0)])
	finite = all(int(v) == 0 for v in nonfinites) and all(h != "fnv64:0000000000000000" for h in hashes)
	return {
		"format": "ds4-stage-handoff-truth-v1",
		"run_id": args.run_id,
		"model_id": MODEL_ID,
		"runtime_id": RUNTIME_ID,
		"quantization_id": QUANT_ID,
		"batch_size": args.batch,
		"stage_count": len(stages),
		"stage_nodes": [s.name for s in stages],
		"layer_ranges": [[s.layer_begin, s.layer_end] for s in stages],
		"boundary_layout": "batch,hc,hidden",
		"boundary_dtype": "f32",
		"boundary_bytes": args.boundary_bytes,
		"stage_ms": [float(r["best_ms"]) for r in results],
		"stage_ms_by_microbatch": schedule["stage_ms_by_microbatch"],
		"transport_kind": "tcp_binary",
		"streaming_pipeline": True,
		"microbatch_count": args.microbatches,
		"pipeline_depth": min(args.pipeline_depth, args.microbatches),
		"transfer_ms": max((item["transfer_ms"] for link in transfers for item in link), default=0.0),
		"transfer_ms_by_boundary": schedule["transfer_ms_by_boundary"],
		"pipeline_rows_per_s_bound": schedule["pipeline_rows_per_s_bound"],
		"actual_end_to_end_rows_per_s_if_measured": schedule["achieved_streaming_rows_per_s"],
		"achieved_streaming_rows_per_s": schedule["achieved_streaming_rows_per_s"],
		"bubble_overhead_ratio": schedule["bubble_overhead_ratio"],
		"orchestrator_wall_ms": wall_ms,
		"final_logits_hash": hashes[-1] if hashes else "",
		"final_logits_hashes": hashes,
		"final_output_finite": finite,
		"parity_status": "not_run",
		"parity_scope": "stage_handoff_finite_logits",
		"blocker_kind": "none" if finite else "nonfinite_final_output",
		"blocker_detail": "" if finite else "stage2 produced nonfinite or zero final logits",
		"artifact_dir": str(outdir),
	}


def parse_args() -> argparse.Namespace:
	ap = argparse.ArgumentParser()
	ap.add_argument("--run-id", default=f"ds4-streaming-stage-handoff-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
	ap.add_argument("--stage-manifest", default="", help="Optional JSON stage manifest. Defaults to Spark0->Spark1->Spark2.")
	ap.add_argument("--local-out-dir", default="")
	ap.add_argument("--remote-run-root", default="")
	ap.add_argument("--batch", type=int, default=64)
	ap.add_argument("--microbatches", type=int, default=2)
	ap.add_argument("--pipeline-depth", type=int, default=2)
	ap.add_argument("--ctx", type=int, default=128)
	ap.add_argument("--preload-chunk-mb", type=int, default=16)
	ap.add_argument("--input-wait-ms", type=int, default=900000)
	ap.add_argument("--transfer-wait-s", type=float, default=900.0)
	ap.add_argument("--base-port", type=int, default=19100)
	ap.add_argument("--known-hosts", default="/private/tmp/ds4_spark_known_hosts")
	args = ap.parse_args()
	if not args.remote_run_root:
		args.remote_run_root = f"/tmp/{args.run_id}"
	if not args.local_out_dir:
		args.local_out_dir = f"/private/tmp/{args.run_id}"
	args.boundary_bytes = args.batch * 4 * 4096 * 4
	return args


def main() -> int:
	args = parse_args()
	stages = load_stage_manifest(args.stage_manifest) if args.stage_manifest else default_stages()
	outdir = Path(args.local_out_dir)
	outdir.mkdir(parents=True, exist_ok=True)
	for idx, stage in enumerate(stages):
		rc = run_remote(stage, args.known_hosts, f"mkdir -p {q(stage_dir(args.remote_run_root, idx))}")
		if rc.returncode != 0:
			print(rc.stderr, file=sys.stderr)
			return 2
	errors: queue.Queue[str] = queue.Queue()
	results: list[dict[str, Any]] = [{} for _ in stages]
	transfers: list[list[dict[str, Any]]] = [[{} for _ in range(args.microbatches)] for _ in range(len(stages) - 1)]
	t0 = time.time()
	threads: list[threading.Thread] = []
	for link in range(len(stages) - 1):
		threads.append(threading.Thread(target=transfer_thread, args=(stages, link, args, outdir, transfers, errors), daemon=True))
	for idx, stage in enumerate(stages):
		threads.append(threading.Thread(target=run_stage_thread, args=(stage, idx, len(stages), args, outdir, results, errors), daemon=True))
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join()
	wall_ms = (time.time() - t0) * 1000.0
	if not errors.empty():
		while not errors.empty():
			print(f"error: {errors.get()}", file=sys.stderr)
		return 2
	schedule = compute_schedule(results, transfers, args.batch, args.microbatches)
	artifact = build_artifact(args, stages, results, transfers, schedule, outdir, wall_ms)
	(outdir / "summary.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	print(json.dumps(artifact, indent=2, sort_keys=True))
	return 0 if artifact["final_output_finite"] else 1


if __name__ == "__main__":
	raise SystemExit(main())
