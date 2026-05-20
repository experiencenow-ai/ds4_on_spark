#!/usr/bin/env python3
"""Coordinate a B=1 DS4 PP=3 prompt-token loop through CUDA stage probes.

This module intentionally has no fixture fallback.  It drives the existing
`--cuda-batch-stack-probe` path on Spark0/Spark1/Spark2, moves real boundary
activation files between stages, reads the stage2 argmax token, and feeds that
token back into Spark0's row-token input for the next step.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import os
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
DEFAULT_BATCH = 1
HC_MULT = 4
HIDDEN_SIZE = 4096
BOUNDARY_DTYPE_BYTES = 4
PROBE_NEEDLE = "--cuda-batch-stack-probe"


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
c,addr=s.accept(); t0=time.time()
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
os.replace(tmp,path); t1=time.time()
print(json.dumps({"bytes":n,"sha256":h.hexdigest(),"transfer_ms":(t1-t0)*1000.0,"peer":addr[0]}), flush=True)
"""


SEND_CODE = r"""
import hashlib,json,os,socket,struct,sys,time
host=sys.argv[1]; port=int(sys.argv[2]); path=sys.argv[3]; timeout=float(sys.argv[4]); expected=int(sys.argv[5])
t_wait=time.time()
while True:
    if os.path.exists(path) and (expected <= 0 or os.path.getsize(path) == expected): break
    if (time.time()-t_wait) > timeout:
        size=os.path.getsize(path) if os.path.exists(path) else -1
        raise RuntimeError(f"timeout waiting for {path} size={size} expected={expected}")
    time.sleep(0.01)
data=open(path,"rb").read()
if expected > 0 and len(data) != expected: raise RuntimeError(f"size {len(data)} expected {expected}")
h=hashlib.sha256(data).digest(); t0=time.time(); last=None
while True:
    try:
        s=socket.create_connection((host,port),timeout=5.0); break
    except OSError as e:
        last=e
        if (time.time()-t0) > timeout: raise RuntimeError(f"connect timeout: {last}")
        time.sleep(0.05)
with s:
    s.sendall(struct.pack(">Q",len(data))); s.sendall(data); s.sendall(h)
t1=time.time()
print(json.dumps({"bytes":len(data),"sha256":h.hex(),"transfer_ms":(t1-t0)*1000.0,"dest":host}), flush=True)
"""


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
		StageConfig(0, "spark0", "spark0@aitopatom-9ab9.local", "/home/spark0/src/ds4", f"/home/spark0/models/ds4/{MODEL_BASENAME}", 0, 15, False, ""),
		StageConfig(1, "spark1", "spark1", "/home/spark1/src/ds4", f"/home/spark1/models/ds4/{MODEL_BASENAME}", 15, 29, False, "10.10.1.248"),
		StageConfig(2, "spark2", "spark2", "/home/spark2/src/ds4", f"/home/spark2/models/ds4/{MODEL_BASENAME}", 29, 43, True, "10.10.5.2"),
	]


def load_stage_manifest(path: str) -> list[StageConfig]:
	raw = json.loads(Path(path).read_text(encoding="utf-8"))
	items = raw.get("stages") if isinstance(raw, dict) else raw
	if not isinstance(items, list):
		raise PipelineSessionError("stage manifest must contain a stages list")
	stages = []
	for item in items:
		if not isinstance(item, dict):
			raise PipelineSessionError("stage manifest entry must be an object")
		stages.append(StageConfig(
			int(item["stage_id"]),
			str(item["name"]),
			str(item["host"]),
			str(item["ds4_dir"]),
			str(item["model"]),
			int(item["layer_begin"]),
			int(item["layer_end"]),
			bool(item["include_head"]),
			str(item.get("listen", "")),
			str(item.get("proxy", "")),
		))
	if [s.stage_id for s in stages] != list(range(len(stages))):
		raise PipelineSessionError("stage manifest stage_id values must be dense from zero")
	return stages


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


def popen_remote(stage: StageConfig, remote_command: str, ssh_config: str, known_hosts: str) -> subprocess.Popen[str]:
	return subprocess.Popen(
		ssh_base(stage.host, ssh_config, known_hosts) + [remote_command],
		text=True,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
	)


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


