#!/usr/bin/env python3
"""Run DS4 CUDA per-layer stage kernel probes on the Spark 0/1/2 split."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MODEL = "DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf"
BASE_ENV = {
	"DS4_CUDA_SKIP_STARTUP_MODEL_CACHE": "1",
	"DS4_CUDA_MOE_EXPERT_SLICE_CACHE": "1",
	"DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE": "1",
	"DS4_CUDA_MOE_EXPERT_SLICE_STRICT": "1",
}
VARIANTS = {
	"default": {},
	"tile4": {"DS4_CUDA_MOE_TILE4": "1"},
	"down_block16": {"DS4_CUDA_MOE_DOWN_BLOCK16": "1"},
	"no_p2": {"DS4_CUDA_MOE_NO_P2": "1"},
}


@dataclass(frozen=True)
class Stage:
	name: str
	host: str
	ds4_dir: str
	model: str
	layer_begin: int
	layer_end: int
	proxy: str = ""


def default_stages() -> list[Stage]:
	return [
		Stage("spark0", "spark0@aitopatom-9ab9.local", "/tmp/ds4_stage_handoff_src", f"/home/spark0/models/ds4/{MODEL}", 0, 15),
		Stage("spark1", "spark1@edgexpert-d623.local", "/home/spark1/src/ds4", f"/home/spark1/models/ds4/{MODEL}", 15, 29),
		Stage("spark2", "spark2@10.10.5.2", "/home/spark2/src/ds4", f"/home/spark2/models/ds4/{MODEL}", 29, 43, "spark1@edgexpert-d623.local"),
	]


def ssh_base(stage: Stage, known_hosts: str) -> list[str]:
	args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={known_hosts}"]
	if stage.proxy:
		proxy = "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={} {} -W %h:%p".format(shlex.quote(known_hosts), shlex.quote(stage.proxy))
		args += ["-o", f"ProxyCommand={proxy}"]
	args.append(stage.host)
	return args


def q(s: str) -> str:
	return shlex.quote(s)


def parse_last_json(text: str) -> dict[str, Any]:
	for line in reversed(text.splitlines()):
		line = line.strip()
		if line.startswith("{") and line.endswith("}"):
			return json.loads(line)
	raise ValueError("no JSON object found")


def part_flag(part: str) -> str:
	if part == "layer":
		return "--cuda-layer-probe"
	if part == "ffn":
		return "--cuda-ffn-probe"
	if part == "moe":
		return "--cuda-moe-probe"
	raise ValueError(f"unsupported part {part}")


def env_prefix(extra: dict[str, str]) -> str:
	items = dict(BASE_ENV)
	items.update(extra)
	return " ".join(f"{k}={q(v)}" for k, v in items.items())


def run_probe(stage: Stage, args: argparse.Namespace, layer: int, part: str, variant: str, extra: dict[str, str], outdir: Path) -> dict[str, Any]:
	cmd = "{} ./ds4 -m {} {} --cuda-moe-layer {} --cuda-moe-tokens {} --cuda-moe-iters {}".format(
		env_prefix(extra),
		q(stage.model),
		part_flag(part),
		layer,
		args.batch,
		args.iterations,
	)
	remote = f"cd {q(stage.ds4_dir)} && {cmd}"
	t0 = time.time()
	rc = subprocess.run(ssh_base(stage, args.known_hosts) + [remote], text=True, capture_output=True)
	t1 = time.time()
	stem = f"{stage.name}_l{layer}_{part}_{variant}"
	(outdir / f"{stem}.out").write_text(rc.stdout or "", encoding="utf-8")
	(outdir / f"{stem}.err").write_text(rc.stderr or "", encoding="utf-8")
	item: dict[str, Any] = {
		"stage": stage.name,
		"layer": layer,
		"part": part,
		"variant": variant,
		"returncode": rc.returncode,
		"wall_ms": (t1 - t0) * 1000.0,
		"command": cmd,
	}
	try:
		obj = parse_last_json(rc.stdout or "")
		item.update(obj)
	except Exception as e:
		item["parse_error"] = str(e)
		item["stderr_tail"] = "\n".join((rc.stderr or "").splitlines()[-8:])
	return item


def summarize_stage(stage: Stage, rows: list[dict[str, Any]], batch: int) -> dict[str, Any]:
	layers = []
	for layer in range(stage.layer_begin, stage.layer_end):
		by_part = {r.get("part"): r for r in rows if r.get("stage") == stage.name and r.get("layer") == layer and r.get("variant") == "default"}
		layer_ms = float(by_part.get("layer", {}).get("best_ms", 0.0) or 0.0)
		ffn_ms = float(by_part.get("ffn", {}).get("best_ms", 0.0) or 0.0)
		moe_ms = float(by_part.get("moe", {}).get("best_ms", 0.0) or 0.0)
		layers.append({
			"layer": layer,
			"layer_ms": layer_ms,
			"ffn_ms": ffn_ms,
			"moe_ms": moe_ms,
			"attention_or_non_ffn_ms": max(0.0, layer_ms - ffn_ms),
			"non_moe_ffn_ms": max(0.0, ffn_ms - moe_ms),
			"layer_rows_per_s": ((float(batch) * 1000.0) / layer_ms) if layer_ms > 0.0 else 0.0,
		})
	sum_layer = sum(float(x["layer_ms"]) for x in layers)
	sum_ffn = sum(float(x["ffn_ms"]) for x in layers)
	sum_moe = sum(float(x["moe_ms"]) for x in layers)
	return {
		"stage": stage.name,
		"layer_range": [stage.layer_begin, stage.layer_end],
		"layer_count": stage.layer_end - stage.layer_begin,
		"sum_layer_ms": sum_layer,
		"sum_ffn_ms": sum_ffn,
		"sum_moe_ms": sum_moe,
		"moe_fraction_of_layer": (sum_moe / sum_layer) if sum_layer > 0.0 else 0.0,
		"ffn_fraction_of_layer": (sum_ffn / sum_layer) if sum_layer > 0.0 else 0.0,
		"layers": layers,
	}


def select_stages(args: argparse.Namespace) -> list[Stage]:
	stages = default_stages()
	if args.stage == "all":
		return stages
	return [s for s in stages if s.name == args.stage]


def selected_layers(stage: Stage, args: argparse.Namespace) -> list[int]:
	if args.layers:
		return [int(x) for x in args.layers.split(",") if x.strip()]
	return list(range(stage.layer_begin, stage.layer_end))


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--run-id", default=f"ds4-stage-kernel-profile-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
	ap.add_argument("--out-dir", default="")
	ap.add_argument("--stage", choices=["all", "spark0", "spark1", "spark2"], default="all")
	ap.add_argument("--layers", default="", help="Comma-separated layer override for every selected stage.")
	ap.add_argument("--mode", choices=["stage-profile", "moe-variant-sweep"], default="stage-profile")
	ap.add_argument("--batch", type=int, default=512)
	ap.add_argument("--iterations", type=int, default=3)
	ap.add_argument("--known-hosts", default="/private/tmp/ds4_spark_known_hosts")
	args = ap.parse_args()
	outdir = Path(args.out_dir or f"/private/tmp/{args.run_id}")
	outdir.mkdir(parents=True, exist_ok=True)
	stages = select_stages(args)
	rows: list[dict[str, Any]] = []
	for stage in stages:
		layers = selected_layers(stage, args)
		if args.mode == "stage-profile":
			for layer in layers:
				for part in ["layer", "ffn", "moe"]:
					rows.append(run_probe(stage, args, layer, part, "default", {}, outdir))
		else:
			for variant, extra in VARIANTS.items():
				for layer in layers:
					rows.append(run_probe(stage, args, layer, "moe", variant, extra, outdir))
	summaries = [summarize_stage(stage, rows, args.batch) for stage in stages] if args.mode == "stage-profile" else []
	artifact = {
		"format": "ds4-stage-kernel-profile-v1",
		"run_id": args.run_id,
		"mode": args.mode,
		"batch_size": args.batch,
		"iterations": args.iterations,
		"stage_count": len(stages),
		"stages": [{"stage": s.name, "layer_range": [s.layer_begin, s.layer_end]} for s in stages],
		"production_generation_eligible": False,
		"parity_status": "not_run",
		"rows": rows,
		"stage_summaries": summaries,
	}
	(outdir / "summary.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	print(json.dumps(artifact, indent=2, sort_keys=True))
	return 0 if all(int(r.get("returncode", 1)) == 0 and "parse_error" not in r for r in rows) else 2


if __name__ == "__main__":
	raise SystemExit(main())
