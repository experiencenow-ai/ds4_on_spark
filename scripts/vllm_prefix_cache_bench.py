#!/usr/bin/env python3
"""Benchmark vLLM prefix-cache impact on a Centaur-shaped workload."""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FORMAT = "centaur-standard-runtime-model-benchmark-v1"
BENCHMARK_FORMAT = "ds4-vllm-prefix-cache-bench-v1"
DEFAULT_BENCHMARK_ID = "ds4-vllm-prefix-cache-centaur-workload-20260521"
DEFAULT_PROVIDER_ID = "standard-vllm-deepseek-v4-flash-prefix-cache"
BASELINE_NO_PREFIX_C512_TPS = 174.19031762627782


@dataclass(frozen=True)
class RequestResult:
	request_index: int
	prompt_chars: int
	prompt_tokens: int
	completion_tokens: int
	wall_s: float
	error: str
	text_preview: str


def utc_now() -> str:
	return(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def canonical_hash(obj: dict[str, Any]) -> str:
	payload = copy.deepcopy(obj)
	payload.pop("artifact_sha256", None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
	return(hashlib.sha256(data).hexdigest())


def centaur_system_prompt(target_words: int = 500) -> str:
	words = (
		"Centaur evaluates candidate state machines for internal release readiness. "
		"The operator needs deterministic evidence about chat routes, tool calls, "
		"provider choices, work lifecycle events, replay bundles, artifact hashes, "
		"debug snapshots, cost gates, model qualification, and release blockers. "
		"Answer with concrete operational language, preserve identifiers exactly, "
		"prefer measurable next steps, and treat missing evidence as a blocker. "
		"Do not invent live-provider success, do not hide optional-module warnings, "
		"and do not collapse mock readiness into release readiness. "
	).split()
	out: list[str] = []
	while len(out) < target_words:
		out.extend(words)
	return(" ".join(out[:target_words]))


def centaur_user_prompt(index: int, target_words: int = 50) -> str:
	seed = (
		f"Request {index}: compare a candidate workflow against the release gate, "
		"identify the most important blocker, name the artifact to inspect next, "
		"and recommend whether the UI operator should continue, pause, or rerun. "
	)
	words = seed.split()
	while len(words) < target_words:
		words.extend([
			"state-machine",
			str(index % 17),
			"provider",
			str(index % 5),
			"artifact",
			str(index % 23),
		])
	return(" ".join(words[:target_words]))


def build_prompt(index: int, system_words: int, user_words: int) -> str:
	return(
		"<|system|>\n"
		+ centaur_system_prompt(system_words)
		+ "\n<|user|>\n"
		+ centaur_user_prompt(index, user_words)
		+ "\n<|assistant|>\n"
	)


def fetch_text(url: str, timeout_s: float) -> tuple[str, str]:
	req = urllib.request.Request(url, method="GET")
	try:
		with urllib.request.urlopen(req, timeout=timeout_s) as resp:
			return(resp.read().decode("utf-8", "replace"), "")
	except (OSError, TimeoutError, urllib.error.URLError) as exc:
		return("", repr(exc))


def request_completion(endpoint: str, model: str, prompt: str, max_tokens: int, timeout_s: float) -> RequestResult:
	payload = {
		"model": model,
		"prompt": prompt,
		"max_tokens": max_tokens,
		"temperature": 0,
		"ignore_eos": True,
	}
	data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
	req = urllib.request.Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
	t0 = time.perf_counter()
	try:
		with urllib.request.urlopen(req, timeout=timeout_s) as resp:
			body = resp.read().decode("utf-8", "replace")
		wall = time.perf_counter() - t0
		obj = json.loads(body)
		usage = obj.get("usage") if isinstance(obj, dict) else None
		choices = obj.get("choices") if isinstance(obj, dict) else None
		text = ""
		if isinstance(choices, list) and choices and isinstance(choices[0], dict):
			text = str(choices[0].get("text", ""))
		return(RequestResult(
			request_index=-1,
			prompt_chars=len(prompt),
			prompt_tokens=int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0,
			completion_tokens=int(usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0,
			wall_s=wall,
			error="",
			text_preview=text.replace("\n", " ")[:160],
		))
	except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
		return(RequestResult(
			request_index=-1,
			prompt_chars=len(prompt),
			prompt_tokens=0,
			completion_tokens=0,
			wall_s=time.perf_counter() - t0,
			error=repr(exc),
			text_preview="",
		))


def run_one(args: argparse.Namespace, index: int) -> RequestResult:
	prompt = build_prompt(index, args.system_words, args.user_words)
	result = request_completion(args.endpoint, args.model, prompt, args.max_tokens, args.timeout_s)
	return(RequestResult(index, result.prompt_chars, result.prompt_tokens, result.completion_tokens, result.wall_s, result.error, result.text_preview))


def metric_value(line: str) -> tuple[str, float] | None:
	if line.startswith("#"):
		return(None)
	match = re.match(r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+([-+0-9.eE]+)$", line.strip())
	if match is None:
		return(None)
	try:
		return(match.group(1), float(match.group(2)))
	except ValueError:
		return(None)


def metric_sum(text: str, required_terms: tuple[str, ...], excluded_terms: tuple[str, ...] = ()) -> float:
	total = 0.0
	for line in text.splitlines():
		item = metric_value(line)
		if item is None:
			continue
		name, value = item
		low = name.lower()
		if all(term in low for term in required_terms) and not any(term in low for term in excluded_terms):
			total += value
	return(total)


def prefix_metric_snapshot(text: str) -> dict[str, float]:
	return({
		"prompt_tokens_total": metric_sum(text, ("prompt", "tokens", "total"), ("cached",)),
		"prompt_tokens_cached_total": metric_sum(text, ("prompt", "tokens", "cached")),
		"prefix_cache_hits_total": metric_sum(text, ("prefix", "cache", "hit")),
		"prefix_cache_queries_total": metric_sum(text, ("prefix", "cache"), ("hit",)),
	})


def delta_metrics(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
	return({key: max(0.0, after.get(key, 0.0) - before.get(key, 0.0)) for key in sorted(set(before) | set(after))})


def api_base_from_endpoint(endpoint: str) -> str:
	if endpoint.endswith("/v1/completions"):
		return(endpoint[: -len("/completions")])
	return(endpoint.rsplit("/", 1)[0])


def run_requests(args: argparse.Namespace) -> dict[str, Any]:
	metrics_url = args.metrics_url or api_base_from_endpoint(args.endpoint).rsplit("/", 1)[0] + "/metrics"
	before_text, before_error = fetch_text(metrics_url, args.metrics_timeout_s)
	before = prefix_metric_snapshot(before_text)
	started = utc_now()
	t0 = time.perf_counter()
	rows: list[RequestResult] = []
	with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
		futures = [ex.submit(run_one, args, i) for i in range(args.requests)]
		for fut in concurrent.futures.as_completed(futures):
			rows.append(fut.result())
	wall = time.perf_counter() - t0
	finished = utc_now()
	after_text, after_error = fetch_text(metrics_url, args.metrics_timeout_s)
	after = prefix_metric_snapshot(after_text)
	rows.sort(key=lambda row: row.request_index)
	errors = sum(1 for row in rows if row.error != "")
	completion_tokens = sum(row.completion_tokens for row in rows)
	prompt_tokens = sum(row.prompt_tokens for row in rows)
	metric_delta = delta_metrics(before, after)
	cached = metric_delta.get("prompt_tokens_cached_total", 0.0)
	total = metric_delta.get("prompt_tokens_total", 0.0) or float(prompt_tokens)
	hit_rate = (cached / total) if total > 0.0 else None
	return({
		"started_utc": started,
		"finished_utc": finished,
		"wall_s": wall,
		"aggregate_tps": (completion_tokens / wall) if wall > 0.0 else 0.0,
		"requests_per_second": (args.requests / wall) if wall > 0.0 else 0.0,
		"completion_tokens": completion_tokens,
		"prompt_tokens": prompt_tokens,
		"errors": errors,
		"metrics_url": metrics_url,
		"metrics_errors": [item for item in (before_error, after_error) if item != ""],
		"metrics_before": before,
		"metrics_after": after,
		"metrics_delta": metric_delta,
		"prefix_cache_hit_rate": hit_rate,
		"rows": [row.__dict__ for row in rows],
	})


def common_artifact(args: argparse.Namespace) -> dict[str, Any]:
	prompt_shape = f"centaur_shared_{args.system_words}_word_system_{args.user_words}_word_user_{args.requests}_requests_{args.max_tokens}_output"
	return({
		"format": FORMAT,
		"artifact_sha256": "",
		"benchmark_id": args.benchmark_id,
		"provider_id": args.provider_id,
		"model_id": args.model_id,
		"model_family": "deepseek_v4_flash",
		"runtime": "vllm",
		"runtime_version": args.runtime_version,
		"model_format": "safetensors",
		"quantization": "official FP8 checkpoint with fp8 KV cache and fp4 expert path",
		"hardware": {
			"fabric": "direct_200g_pair",
			"head_node": "spark4",
			"launcher_node": "spark3",
			"machine": "DGX Spark",
			"worker_node": "spark5",
		},
		"launch_command": args.launch_command,
		"api_endpoint": api_base_from_endpoint(args.endpoint),
		"context_length": 200000,
		"mtp_supported": True,
		"mtp_enabled": False,
		"speculative_config": {},
		"ngram_spec_enabled": False,
		"batch_size": args.requests,
		"prompt_shape": prompt_shape,
		"output_mode": "full_vocab",
		"tokens_per_second": None,
		"time_to_first_token_ms": None,
		"prompt_processing_tokens_per_second": None,
		"memory_used_gib": None,
		"parse_valid": False,
		"task_quality_score": None,
		"blocker_kind": "endpoint_unavailable",
		"blocker_detail": "",
		"created_utc": args.created_utc or utc_now(),
		"prefix_cache_benchmark": {
			"format": BENCHMARK_FORMAT,
			"cache_mode": args.cache_mode,
			"requests": args.requests,
			"concurrency": args.concurrency,
			"system_words": args.system_words,
			"user_words": args.user_words,
			"max_tokens": args.max_tokens,
			"baseline_no_prefix_c512_tps": BASELINE_NO_PREFIX_C512_TPS,
			"cold_cache_policy": "single pass only; no measurement rerun after warmup",
		},
	})


def blocked_artifact(args: argparse.Namespace) -> dict[str, Any]:
	obj = common_artifact(args)
	obj["benchmark_status"] = "blocked"
	obj["blocker_kind"] = args.blocker_kind
	obj["blocker_detail"] = args.blocker_detail
	obj["startup_observations"] = {
		"spark3_ssh": args.spark3_ssh,
		"spark4_ssh": args.spark4_ssh,
		"spark5_ssh": args.spark5_ssh,
		"models_endpoint": args.models_endpoint,
		"rescue_endpoint": args.rescue_endpoint,
	}
	obj["raw_runtime_evidence"] = args.raw_evidence
	obj["artifact_sha256"] = canonical_hash(obj)
	return(obj)


def measured_artifact(args: argparse.Namespace) -> dict[str, Any]:
	run = run_requests(args)
	obj = common_artifact(args)
	if int(run["errors"]) != 0:
		args.blocker_kind = "endpoint_unavailable"
		args.blocker_detail = f"{run['errors']} request(s) failed during prefix-cache benchmark"
		args.raw_evidence = [row["error"] for row in run["rows"] if row["error"] != ""][:10]
		return(blocked_artifact(args))
	hit_rate = run.get("prefix_cache_hit_rate")
	obj.update({
		"benchmark_status": "passed",
		"tokens_per_second": float(run["aggregate_tps"]),
		"time_to_first_token_ms": 0.0,
		"time_to_first_token_source": "not separately measured by concurrent non-streaming completions pass",
		"prompt_processing_tokens_per_second": 0.0,
		"prompt_processing_tokens_per_second_source": "not separately measured by concurrent non-streaming completions pass",
		"memory_used_gib": args.memory_used_gib,
		"parse_valid": True,
		"blocker_kind": "none",
		"blocker_detail": "",
		"prefix_cache_benchmark": {
			**obj["prefix_cache_benchmark"],
			"run": run,
			"cache_hit_rate_percent": (hit_rate * 100.0) if isinstance(hit_rate, float) else None,
		},
		"topline_result": {
			"aggregate_tps": float(run["aggregate_tps"]),
			"completion_tokens": int(run["completion_tokens"]),
			"prompt_tokens": int(run["prompt_tokens"]),
			"prefix_cache_hit_rate": hit_rate,
		},
	})
	obj["artifact_sha256"] = canonical_hash(obj)
	return(obj)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--output", required=True)
	p.add_argument("--endpoint", default="http://10.20.0.14:8000/v1/completions")
	p.add_argument("--metrics-url", default="")
	p.add_argument("--model", default="deepseek-v4-flash")
	p.add_argument("--cache-mode", choices=("enabled", "disabled"), default="enabled")
	p.add_argument("--requests", type=int, default=100)
	p.add_argument("--concurrency", type=int, default=100)
	p.add_argument("--system-words", type=int, default=500)
	p.add_argument("--user-words", type=int, default=50)
	p.add_argument("--max-tokens", type=int, default=256)
	p.add_argument("--timeout-s", type=float, default=7200.0)
	p.add_argument("--metrics-timeout-s", type=float, default=30.0)
	p.add_argument("--blocked", action="store_true")
	p.add_argument("--blocker-kind", default="endpoint_unavailable")
	p.add_argument("--blocker-detail", default="")
	p.add_argument("--raw-evidence", action="append", default=[])
	p.add_argument("--spark3-ssh", default="")
	p.add_argument("--spark4-ssh", default="")
	p.add_argument("--spark5-ssh", default="")
	p.add_argument("--models-endpoint", default="")
	p.add_argument("--rescue-endpoint", default="")
	p.add_argument("--created-utc", default="")
	p.add_argument("--benchmark-id", default=DEFAULT_BENCHMARK_ID)
	p.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
	p.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	p.add_argument("--runtime-version", default="0.1.dev16581+gdda4668b5.d20260521")
	p.add_argument("--launch-command", default="DS4_WORKER_DOCKER_ARG_REWRITE_FROM=/home/spark4/models/hf/deepseek-ai/DeepSeek-V4-Flash DS4_WORKER_DOCKER_ARG_REWRITE_TO=/home/spark5/models/hf/deepseek-ai/DeepSeek-V4-Flash DS4_WORKER_ETH_IF=enp1s0f1np1 DS4_WORKER_IB_IF=rocep1s0f1 VLLM_SPARK_EXTRA_DOCKER_ARGS='-v /home/spark4/models/hf/deepseek-ai/DeepSeek-V4-Flash:/models/deepseek-v4-flash:ro' ./run-recipe.sh recipes/deepseek-v4-flash-local-batch512-no-mtp.yaml --no-ray --no-cache-dirs -d")
	p.add_argument("--memory-used-gib", type=float, default=74.05)
	args = p.parse_args(argv)
	if args.requests <= 0 or args.concurrency <= 0:
		raise SystemExit("--requests and --concurrency must be positive")
	return(args)


def run(args: argparse.Namespace) -> dict[str, Any]:
	if args.blocked:
		if args.blocker_detail == "":
			raise SystemExit("--blocked requires --blocker-detail")
		obj = blocked_artifact(args)
	else:
		obj = measured_artifact(args)
	path = Path(args.output)
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		json.dump(obj, f, indent=2, sort_keys=True)
		f.write("\n")
	return(obj)


def main() -> int:
	args = parse_args()
	obj = run(args)
	print(json.dumps({
		"output": args.output,
		"benchmark_status": obj.get("benchmark_status"),
		"tokens_per_second": obj.get("tokens_per_second"),
		"blocker_kind": obj.get("blocker_kind"),
	}, indent=2, sort_keys=True))
	return(0)


if __name__ == "__main__":
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
	raise SystemExit(main())