def parse_last_json(text: str) -> dict[str, Any]:
	for line in reversed(text.splitlines()):
		line = line.strip()
		if line.startswith("{") and line.endswith("}"):
			obj = json.loads(line)
			if not isinstance(obj, dict):
				raise PipelineSessionError("last JSON record is not an object")
			return obj
	raise PipelineSessionError("command output did not contain a JSON object")


def hash_token_ids(token_ids: list[int]) -> str:
	data = json.dumps(token_ids, separators=(",", ":")).encode("utf-8")
	return "sha256:" + hashlib.sha256(data).hexdigest()


def boundary_bytes(batch_size: int = DEFAULT_BATCH) -> int:
	return batch_size * HC_MULT * HIDDEN_SIZE * BOUNDARY_DTYPE_BYTES


def prompt_tokens_file(run_dir: str, step: int) -> str:
	return f"{run_dir}/prompt_step{step:03d}.bin"


def pattern_path(run_dir: str, name: str) -> str:
	return f"{run_dir}/{name}_%u.bin"


def actual_pattern_file(pattern: str, index: int = 0) -> str:
	return pattern.replace("%u", str(index)) if "%u" in pattern else pattern


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


def format_fnv(value: Any) -> str:
	if isinstance(value, str):
		v = value
	else:
		v = f"{int(value):016x}"
	return v if v.startswith("fnv64:") else f"fnv64:{v}"


