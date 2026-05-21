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


def print_process_output(result: subprocess.CompletedProcess[str]) -> None:
	if result.stdout:
		print(result.stdout, end="")
	if result.stderr:
		print(result.stderr, end="", file=sys.stderr)


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--runner", required=True, help="Path to spark-vllm-docker run-recipe.sh or run-recipe.py")
	p.add_argument("--allow-blocked", action="store_true", help="Print guard failures but still execute the recipe")
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
	if result.get("status") == launch_guard.BAD and not args.allow_blocked:
		print("refusing to execute blocked vLLM launch profile", file=sys.stderr)
		return(3)
	if has_dry_run_arg(args.recipe_args):
		return(0)
	print(f"guard execute: {shlex.join(original_cmd)}")
	run = subprocess.run(original_cmd)
	return(run.returncode)


if __name__ == "__main__":
	raise SystemExit(main())
