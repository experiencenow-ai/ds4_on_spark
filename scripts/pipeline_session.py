#!/usr/bin/env python3
"""Coordinate a real-prompt DS4 PP=3 pipeline session.

This module intentionally has no fixture fallback.  It either talks to the
Spark-side ds4 binaries or returns a precise missing-runtime-hook blocker.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


BOS = "<｜begin▁of▁sentence｜>"
USER = "<｜User｜>"
ASSISTANT = "<｜Assistant｜>"
THINK = "<think>"
NO_THINK = "</think>"
DEFAULT_SYSTEM = "You are a helpful assistant"
MODEL_BASENAME = "DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf"
DEFAULT_CTX = 128
DEFAULT_BATCH = 512
HOOK_NEEDLE = "--pipeline-session-b1-worker"


class PipelineSessionError(RuntimeError):
	pass


@dataclasses.dataclass(frozen=True)
class StageConfig:
	stage_id: int
	name: str
	host: str
	ds4_dir: str
	model: str
	layer_begin: int
	layer_end: int
	include_head: bool
	listen: str = ""
	proxy: str = ""


@dataclasses.dataclass(frozen=True)
class CommandResult:
	command: list[str]
	returncode: int
	stdout: str
	stderr: str


@dataclasses.dataclass(frozen=True)
class GeneratedStep:
	step: int
	token_id: int
	text: str
	bytes: list[int]
	stage_logits_hashes: list[str]
	stage_logits_nonfinite: list[int]


@dataclasses.dataclass(frozen=True)
class PromptRun:
	mode: str
	prompt: str
	rendered_prompt: str
	prompt_token_ids: list[int]
	generated_token_ids: list[int]
	generated_text: str
	steps: list[GeneratedStep]
	raw_log_path: str
	blocker_kind: str = "none"
	blocker_detail: str = ""


def default_stages() -> list[StageConfig]:
	return [
		StageConfig(0, "spark0", "spark0", "/home/spark0/src/ds4", f"/home/spark0/models/ds4/{MODEL_BASENAME}", 0, 15, False, "10.10.1.1:19010"),
		StageConfig(1, "spark1", "spark1", "/home/spark1/src/ds4", f"/home/spark1/models/ds4/{MODEL_BASENAME}", 15, 29, False, "10.10.3.1:19011"),
		StageConfig(2, "spark2", "spark2", "/home/spark2/src/ds4", f"/home/spark2/models/ds4/{MODEL_BASENAME}", 29, 43, True, "10.10.5.2:19012"),
	]


def q(text: str) -> str:
	return shlex.quote(text)


def render_chat_prompt(prompt: str, system: str = DEFAULT_SYSTEM, think: bool = False) -> str:
	pieces = [BOS]
	if system:
		pieces.append(system)
	pieces.extend([USER, prompt, ASSISTANT, THINK if think else NO_THINK])
	return "".join(pieces)


def ssh_base(host: str, ssh_config: str, known_hosts: str) -> list[str]:
	base = ["ssh"]
	if ssh_config:
		base.extend(["-F", ssh_config])
	base.extend([
		"-o", "BatchMode=yes",
		"-o", "ConnectTimeout=10",
		"-o", "StrictHostKeyChecking=accept-new",
		"-o", f"UserKnownHostsFile={known_hosts}",
		host,
	])
	return base


def run_command(command: list[str], timeout_s: int = 900) -> CommandResult:
	proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_s)
	return CommandResult(command, proc.returncode, proc.stdout or "", proc.stderr or "")


def run_remote(stage: StageConfig, remote_command: str, ssh_config: str, known_hosts: str, timeout_s: int = 900) -> CommandResult:
	return run_command(ssh_base(stage.host, ssh_config, known_hosts) + [remote_command], timeout_s)


def parse_token_dump(stdout: str) -> list[int]:
	for line in stdout.splitlines():
		line = line.strip()
		if line.startswith("[") and line.endswith("]"):
			value = ast.literal_eval(line)
			if not isinstance(value, list) or not all(isinstance(item, int) for item in value):
				raise PipelineSessionError("token dump first list is not an integer token list")
			return list(value)
	raise PipelineSessionError("ds4 --dump-tokens output did not contain a token list")


def bytes_to_text(values: list[int]) -> str:
	return bytes(values).decode("utf-8", errors="replace")


def parse_logprob_dump(text: str) -> tuple[list[int], str, list[GeneratedStep]]:
	obj = json.loads(text)
	steps_raw = obj.get("steps")
	if not isinstance(steps_raw, list):
		raise PipelineSessionError("logprob dump missing steps[]")
	ids: list[int] = []
	out = bytearray()
	steps: list[GeneratedStep] = []
	for item in steps_raw:
		if not isinstance(item, dict):
			raise PipelineSessionError("logprob dump step is not an object")
		selected = item.get("selected")
		if not isinstance(selected, dict):
			raise PipelineSessionError("logprob dump step missing selected token")
		token_id = selected.get("id")
		raw_bytes = selected.get("bytes")
		if not isinstance(token_id, int) or not isinstance(raw_bytes, list) or not all(isinstance(v, int) for v in raw_bytes):
			raise PipelineSessionError("logprob dump selected token is malformed")
		ids.append(token_id)
		out.extend(raw_bytes)
		steps.append(GeneratedStep(int(item.get("step", len(steps))), token_id, bytes_to_text(raw_bytes), raw_bytes, [], []))
	return ids, out.decode("utf-8", errors="replace"), steps


def hash_token_ids(token_ids: list[int]) -> str:
	data = json.dumps(token_ids, separators=(",", ":")).encode("utf-8")
	return "sha256:" + hashlib.sha256(data).hexdigest()


def make_prefill_payload(token_ids: list[int], batch_size: int = DEFAULT_BATCH, pad_token_id: int = 0) -> dict[str, Any]:
	if not token_ids:
		raise PipelineSessionError("prefill requires at least one token")
	if batch_size < 1:
		raise PipelineSessionError("batch_size must be positive")
	return {
		"op": "prefill_chunk",
		"batch_size": batch_size,
		"real_row": 0,
		"row0_token_ids": list(token_ids),
		"padding_rows": batch_size - 1,
		"padding_token_id": pad_token_id,
		"token_ids_sha256": hash_token_ids(token_ids),
	}


def validate_decode_steps(steps: list[GeneratedStep], stage_count: int = 3) -> None:
	if not steps:
		raise PipelineSessionError("decode log has no steps")
	for step in steps:
		if len(step.stage_logits_hashes) != stage_count:
			raise PipelineSessionError(f"decode step {step.step} missing per-stage logits hashes")
		if len(step.stage_logits_nonfinite) != stage_count:
			raise PipelineSessionError(f"decode step {step.step} missing per-stage nonfinite counters")
		for h in step.stage_logits_hashes:
			if not isinstance(h, str) or not h.startswith("fnv64:") or h == "fnv64:0000000000000000":
				raise PipelineSessionError(f"decode step {step.step} has invalid stage hash {h!r}")
		for value in step.stage_logits_nonfinite:
			if int(value) != 0:
				raise PipelineSessionError(f"decode step {step.step} has nonfinite logits")


def assert_matching_token_prefix(pp3_ids: list[int], pp1_ids: list[int], count: int) -> None:
	left = pp3_ids[:count]
	right = pp1_ids[:count]
	if left != right:
		raise PipelineSessionError(f"PP=3 token IDs differ from PP=1 for first {count}: pp3={left} pp1={right}")


class PipelineSession:
	def __init__(
			self,
			stages: list[StageConfig] | None = None,
			ssh_config: str = str(Path.home() / ".ssh" / "config"),
			known_hosts: str = "/private/tmp/ds4_lane_a_known_hosts",
			runner: Callable[[StageConfig, str, str, str, int], CommandResult] = run_remote):
		self.stages = stages if stages is not None else default_stages()
		self.ssh_config = ssh_config
		self.known_hosts = known_hosts
		self.runner = runner

	def tokenize_rendered_prompt(self, rendered_prompt: str) -> list[int]:
		stage = self.stages[0]
		cmd = f"cd {q(stage.ds4_dir)} && ./ds4 -m {q(stage.model)} --dump-tokens -p {q(rendered_prompt)}"
		rc = self.runner(stage, cmd, self.ssh_config, self.known_hosts, 300)
		if rc.returncode != 0:
			raise PipelineSessionError(f"ds4 tokenizer failed rc={rc.returncode}: {rc.stderr.strip()}")
		return parse_token_dump(rc.stdout)

	def check_worker_hooks(self) -> list[dict[str, Any]]:
		results: list[dict[str, Any]] = []
		for stage in self.stages:
			cmd = f"cd {q(stage.ds4_dir)} && ./ds4 --help 2>&1"
			rc = self.runner(stage, cmd, self.ssh_config, self.known_hosts, 120)
			available = rc.returncode == 0 and HOOK_NEEDLE in (rc.stdout + rc.stderr)
			results.append({
				"stage_id": stage.stage_id,
				"stage": stage.name,
				"host": stage.host,
				"hook": HOOK_NEEDLE,
				"available": available,
				"returncode": rc.returncode,
				"stderr_tail": "\n".join(rc.stderr.splitlines()[-8:]),
			})
		return results

	def require_worker_hooks(self) -> None:
		results = self.check_worker_hooks()
		missing = [item for item in results if not item["available"]]
		if missing:
			raise PipelineSessionError(json.dumps({
				"blocker_kind": "missing_pipeline_session_worker",
				"blocker_detail": f"stage ds4 binaries must expose {HOOK_NEEDLE}",
				"hook_status": results,
			}, sort_keys=True))

	def run_pp1_baseline(self, prompt: str, max_tokens: int, out_dir: Path, system: str = DEFAULT_SYSTEM) -> PromptRun:
		out_dir.mkdir(parents=True, exist_ok=True)
		stage = self.stages[0]
		log_remote = f"/tmp/ds4_lane_a_pp1_{int(time.time())}.json"
		cmd = "cd {} && ./ds4 -m {} -p {} --system {} --nothink --temp 0 --top-p 1 -n {} --ctx {} --dump-logprobs {} && cat {}".format(
			q(stage.ds4_dir),
			q(stage.model),
			q(prompt),
			q(system),
			max_tokens,
			DEFAULT_CTX,
			q(log_remote),
			q(log_remote),
		)
		rc = self.runner(stage, cmd, self.ssh_config, self.known_hosts, 1800)
		raw_path = out_dir / "pp1_logprobs.json"
		raw_path.write_text(rc.stdout, encoding="utf-8")
		(out_dir / "pp1.stderr").write_text(rc.stderr, encoding="utf-8")
		if rc.returncode != 0:
			raise PipelineSessionError(f"PP=1 baseline failed rc={rc.returncode}: {rc.stderr.strip()}")
		ids, text, steps = parse_logprob_dump(rc.stdout)
		rendered = render_chat_prompt(prompt, system, think=False)
		return PromptRun("pp1", prompt, rendered, [], ids, text, steps, str(raw_path))

	def prefill_chunk(self, token_ids: list[int]) -> dict[str, Any]:
		self.require_worker_hooks()
		return make_prefill_payload(token_ids)

	def decode_one(self) -> GeneratedStep:
		self.require_worker_hooks()
		raise PipelineSessionError("pipeline session worker hook is present, but decode RPC client is not implemented in this checkout")

	def run_pp3(self, prompt: str, max_tokens: int, out_dir: Path, system: str = DEFAULT_SYSTEM) -> PromptRun:
		out_dir.mkdir(parents=True, exist_ok=True)
		rendered = render_chat_prompt(prompt, system, think=False)
		token_ids = self.tokenize_rendered_prompt(rendered)
		(out_dir / "rendered_prompt.txt").write_text(rendered, encoding="utf-8")
		(out_dir / "prompt_token_ids.json").write_text(json.dumps(token_ids) + "\n", encoding="utf-8")
		make_prefill_payload(token_ids)
		self.require_worker_hooks()
		raise PipelineSessionError("pipeline session worker hook exists but the PP=3 session loop is not wired")


def main_args(argv: list[str]) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--prompt", required=True)
	ap.add_argument("--max-tokens", type=int, default=8)
	ap.add_argument("--out-dir", default=f"/private/tmp/ds4_lane_a_session_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
	ap.add_argument("--mode", choices=["pp1", "pp3", "all"], default="all")
	args = ap.parse_args(argv)
	session = PipelineSession()
	out_dir = Path(args.out_dir)
	if args.mode in ("pp3", "all"):
		run = session.run_pp3(args.prompt, args.max_tokens, out_dir / "pp3")
		print(json.dumps(dataclasses.asdict(run), indent=2, sort_keys=True))
	if args.mode in ("pp1", "all"):
		run = session.run_pp1_baseline(args.prompt, args.max_tokens, out_dir / "pp1")
		print(json.dumps(dataclasses.asdict(run), indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main_args(__import__("sys").argv[1:]))
