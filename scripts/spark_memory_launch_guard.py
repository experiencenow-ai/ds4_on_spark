#!/usr/bin/env python3
"""Block Spark model launches that cannot fit in current host memory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

FORMAT = "ds4-spark-memory-launch-guard-v1"
BLOCKED = "blocked"
PASSED = "passed"
RUNTIME_PATTERNS = (
	"vllm serve",
	"VLLM::",
	"llama-server",
	"ds4_vllm_lazy_proxy.py",
)


def gib(kib: float) -> float:
	return(kib / 1024.0 / 1024.0)


def read_meminfo(path: Path = Path("/proc/meminfo")) -> dict[str,int]:
	out: dict[str,int] = {}
	for line in path.read_text(encoding="utf-8").splitlines():
		parts = line.replace(":","").split()
		if len(parts) >= 2:
			try:
				out[parts[0]] = int(parts[1])
			except ValueError:
				pass
	return(out)


def process_rows() -> list[dict[str,Any]]:
	cp = subprocess.run(["ps","-eo","pid=,rss=,vsz=,comm=,args="],text=True,capture_output=True,check=False)
	rows: list[dict[str,Any]] = []
	for line in cp.stdout.splitlines():
		parts = line.split(None,4)
		if len(parts) < 5:
			continue
		try:
			pid,rss,vsz = int(parts[0]),int(parts[1]),int(parts[2])
		except ValueError:
			continue
		rows.append({"pid":pid,"rss_kib":rss,"vsz_kib":vsz,"comm":parts[3],"args":parts[4]})
	return(rows)


def runtime_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
	out = []
	for row in rows:
		args = str(row.get("args",""))
		comm = str(row.get("comm",""))
		if any(pat in args or pat in comm for pat in RUNTIME_PATTERNS):
			out.append(row)
	return(out)


def model_gib(path: Path | None, explicit: float | None) -> float:
	if explicit is not None:
		return(float(explicit))
	if path is None:
		return(0.0)
	return(path.stat().st_size / 1024.0 / 1024.0 / 1024.0)


def estimate_required_gib(model_weight_gib: float, weight_multiplier: float, ctx_tokens: int, parallel: int, kv_mib_per_1k_token_slot: float, extra_gib: float) -> dict[str,float]:
	weights = model_weight_gib * weight_multiplier
	kv = (max(ctx_tokens,0) / 1000.0) * max(parallel,1) * kv_mib_per_1k_token_slot / 1024.0
	total = weights + kv + extra_gib
	return({
		"model_weight_gib": round(model_weight_gib,3),
		"weights_with_multiplier_gib": round(weights,3),
		"kv_estimate_gib": round(kv,3),
		"extra_gib": round(extra_gib,3),
		"total_required_gib": round(total,3),
	})


def issue(kind: str, detail: str) -> dict[str,str]:
	return({"kind":kind,"detail":detail})


def evaluate(args: argparse.Namespace, meminfo: dict[str,int] | None = None, rows: list[dict[str,Any]] | None = None) -> dict[str,Any]:
	meminfo = meminfo if meminfo is not None else read_meminfo()
	rows = rows if rows is not None else process_rows()
	rt = runtime_rows(rows)
	model_path = Path(args.model_path) if args.model_path else None
	required = estimate_required_gib(
		model_gib(model_path,args.model_gib),
		args.weight_multiplier,
		args.ctx_tokens,
		args.parallel,
		args.kv_mib_per_1k_token_slot,
		args.extra_gib,
	)
	mem_available = gib(float(meminfo.get("MemAvailable",0)))
	swap_free = gib(float(meminfo.get("SwapFree",0)))
	commit_margin = gib(float(meminfo.get("CommitLimit",0) - meminfo.get("Committed_AS",0)))
	physical_margin = mem_available - args.reserve_gib
	commit_required = required["total_required_gib"] * args.commit_multiplier
	issues: list[dict[str,str]] = []
	if args.exclusive and rt:
		issues.append(issue("resident_runtime_present",f"{len(rt)} model runtime process(es) already present; drain/stop resident lane before loading another model"))
	if required["total_required_gib"] > physical_margin:
		issues.append(issue("insufficient_physical_memory",f"estimated launch needs {required['total_required_gib']:.2f} GiB, MemAvailable-reserve is {physical_margin:.2f} GiB"))
	if commit_required > commit_margin:
		issues.append(issue("insufficient_commit_margin",f"estimated committed footprint {commit_required:.2f} GiB exceeds CommitLimit-Committed_AS margin {commit_margin:.2f} GiB"))
	if swap_free < args.min_swap_free_gib:
		issues.append(issue("low_swap_cushion",f"SwapFree {swap_free:.2f} GiB is below cushion {args.min_swap_free_gib:.2f} GiB"))
	return({
		"format": FORMAT,
		"status": BLOCKED if issues else PASSED,
		"estimate": required,
		"host_memory": {
			"mem_available_gib": round(mem_available,3),
			"swap_free_gib": round(swap_free,3),
			"commit_margin_gib": round(commit_margin,3),
			"reserve_gib": round(args.reserve_gib,3),
		},
		"resident_runtimes": [
			{
				"pid": row["pid"],
				"rss_gib": round(gib(float(row["rss_kib"])),3),
				"vsz_gib": round(gib(float(row["vsz_kib"])),3),
				"comm": row["comm"],
				"args": str(row["args"])[:240],
			}
			for row in sorted(rt,key=lambda item: int(item["vsz_kib"]),reverse=True)
		],
		"issues": issues,
		"recommended_action": "refuse launch; drain resident model or lower ctx/parallel/batch until estimate fits" if issues else "launch memory guard passed",
	})


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--model-path", default="")
	p.add_argument("--model-gib", type=float)
	p.add_argument("--weight-multiplier", type=float, default=float(os.environ.get("DS4_MEMORY_GUARD_WEIGHT_MULTIPLIER","1.20")))
	p.add_argument("--ctx-tokens", type=int, default=int(os.environ.get("DS4_MEMORY_GUARD_CTX_TOKENS","0")))
	p.add_argument("--parallel", type=int, default=int(os.environ.get("DS4_MEMORY_GUARD_PARALLEL","1")))
	p.add_argument("--kv-mib-per-1k-token-slot", type=float, default=float(os.environ.get("DS4_MEMORY_GUARD_KV_MIB_PER_1K_TOKEN_SLOT","1.0")))
	p.add_argument("--extra-gib", type=float, default=float(os.environ.get("DS4_MEMORY_GUARD_EXTRA_GIB","4.0")))
	p.add_argument("--reserve-gib", type=float, default=float(os.environ.get("DS4_MEMORY_GUARD_RESERVE_GIB","16.0")))
	p.add_argument("--commit-multiplier", type=float, default=float(os.environ.get("DS4_MEMORY_GUARD_COMMIT_MULTIPLIER","1.0")))
	p.add_argument("--min-swap-free-gib", type=float, default=float(os.environ.get("DS4_MEMORY_GUARD_MIN_SWAP_FREE_GIB","4.0")))
	p.add_argument("--exclusive", action=argparse.BooleanOptionalAction, default=os.environ.get("DS4_MEMORY_GUARD_EXCLUSIVE","1") != "0")
	return(p.parse_args())


def main() -> int:
	result = evaluate(parse_args())
	print(json.dumps(result,indent=2,sort_keys=True))
	return(2 if result["status"] == BLOCKED else 0)


if __name__ == "__main__":
	raise SystemExit(main())