def json_bool(value: bool) -> str:
	return "true" if value else "false"


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

	def check_probe_hooks(self) -> list[dict[str, Any]]:
		results: list[dict[str, Any]] = []
		for stage in self.stages:
			cmd = f"cd {q(stage.ds4_dir)} && ./ds4 --help 2>&1"
			rc = self.runner(stage, cmd, self.ssh_config, self.known_hosts, 120)
			available = rc.returncode == 0 and PROBE_NEEDLE in (rc.stdout + rc.stderr)
			results.append({
				"stage_id": stage.stage_id,
				"stage": stage.name,
				"host": stage.host,
				"hook": PROBE_NEEDLE,
				"available": available,
				"returncode": rc.returncode,
				"stderr_tail": "\n".join(rc.stderr.splitlines()[-8:]),
			})
		return results

	def require_probe_hooks(self) -> None:
		results = self.check_probe_hooks()
		missing = [item for item in results if not item["available"]]
		if missing:
			raise PipelineSessionError(json.dumps({
				"blocker_kind": "missing_cuda_batch_stack_probe",
				"blocker_detail": f"stage ds4 binaries must expose {PROBE_NEEDLE}",
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

	def remote_step_dir(self, run_id: str, step: int) -> str:
		return f"/tmp/ds4_lane_a_pp3_{run_id}/step{step:03d}"

	def write_remote_prompt_tokens(self, stage: StageConfig, path: str, token_ids: list[int]) -> None:
		code = "import json,os,struct,sys; ids=json.loads(sys.argv[1]); os.makedirs(os.path.dirname(sys.argv[2]), exist_ok=True); open(sys.argv[2],'wb').write(struct.pack('<' + 'i'*len(ids), *ids))"
		cmd = "python3 -c {} {} {}".format(q(code), q(json.dumps(token_ids, separators=(",", ":"))), q(path))
		rc = self.runner(stage, cmd, self.ssh_config, self.known_hosts, 120)
		if rc.returncode != 0:
			raise PipelineSessionError(f"{stage.name} prompt token file write failed rc={rc.returncode}: {rc.stderr.strip()}")

	def build_stage_probe_command(self, stage: StageConfig, run_id: str, step: int, prompt_file: str, input_file: str | None, output_file: str | None) -> str:
		env = [
			f"DS4_CUDA_STACK_PROBE_LAYER_BEGIN={stage.layer_begin}",
			f"DS4_CUDA_STACK_PROBE_LAYER_END={stage.layer_end}",
			"DS4_CUDA_MOE_SLICE_TILE8=1",
		]
		if stage.stage_id == 0:
			env.append("DS4_CUDA_STACK_PROBE_EMBED_INPUT=1")
		if not stage.include_head:
			env.append("DS4_CUDA_STACK_PROBE_NO_HEAD=1")
		if input_file:
			env.extend([f"DS4_CUDA_STACK_PROBE_INPUT_HC_FILE={q(input_file)}", "DS4_CUDA_STACK_PROBE_INPUT_WAIT_MS=30000"])
		if output_file:
			env.append(f"DS4_CUDA_STACK_PROBE_OUTPUT_HC_FILE={q(output_file)}")
		cmd = " ".join(env + [
			"./ds4",
			"-m",
			q(stage.model),
			"--cuda-batch-stack-probe",
			"--batch",
			str(DEFAULT_BATCH),
			"--prompt-tokens-file",
			q(prompt_file),
			"--emit-output-head-argmax",
		])
		return f"mkdir -p {q(self.remote_step_dir(run_id, step))}; cd {q(stage.ds4_dir)}; env {cmd}"

	def run_stage_probe(self, stage: StageConfig, run_id: str, step: int, prompt_file: str, input_file: str | None, output_file: str | None, out_dir: Path) -> dict[str, Any]:
		cmd = self.build_stage_probe_command(stage, run_id, step, prompt_file, input_file, output_file)
		rc = self.runner(stage, cmd, self.ssh_config, self.known_hosts, 2400)
		(out_dir / f"stage{stage.stage_id}_step{step}.out").write_text(rc.stdout, encoding="utf-8")
		(out_dir / f"stage{stage.stage_id}_step{step}.err").write_text(rc.stderr, encoding="utf-8")
		if rc.returncode != 0:
			raise PipelineSessionError(f"{stage.name} batch-stack probe failed rc={rc.returncode}: {rc.stderr.strip()[-2000:]}")
		obj = parse_last_json(rc.stdout)
		(out_dir / f"stage{stage.stage_id}_step{step}.json").write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
		return obj

	def tcp_transfer_file(self, src: StageConfig, dst: StageConfig, src_path: str, dst_path: str, port: int, out_dir: Path, label: str) -> dict[str, Any]:
		if src.host == dst.host:
			item = {
				"bytes": boundary_bytes(),
				"src": src.name,
				"dst": dst.name,
				"label": label,
				"transfer_kind": "same_host_file",
				"transfer_ms": 0.0,
			}
			(out_dir / f"{label}.json").write_text(json.dumps(item, indent=2, sort_keys=True) + "\n", encoding="utf-8")
			return item
		if not dst.listen:
			raise PipelineSessionError(f"{dst.name} is missing listen IP for TCP boundary transfer")
		expected = boundary_bytes()
		recv_cmd = "python3 -c {} {} {} {}".format(q(RECV_CODE), port, q(dst_path), expected)
		send_cmd = "python3 -c {} {} {} {} {} {}".format(q(SEND_CODE), q(dst.listen), port, q(src_path), 120.0, expected)
		recv = popen_remote(dst, recv_cmd, self.ssh_config, self.known_hosts)
		time.sleep(0.15)
		send = popen_remote(src, send_cmd, self.ssh_config, self.known_hosts)
		send_out, send_err = send.communicate(timeout=180)
		recv_out, recv_err = recv.communicate(timeout=180)
		(out_dir / f"{label}.send.out").write_text(send_out or "", encoding="utf-8")
		(out_dir / f"{label}.send.err").write_text(send_err or "", encoding="utf-8")
		(out_dir / f"{label}.recv.out").write_text(recv_out or "", encoding="utf-8")
		(out_dir / f"{label}.recv.err").write_text(recv_err or "", encoding="utf-8")
		if send.returncode != 0 or recv.returncode != 0:
			raise PipelineSessionError(f"{label} transfer failed send_rc={send.returncode} recv_rc={recv.returncode}: {(send_err or recv_err or '').strip()}")
		item = parse_last_json(recv_out or "")
		item["src"] = src.name
		item["dst"] = dst.name
		item["label"] = label
		(out_dir / f"{label}.json").write_text(json.dumps(item, indent=2, sort_keys=True) + "\n", encoding="utf-8")
		return item

	def stage_hash(self, stage: StageConfig, obj: dict[str, Any]) -> tuple[str, int]:
		if stage.include_head:
			hashes = obj.get("logits_fnv64s")
			nonfinites = obj.get("logits_nonfinites")
			h = hashes[-1] if isinstance(hashes, list) and hashes else obj.get("logits_fnv64")
			nf = nonfinites[-1] if isinstance(nonfinites, list) and nonfinites else obj.get("logits_nonfinite", 0)
		else:
			hashes = obj.get("out_fnv64s")
			nonfinites = obj.get("out_nonfinites")
			h = hashes[-1] if isinstance(hashes, list) and hashes else obj.get("out_fnv64")
			nf = nonfinites[-1] if isinstance(nonfinites, list) and nonfinites else obj.get("out_nonfinite", 0)
		return format_fnv(h), int(nf)

	def committed_token(self, obj: dict[str, Any]) -> int:
		value = obj.get("pipeline_argmax_token")
		if isinstance(value, int):
			return value
		ids = obj.get("committed_token_ids")
		if isinstance(ids, list) and ids and isinstance(ids[-1], int):
			return ids[-1]
		raise PipelineSessionError("stage2 did not emit pipeline_argmax_token or committed_token_ids[-1]")

	def decode_one(self, run_id: str, step: int, token_ids: list[int], out_dir: Path) -> GeneratedStep:
		stage0, stage1, stage2 = self.stages
		run_dir = self.remote_step_dir(run_id, step)
		prompt_file = prompt_tokens_file(run_dir, step)
		stage0_out_pattern = pattern_path(run_dir, "stage0_out")
		stage1_in_pattern = pattern_path(run_dir, "stage1_in")
		stage1_out_pattern = pattern_path(run_dir, "stage1_out")
		stage2_in_pattern = pattern_path(run_dir, "stage2_in")
		self.write_remote_prompt_tokens(stage0, prompt_file, token_ids)
		r0 = self.run_stage_probe(stage0, run_id, step, prompt_file, None, stage0_out_pattern, out_dir)
		self.tcp_transfer_file(stage0, stage1, actual_pattern_file(stage0_out_pattern), actual_pattern_file(stage1_in_pattern), 19100 + step, out_dir, f"step{step}_stage0_to_stage1")
		r1 = self.run_stage_probe(stage1, run_id, step, prompt_file, stage1_in_pattern, stage1_out_pattern, out_dir)
		self.tcp_transfer_file(stage1, stage2, actual_pattern_file(stage1_out_pattern), actual_pattern_file(stage2_in_pattern), 19200 + step, out_dir, f"step{step}_stage1_to_stage2")
		r2 = self.run_stage_probe(stage2, run_id, step, prompt_file, stage2_in_pattern, None, out_dir)
		token_id = self.committed_token(r2)
		hashes: list[str] = []
		nonfinites: list[int] = []
		for stage, obj in ((stage0, r0), (stage1, r1), (stage2, r2)):
			h, nf = self.stage_hash(stage, obj)
			hashes.append(h)
			nonfinites.append(nf)
		return GeneratedStep(step, token_id, "", [], hashes, nonfinites)

	def run_pp3(self, prompt: str, max_tokens: int, out_dir: Path, system: str = DEFAULT_SYSTEM) -> PromptRun:
		out_dir.mkdir(parents=True, exist_ok=True)
		rendered = render_chat_prompt(prompt, system, think=False)
		token_ids = self.tokenize_rendered_prompt(rendered)
		if not token_ids:
			raise PipelineSessionError("rendered prompt tokenization returned no tokens")
		(out_dir / "rendered_prompt.txt").write_text(rendered, encoding="utf-8")
		(out_dir / "prompt_token_ids.json").write_text(json.dumps(token_ids) + "\n", encoding="utf-8")
		self.require_probe_hooks()
		run_id = f"{int(time.time())}_{os.getpid()}"
		context_ids = list(token_ids)
		steps: list[GeneratedStep] = []
		generated_ids: list[int] = []
		for step in range(max_tokens):
			item = self.decode_one(run_id, step, context_ids, out_dir)
			steps.append(item)
			generated_ids.append(item.token_id)
			context_ids.append(item.token_id)
		validate_decode_steps(steps, len(self.stages))
		raw_path = out_dir / "pp3_steps.json"
		raw_path.write_text(json.dumps([dataclasses.asdict(s) for s in steps], indent=2, sort_keys=True) + "\n", encoding="utf-8")
		return PromptRun("pp3", prompt, rendered, token_ids, generated_ids, "", steps, str(raw_path))


def main_args(argv: list[str]) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--prompt", required=True)
	ap.add_argument("--max-tokens", type=int, default=8)
	ap.add_argument("--out-dir", default=f"/private/tmp/ds4_lane_a_session_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
	ap.add_argument("--mode", choices=["pp1", "pp3", "all"], default="all")
	ap.add_argument("--stage-manifest", default="")
	args = ap.parse_args(argv)
	session = PipelineSession(stages=load_stage_manifest(args.stage_manifest) if args.stage_manifest else None)
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
