#!/usr/bin/env python3
"""Reject DS4 DeepSeek-V4-Flash vLLM launch profiles that can wedge Sparks."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-dsv4-flash-launch-guard-v1"
BAD = "blocked"
OK = "passed"
WARN = "warn"
DS4_FLASH_SPARK_GB10_TOTAL_GIB = 119.7
DS4_FLASH_BASE_RESIDENT_GIB = 78.0
DS4_FLASH_BATCH_KV_GIB_AT_8192_TP2 = 4.0
DS4_FLASH_SEQUENCE_OVERHEAD_GIB = 0.004
DS4_FLASH_DEFAULT_MIN_HEADROOM_GIB = 8.0
DS4_FLASH_REQUIRED_BLOCK_SIZE = 128
DS4_FLASH_WIFI_PREFIXES = ("wl", "wifi", "wlan")
DS4_FLASH_WIFI_ADDR_PREFIXES = ("192.168.",)


def strip_value(raw: str) -> str:
	return(raw.strip().strip("'").strip('"'))


def parse_scalar(raw: str) -> Any:
	value = strip_value(raw)
	if value.lower() == "true":
		return(True)
	if value.lower() == "false":
		return(False)
	try:
		if "." in value:
			return(float(value))
		return(int(value))
	except ValueError:
		return(value)


def read_recipe_text(path: Path) -> tuple[dict[str, Any], str]:
	defaults: dict[str, Any] = {}
	command_lines: list[str] = []
	in_defaults = False
	in_command = False
	for raw in path.read_text(encoding="utf-8").splitlines():
		if re.match(r"^[A-Za-z0-9_]+:", raw):
			in_defaults = raw.startswith("defaults:")
			in_command = raw.startswith("command:")
			continue
		if in_defaults:
			m = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.*)$", raw)
			if m is not None:
				defaults[m.group(1)] = parse_scalar(m.group(2))
			elif raw.strip() != "":
				in_defaults = False
		elif in_command:
			if raw.startswith("  "):
				command_lines.append(raw[2:])
			elif raw.strip() != "":
				in_command = False
	command = "\n".join(command_lines).strip()
	if command == "":
		command = path.read_text(encoding="utf-8")
	for key, value in defaults.items():
		command = command.replace("{" + key + "}", str(value))
	return(defaults, command)


def read_launch_text(path: Path) -> tuple[dict[str, Any], str]:
	return({}, path.read_text(encoding="utf-8"))


def command_tokens(command: str) -> list[str]:
	flat = command.replace("\\\n", " ")
	return(shlex.split(flat, comments=False, posix=True))


def flag_values(tokens: list[str]) -> dict[str, list[str | bool]]:
	out: dict[str, list[str | bool]] = {}
	i = 0
	while i < len(tokens):
		tok = tokens[i]
		if not tok.startswith("--"):
			i += 1
			continue
		if "=" in tok:
			flag, value = tok.split("=", 1)
			out.setdefault(flag, []).append(value)
			i += 1
			continue
		if tok in ("--enable-prefix-caching", "--no-enable-prefix-caching", "--trust-remote-code", "--enable-expert-parallel"):
			out.setdefault(tok, []).append(True)
			i += 1
			continue
		if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
			out.setdefault(tok, []).append(tokens[i + 1])
			i += 2
		else:
			out.setdefault(tok, []).append(True)
			i += 1
	return(out)


def env_values(tokens: list[str], names: tuple[str, ...]) -> dict[str, list[str]]:
	out: dict[str, list[str]] = {name: [] for name in names}
	for tok in tokens:
		if "=" not in tok or tok.startswith("--"):
			continue
		name, value = tok.split("=", 1)
		if name in out:
			out[name].append(value)
	return(out)


def string_flag(flags: dict[str, list[str | bool]], name: str) -> str:
	vals = flags.get(name)
	if not vals:
		return("")
	value = vals[-1]
	if isinstance(value, bool):
		return("")
	return(str(value))


def is_wifi_interface(value: str) -> bool:
	item = strip_value(value).lower()
	return(any(item.startswith(prefix) for prefix in DS4_FLASH_WIFI_PREFIXES))


def is_wifi_address(value: str) -> bool:
	item = strip_value(value)
	return(any(item.startswith(prefix) for prefix in DS4_FLASH_WIFI_ADDR_PREFIXES))


def int_flag(flags: dict[str, list[str | bool]], name: str, default: int) -> int:
	vals = flags.get(name)
	if not vals:
		return(default)
	try:
		return(int(vals[-1]))
	except (TypeError, ValueError):
		return(default)


def float_flag(flags: dict[str, list[str | bool]], name: str, default: float) -> float:
	vals = flags.get(name)
	if not vals:
		return(default)
	try:
		return(float(vals[-1]))
	except (TypeError, ValueError):
		return(default)


def float_default(defaults: dict[str, Any], key: str, default: float) -> float:
	try:
		return(float(defaults.get(key, default)))
	except (TypeError, ValueError):
		return(default)


def int_default(defaults: dict[str, Any], key: str, default: int) -> int:
	try:
		return(int(defaults.get(key, default)))
	except (TypeError, ValueError):
		return(default)


def prefix_policy(tokens: list[str]) -> str:
	policy = "default"
	for tok in tokens:
		if tok == "--enable-prefix-caching":
			policy = "enabled"
		elif tok == "--no-enable-prefix-caching":
			policy = "disabled"
	return(policy)


def is_dsv4_flash(command: str) -> bool:
	needle = command.lower()
	return("deepseek-v4-flash" in needle or "deepseek_v4" in needle)


def add_issue(issues: list[dict[str, str]], kind: str, blocker_kind: str, detail: str, recommended_fix: str) -> None:
	issues.append({
		"kind": kind,
		"blocker_kind": blocker_kind,
		"detail": detail,
		"recommended_fix": recommended_fix,
	})


def estimate_memory(defaults: dict[str, Any], max_num_batched_tokens: int, max_num_seqs: int, gpu_memory_utilization: float, tensor_parallel_size: int) -> dict[str, Any]:
	tp = max(tensor_parallel_size, 1)
	total_gib = float_default(defaults, "total_gpu_memory_gib", DS4_FLASH_SPARK_GB10_TOTAL_GIB)
	util = gpu_memory_utilization if gpu_memory_utilization > 0.0 else float_default(defaults, "gpu_memory_utilization", 0.8)
	utilized_gib = (total_gib * util)
	available_gib = float_default(defaults, "available_gpu_memory_gib", utilized_gib)
	free_gib = float_default(defaults, "free_gpu_memory_gib", available_gib)
	budget_gib = min(available_gib, free_gib)
	min_headroom_gib = float_default(defaults, "declared_headroom_gib", DS4_FLASH_DEFAULT_MIN_HEADROOM_GIB)
	batch_kv_gib = (DS4_FLASH_BATCH_KV_GIB_AT_8192_TP2 * (float(max(max_num_batched_tokens, 0)) / 8192.0) * (2.0 / float(tp)))
	sequence_gib = (float(max(max_num_seqs, 0)) * DS4_FLASH_SEQUENCE_OVERHEAD_GIB)
	estimated_request_gib = (DS4_FLASH_BASE_RESIDENT_GIB + batch_kv_gib + sequence_gib)
	headroom_after_estimate_gib = (budget_gib - estimated_request_gib)
	return({
		"basis": "spark4_spark5_empirical_guard",
		"tensor_parallel_size": tp,
		"total_gpu_memory_gib": round(total_gib, 3),
		"gpu_memory_utilization": round(util, 4),
		"available_gpu_memory_gib": round(available_gib, 3),
		"free_gpu_memory_gib": round(free_gib, 3),
		"budget_gpu_memory_gib": round(budget_gib, 3),
		"base_resident_gib": round(DS4_FLASH_BASE_RESIDENT_GIB, 3),
		"batch_kv_gib": round(batch_kv_gib, 3),
		"sequence_overhead_gib": round(sequence_gib, 3),
		"estimated_request_gib": round(estimated_request_gib, 3),
		"minimum_headroom_gib": round(min_headroom_gib, 3),
		"headroom_after_estimate_gib": round(headroom_after_estimate_gib, 3),
	})


def validate_command(path: Path, defaults: dict[str, Any], command: str) -> dict[str, Any]:
	tokens = command_tokens(command)
	flags = flag_values(tokens)
	prefix = prefix_policy(tokens)
	max_model_len = int_flag(flags, "--max-model-len", int(defaults.get("max_model_len", 0) or 0))
	max_num_seqs = int_flag(flags, "--max-num-seqs", int(defaults.get("max_num_seqs", 0) or 0))
	max_num_batched_tokens = int_flag(flags, "--max-num-batched-tokens", int(defaults.get("max_num_batched_tokens", 0) or 0))
	block_size = int_flag(flags, "--block-size", int(defaults.get("block_size", 0) or 0))
	gpu_memory_utilization = float_flag(flags, "--gpu-memory-utilization", float(defaults.get("gpu_memory_utilization", 0.0) or 0.0))
	nnodes = int_flag(flags, "--nnodes", int(defaults.get("nnodes", 1) or 1))
	tensor_parallel_size = int_flag(flags, "--tensor-parallel-size", int(defaults.get("tensor_parallel_size", 1) or 1))
	pipeline_parallel_size = int_flag(flags, "--pipeline-parallel-size", int(defaults.get("pipeline_parallel_size", 1) or 1))
	master_addr = string_flag(flags, "--master-addr")
	fabric_env = env_values(tokens, ("GLOO_SOCKET_IFNAME", "NCCL_SOCKET_IFNAME", "TP_SOCKET_IFNAME", "VLLM_HOST_IP", "RAY_NODE_IP_ADDRESS", "RAY_OVERRIDE_NODE_IP_ADDRESS"))
	issues: list[dict[str, str]] = []
	warnings: list[dict[str, str]] = []
	dupes = {k: v for k, v in flags.items() if len(v) > 1}
	if "--max-num-batched-tokens" in dupes:
		add_issue(issues, "duplicate_max_num_batched_tokens", "ambiguous_duplicate_max_num_batched_tokens", "duplicate --max-num-batched-tokens makes the effective graph/KV profile ambiguous", "remove the duplicate flag and keep exactly one measured scheduler-token value")
	memory = estimate_memory(defaults, max_num_batched_tokens, max_num_seqs, gpu_memory_utilization, tensor_parallel_size)
	if is_dsv4_flash(command):
		if block_size not in (0, DS4_FLASH_REQUIRED_BLOCK_SIZE):
			add_issue(issues, "ds4_flash_block_size_mismatch", "unsupported_block_size", f"DeepSeek-V4-Flash inference constants require block_size={DS4_FLASH_REQUIRED_BLOCK_SIZE}; observed launch --block-size {block_size}, matching the known 256 == 128 assertion path", f"set --block-size {DS4_FLASH_REQUIRED_BLOCK_SIZE} or omit the flag before launching DS4 Flash")
		if prefix != "disabled":
			add_issue(issues, "prefix_cache_c512_rank0_kill_risk", "prefix_enabled_c512_risk", "DeepSeek-V4-Flash Spark4/Spark5 c512 stress reproduced rank0/API death unless --no-enable-prefix-caching is explicit", "add --no-enable-prefix-caching before retrying c512 or long-context DS4 Flash profiles")
		if max_model_len >= 200000 and max_num_batched_tokens <= 512:
			add_issue(issues, "cuda_graph_kv_starvation_risk", "unavailable_kv_headroom", "200k context with max_num_batched_tokens<=512 produced 512-size graph capture, low KV headroom, worker exit, and Spark4 SSH banner timeouts", "use the measured 8192 scheduler-token profile or lower context/concurrency before launch")
		if max_model_len >= 200000 and max_num_batched_tokens > 8192:
			add_issue(issues, "kv_allocation_risk", "unavailable_kv_headroom", "existing tuning evidence rejected >8192 scheduler tokens for the 200k-context Spark4/Spark5 lane", "cap --max-num-batched-tokens at 8192 until a larger profile has measured launch evidence")
		if float(memory["headroom_after_estimate_gib"]) < float(memory["minimum_headroom_gib"]):
			add_issue(issues, "insufficient_memory_headroom", "low_free_memory", "estimated DS4 Flash resident+KV/request memory leaves less than declared headroom", "free GPU memory, lower max-num-batched-tokens/max-num-seqs, or lower gpu-memory-utilization before launch")
		if max_num_seqs >= 512 and max_model_len >= 200000:
			warnings.append({
				"kind": "high_sequence_budget",
				"detail": "c512 at 200k context must be stress-tested after launch; this is a queueing/throughput profile, not a safe default chat profile",
			})
		if nnodes > 1 and tensor_parallel_size > 1 and "GLOO_SOCKET_IFNAME" not in command:
			add_issue(issues, "missing_gloo_socket_ifname", "cross_node_gloo_loopback", "cross-node TP uses a Gloo CPU process group; without GLOO_SOCKET_IFNAME it can pick 127.0.0.1 and fail before serving", "set GLOO_SOCKET_IFNAME to the Spark fabric interface used for the cross-node TP launch")
		if nnodes > 1:
			for name in ("GLOO_SOCKET_IFNAME", "NCCL_SOCKET_IFNAME", "TP_SOCKET_IFNAME"):
				for value in fabric_env.get(name, []):
					if is_wifi_interface(value):
						add_issue(issues, f"wifi_distributed_{name.lower()}", "wifi_distributed_dataplane", f"multi-node DS4 Flash launch pins {name}={value}; Wi-Fi distributed traffic produced a low and noisy PP3 throughput lane", "pin GLOO/NCCL/TP interfaces to the direct 200G device for the chosen adjacent Spark pair, or add validated 200G routes before PP>2")
			for name in ("VLLM_HOST_IP", "RAY_NODE_IP_ADDRESS", "RAY_OVERRIDE_NODE_IP_ADDRESS"):
				for value in fabric_env.get(name, []):
					if is_wifi_address(value):
						add_issue(issues, f"wifi_distributed_{name.lower()}", "wifi_distributed_dataplane", f"multi-node DS4 Flash launch pins {name}={value}; this selects the Wi-Fi control plane for runtime traffic", "use the 200G endpoint IP for the node participating in the distributed runtime")
			if is_wifi_address(master_addr):
				add_issue(issues, "wifi_master_addr", "wifi_distributed_dataplane", f"multi-node DS4 Flash launch uses --master-addr {master_addr}; this routes distributed setup and likely NCCL/Gloo traffic through Wi-Fi", "use a reachable 200G master address for PP=2, or configure validated 200G routes before PP=3+")
	status = BAD if issues else OK
	return({
		"format": FORMAT,
		"path": str(path),
		"status": status,
		"model_family_detected": "deepseek_v4_flash" if is_dsv4_flash(command) else "unknown",
		"effective": {
			"prefix_caching": prefix,
			"max_model_len": max_model_len,
			"max_num_seqs": max_num_seqs,
			"max_num_batched_tokens": max_num_batched_tokens,
			"block_size": block_size,
			"gpu_memory_utilization": gpu_memory_utilization,
			"nnodes": nnodes,
			"tensor_parallel_size": tensor_parallel_size,
			"pipeline_parallel_size": pipeline_parallel_size,
			"master_addr": master_addr,
			"fabric_env": fabric_env,
		},
		"memory_estimate": memory,
		"issues": issues,
		"warnings": warnings,
	})


def validate_path(path: Path) -> dict[str, Any]:
	text = path.read_text(encoding="utf-8")
	if "recipe_version:" in text or "command:" in text:
		defaults, command = read_recipe_text(path)
	else:
		defaults, command = read_launch_text(path)
	return(validate_command(path, defaults, command))


def main() -> int:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("paths", nargs="+", type=Path)
	args = p.parse_args()
	results = [validate_path(path) for path in args.paths]
	print(json.dumps({"format": FORMAT, "results": results}, indent=2, sort_keys=True))
	return(1 if any(r["status"] == BAD for r in results) else 0)


if __name__ == "__main__":
	raise SystemExit(main())
