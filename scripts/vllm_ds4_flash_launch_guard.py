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


def validate_command(path: Path, defaults: dict[str, Any], command: str) -> dict[str, Any]:
	tokens = command_tokens(command)
	flags = flag_values(tokens)
	prefix = prefix_policy(tokens)
	max_model_len = int_flag(flags, "--max-model-len", int(defaults.get("max_model_len", 0) or 0))
	max_num_seqs = int_flag(flags, "--max-num-seqs", int(defaults.get("max_num_seqs", 0) or 0))
	max_num_batched_tokens = int_flag(flags, "--max-num-batched-tokens", int(defaults.get("max_num_batched_tokens", 0) or 0))
	gpu_memory_utilization = float_flag(flags, "--gpu-memory-utilization", float(defaults.get("gpu_memory_utilization", 0.0) or 0.0))
	issues: list[dict[str, str]] = []
	warnings: list[dict[str, str]] = []
	dupes = {k: v for k, v in flags.items() if len(v) > 1}
	if "--max-num-batched-tokens" in dupes:
		issues.append({
			"kind": "duplicate_max_num_batched_tokens",
			"detail": "duplicate --max-num-batched-tokens makes the effective graph/KV profile ambiguous",
		})
	if is_dsv4_flash(command):
		if prefix != "disabled":
			issues.append({
				"kind": "prefix_cache_c512_rank0_kill_risk",
				"detail": "DeepSeek-V4-Flash Spark4/Spark5 c512 stress reproduced rank0/API death unless --no-enable-prefix-caching is explicit",
			})
		if max_model_len >= 200000 and max_num_batched_tokens <= 512:
			issues.append({
				"kind": "cuda_graph_kv_starvation_risk",
				"detail": "200k context with max_num_batched_tokens<=512 produced 512-size graph capture, low KV headroom, worker exit, and Spark4 SSH banner timeouts",
			})
		if max_model_len >= 200000 and max_num_batched_tokens > 8192:
			issues.append({
				"kind": "kv_allocation_risk",
				"detail": "existing tuning evidence rejected >8192 scheduler tokens for the 200k-context Spark4/Spark5 lane",
			})
		if max_num_seqs >= 512 and max_model_len >= 200000:
			warnings.append({
				"kind": "high_sequence_budget",
				"detail": "c512 at 200k context must be stress-tested after launch; this is a queueing/throughput profile, not a safe default chat profile",
			})
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
			"gpu_memory_utilization": gpu_memory_utilization,
		},
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
