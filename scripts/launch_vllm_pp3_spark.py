#!/usr/bin/env python3
"""Mac-side launcher for a three-node DeepSeek V4 Flash vLLM PP=3 run."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


MODEL_MOUNT = "/models/deepseek-v4-flash"
DEFAULT_MODEL_HOST_PATH = "/home/{host}/models/hf/deepseek-ai/DeepSeek-V4-Flash"
DEFAULT_NODES = "spark3:0:10.10.100.13,spark4:1:10.10.100.14,spark5:2:10.10.100.15"
DEFAULT_MASTER_ADDR = "10.10.100.13"


@dataclass(frozen=True)
class Node:
	host: str
	rank: int
	addr: str
	model_path: str


def parse_node(raw: str) -> Node:
	parts = raw.split(":")
	if len(parts) not in (3,4):
		raise ValueError("node must be host:rank:addr[:model_path]")
	host = parts[0]
	rank = int(parts[1])
	addr = parts[2]
	model_path = parts[3] if len(parts) == 4 else DEFAULT_MODEL_HOST_PATH.format(host=host)
	return(Node(host,rank,addr,model_path))


def parse_nodes(raw: str) -> list[Node]:
	nodes = [parse_node(part) for part in raw.split(",") if part.strip() != ""]
	if len(nodes) != 3:
		raise ValueError("PP=3 launch requires exactly three nodes")
	ranks = sorted(node.rank for node in nodes)
	if ranks != [0,1,2]:
		raise ValueError(f"PP=3 node ranks must be 0,1,2, got {ranks}")
	return(nodes)


def sh(cmd: list[str], dry_run: bool, timeout_s: float = 30.0) -> subprocess.CompletedProcess[str]:
	print(shlex.join(cmd), flush=True)
	if dry_run:
		return(subprocess.CompletedProcess(cmd,0,"",""))
	return(subprocess.run(cmd, text=True, capture_output=True, timeout=timeout_s))


def ssh(node: Node, remote: str, dry_run: bool, timeout_s: float = 30.0) -> subprocess.CompletedProcess[str]:
	return(sh(["ssh","-o","BatchMode=yes","-o","ConnectTimeout=10",node.host,remote],dry_run,timeout_s))


def check(result: subprocess.CompletedProcess[str]) -> None:
	if result.stdout:
		print(result.stdout, end="")
	if result.stderr:
		print(result.stderr, end="", file=sys.stderr)
	if result.returncode != 0:
		raise SystemExit(result.returncode)


def env_args(node: Node, args: argparse.Namespace) -> list[str]:
	env = {
		"FLASHINFER_DISABLE_VERSION_CHECK": "1",
		"NCCL_DEBUG": args.nccl_debug,
		"NCCL_SOCKET_FAMILY": "AF_INET",
		"NCCL_SOCKET_IFNAME": args.socket_ifname,
		"RAY_NODE_IP_ADDRESS": node.addr,
		"RAY_memory_monitor_refresh_ms": "0",
		"RAY_num_prestart_python_workers": "0",
		"RAY_object_store_memory": "1073741824",
		"RAY_OVERRIDE_NODE_IP_ADDRESS": node.addr,
		"TILELANG_CLEANUP_TEMP_FILES": "1",
		"TORCH_CUDA_ARCH_LIST": "12.1a",
		"VLLM_ALLOW_LONG_MAX_MODEL_LEN": "1",
		"VLLM_HOST_IP": node.addr,
		"VLLM_TRITON_MLA_SPARSE": "1",
	}
	if args.gloo_socket_ifname != "":
		env["GLOO_SOCKET_IFNAME"] = args.gloo_socket_ifname
	if not args.enable_ib:
		env["NCCL_IB_DISABLE"] = "1"
	return([f"-e {shlex.quote(k + '=' + v)}" for k,v in env.items()])


def docker_run_command(node: Node, args: argparse.Namespace) -> str:
	bind = f"{node.model_path}:{MODEL_MOUNT}:ro"
	log_bind = f"{args.host_log_dir}:/host_tmp"
	env = " ".join(env_args(node,args))
	return(
		f"docker run -d --rm --name {shlex.quote(args.container)} --network host "
		f"--privileged --gpus all --ipc host --security-opt label=disable "
		f"-v {shlex.quote(bind)} -v {shlex.quote(log_bind)} "
		f"{env} {shlex.quote(args.image)} sleep infinity"
	)


def vllm_args(node: Node, args: argparse.Namespace) -> list[str]:
	cmd = [
		"vllm","serve",MODEL_MOUNT,
		"--default-chat-template-kwargs",json.dumps({"thinking": True}),
		"--enable-auto-tool-choice",
		"--tool-call-parser","deepseek_v4",
		"--host","0.0.0.0",
		"--port",str(args.port),
		"--tokenizer-mode","deepseek_v4",
		"--trust-remote-code",
		"--max-model-len",str(args.max_model_len),
		"--served-model-name",args.model_name,
		"--load-format","safetensors",
		"--reasoning-parser","deepseek_v4",
		"--pipeline-parallel-size","3",
		"--master-addr",args.master_addr,
		"--master-port",str(args.master_port),
		"--nnodes","3",
		"--node-rank",str(node.rank),
		"--enable-expert-parallel",
		"--block-size","256",
		"--gpu-memory-utilization",str(args.gpu_memory_utilization),
		"--kv-cache-dtype","fp8",
		"--no-enable-prefix-caching",
		"--max-num-batched-tokens",str(args.max_num_batched_tokens),
		"--max-num-seqs",str(args.max_num_seqs),
	]
	if node.rank != 0:
		cmd.append("--headless")
	return(cmd)


def start_node(node: Node, args: argparse.Namespace) -> None:
	ssh(node,f"docker rm -f {shlex.quote(args.container)} >/dev/null 2>&1 || true",args.dry_run)
	check(ssh(node,docker_run_command(node,args),args.dry_run,timeout_s=120.0))
	command = shlex.join(vllm_args(node,args))
	log_path = shlex.quote(args.remote_log_path)
	remote = f"docker exec {shlex.quote(args.container)} bash -lc {shlex.quote(f'nohup {command} >{log_path} 2>&1 &')}"
	check(ssh(node,remote,args.dry_run,timeout_s=60.0))


def start(args: argparse.Namespace) -> int:
	nodes = parse_nodes(args.nodes)
	for node in sorted(nodes, key=lambda n: n.rank, reverse=True):
		start_node(node,args)
		time.sleep(args.node_start_gap_s)
	return(0)


def stop(args: argparse.Namespace) -> int:
	nodes = parse_nodes(args.nodes)
	for node in sorted(nodes, key=lambda n: n.rank, reverse=True):
		check(ssh(node,f"docker rm -f {shlex.quote(args.container)}",args.dry_run,timeout_s=60.0))
		time.sleep(args.node_start_gap_s)
	return(0)


def status(args: argparse.Namespace) -> int:
	nodes = parse_nodes(args.nodes)
	for node in nodes:
		print(f"=== {node.host} rank={node.rank} addr={node.addr} ===")
		check(ssh(node,f"docker ps --filter name={shlex.quote(args.container)} --format '{{{{.Names}}}} {{{{.Status}}}}'",args.dry_run))
		check(ssh(node,f"docker exec {shlex.quote(args.container)} bash -lc {shlex.quote('ps -ef | grep -E \"[v]llm serve|[s]leep infinity\"')}",args.dry_run))
		check(ssh(node,f"docker exec {shlex.quote(args.container)} tail -n {args.log_tail} {shlex.quote(args.remote_log_path)}",args.dry_run))
	return(0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("action", choices=("start","stop","status"))
	p.add_argument("--nodes", default=DEFAULT_NODES)
	p.add_argument("--container", default="vllm_deepseek_v4_flash_pp3_track3_1196")
	p.add_argument("--image", default="vllm-node-dsv4")
	p.add_argument("--model-name", default="deepseek-v4-flash")
	p.add_argument("--master-addr", default=DEFAULT_MASTER_ADDR)
	p.add_argument("--master-port", type=int, default=29516)
	p.add_argument("--port", type=int, default=8016)
	p.add_argument("--socket-ifname", default="wlP9s9")
	p.add_argument("--gloo-socket-ifname", default="wlP9s9")
	p.add_argument("--nccl-debug", default="INFO")
	p.add_argument("--enable-ib", action="store_true")
	p.add_argument("--max-model-len", type=int, default=8192)
	p.add_argument("--max-num-seqs", type=int, default=512)
	p.add_argument("--max-num-batched-tokens", type=int, default=8192)
	p.add_argument("--gpu-memory-utilization", type=float, default=0.85)
	p.add_argument("--host-log-dir", default="/tmp")
	p.add_argument("--remote-log-path", default="/host_tmp/vllm_pp3_track3_1196.log")
	p.add_argument("--node-start-gap-s", type=float, default=2.0)
	p.add_argument("--log-tail", type=int, default=80)
	p.add_argument("--dry-run", action="store_true")
	return(p.parse_args(argv))


def main() -> int:
	args = parse_args()
	if args.action == "start":
		return(start(args))
	if args.action == "stop":
		return(stop(args))
	return(status(args))


if __name__ == "__main__":
	raise SystemExit(main())
