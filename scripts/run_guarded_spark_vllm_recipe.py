#!/usr/bin/env python3
"""Run spark-vllm-docker recipes only after a DS4 Flash launch-guard dry run."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0,str(REPO_ROOT))

from scripts import vllm_ds4_flash_launch_guard as launch_guard
from scripts import vllm_memory_safety_preflight as memory_preflight


BEGIN = "=== Generated Launch Script ==="
END = "=== What would be executed ==="


def insert_dry_run_arg(args: list[str]) -> list[str]:
	if "--dry-run" in args:
		return(list(args))
	out = list(args)
	try:
		idx = out.index("--")
	except ValueError:
		out.append("--dry-run")
	else:
		out.insert(idx, "--dry-run")
	return(out)


def has_dry_run_arg(args: list[str]) -> bool:
	return("--dry-run" in args)


def extract_launch_script(output: str) -> str:
	begin = output.find(BEGIN)
	if begin < 0:
		raise ValueError(f"dry-run output missing marker: {BEGIN}")
	begin += len(BEGIN)
	end = output.find(END, begin)
	if end < 0:
		raise ValueError(f"dry-run output missing marker: {END}")
	script = output[begin:end].strip()
	if script == "":
		raise ValueError("dry-run output contained an empty launch script")
	return(script + "\n")


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
	return(subprocess.run(cmd, text=True, capture_output=True))


def guard_script_text(script: str) -> dict[str, object]:
	with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
		f.write(script)
		path = Path(f.name)
	try:
		return(launch_guard.validate_path(path))
	finally:
		try:
			path.unlink()
		except OSError:
			pass


def memory_preflight_script_text(script: str, args: argparse.Namespace) -> dict[str, object]:
	with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
		f.write(script)
		path = Path(f.name)
	try:
		return(memory_preflight.evaluate_path(
			path,
			available_kv_gib=args.available_kv_gib,
			gpu_total_gib=args.gpu_total_gib,
			gpu_used_gib=args.gpu_used_gib,
			gpu_free_gib=args.gpu_free_gib,
			min_free_gib=args.min_free_gib,
			kv_headroom_ratio=args.kv_headroom_ratio,
			require_memory_sample=args.require_memory_sample,
			runtime_free_gib=args.runtime_free_gib,
			runtime_soft_min_free_gib=args.runtime_soft_min_free_gib,
			runtime_hard_min_free_gib=args.runtime_hard_min_free_gib,
		))
	finally:
		try:
			path.unlink()
		except OSError:
			pass


def print_process_output(result: subprocess.CompletedProcess[str]) -> None:
	if result.stdout:
		print(result.stdout, end="")
	if result.stderr:
		print(result.stderr, end="", file=sys.stderr)


def build_readiness_cmd(args: argparse.Namespace) -> list[str]:
	probe = Path(args.readiness_probe) if args.readiness_probe is not None else REPO_ROOT / "scripts" / "vllm_container_health_check.py"
	cmd = [sys.executable,str(probe)]
	cmd.extend(args.readiness_arg or [])
	return(cmd)


def run_readiness_probe(args: argparse.Namespace) -> int:
	cmd = build_readiness_cmd(args)
	print(f"post-launch readiness: {shlex.join(cmd)}")
	result = run_cmd(cmd)
	print_process_output(result)
	if result.returncode != 0:
		print("serving readiness probe failed", file=sys.stderr)
	return(result.returncode)


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--runner", required=True, help="Path to spark-vllm-docker run-recipe.sh or run-recipe.py")
	p.add_argument("--allow-blocked", action="store_true", help="Print guard failures but still execute the recipe")
	p.add_argument("--available-kv-gib", type=float, help="Measured vLLM available KV cache memory for preflight")
	p.add_argument("--gpu-total-gib", type=float, help="Measured GPU/system memory total for preflight")
	p.add_argument("--gpu-used-gib", type=float, help="Measured GPU/system memory used for preflight")
	p.add_argument("--gpu-free-gib", type=float, help="Measured GPU/system memory free for preflight")
	p.add_argument("--min-free-gib", type=float, default=8.0, help="Minimum free memory floor before launch")
	p.add_argument("--kv-headroom-ratio", type=float, default=0.10, help="Required KV headroom above the estimated request need")
	p.add_argument("--require-memory-sample", action="store_true", help="Block launch unless a memory sample is supplied")
	p.add_argument("--runtime-free-gib", type=float, help="Runtime free-memory sample for low-memory drain/terminate classification")
	p.add_argument("--runtime-soft-min-free-gib", type=float, default=10.0)
	p.add_argument("--runtime-hard-min-free-gib", type=float, default=6.0)
	p.add_argument("--post-launch-readiness", action="store_true", help="Run vLLM serving-readiness probe after recipe execution succeeds")
	p.add_argument("--readiness-probe", help="Override readiness probe script path for tests or custom deployments")
	p.add_argument("--readiness-arg", action="append", default=[], help="Argument passed through to the readiness probe; repeat for multiple args")
	p.add_argument("recipe_args", nargs=argparse.REMAINDER, help="Arguments passed to the recipe runner")
	return(p.parse_args())


def main() -> int:
	args = parse_args()
	if not args.recipe_args:
		print("error: recipe arguments are required", file=sys.stderr)
		return(2)
	runner = Path(args.runner)
	if not runner.exists():
		print(f"error: runner not found: {runner}", file=sys.stderr)
		return(2)
	original_cmd = [str(runner), *args.recipe_args]
	dry_cmd = [str(runner), *insert_dry_run_arg(args.recipe_args)]
	print(f"guard dry-run: {shlex.join(dry_cmd)}")
	dry = run_cmd(dry_cmd)
	print_process_output(dry)
	if dry.returncode != 0:
		return(dry.returncode)
	try:
		script = extract_launch_script(dry.stdout)
		result = guard_script_text(script)
	except Exception as e:
		print(f"launch guard failed to inspect dry-run output: {e}", file=sys.stderr)
		return(2)
	print(json.dumps({"launch_guard": result}, indent=2, sort_keys=True))
	mem_result = memory_preflight_script_text(script,args)
	print(json.dumps({"memory_preflight": mem_result}, indent=2, sort_keys=True))
	if result.get("status") == launch_guard.BAD and not args.allow_blocked:
		print("refusing to execute blocked vLLM launch profile", file=sys.stderr)
		return(3)
	if mem_result.get("status") == memory_preflight.BAD and not args.allow_blocked:
		print("refusing to execute memory-unsafe vLLM launch profile", file=sys.stderr)
		return(4)
	if has_dry_run_arg(args.recipe_args):
		return(0)
	print(f"guard execute: {shlex.join(original_cmd)}")
	run = subprocess.run(original_cmd)
	if run.returncode != 0:
		return(run.returncode)
	if args.post_launch_readiness:
		return(run_readiness_probe(args))
	return(0)


if __name__ == "__main__":
	raise SystemExit(main())
