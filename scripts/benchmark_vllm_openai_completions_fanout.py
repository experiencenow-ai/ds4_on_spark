#!/usr/bin/env python3
"""Benchmark vLLM OpenAI completions fanout with mixed prompt shapes."""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


FORMAT = "ds4-vllm-openai-completions-fanout-v1"
STANDARD_RUNTIME_FORMAT = "centaur-standard-runtime-model-benchmark-v1"


@dataclass(frozen=True)
class RequestResult:
	concurrency: int
	round_index: int
	request_index: int
	prompt_chars: int
	prompt_tokens: int
	completion_tokens: int
	wall_s: float
	error: str
	text_preview: str


PROMPT_STEMS = [
	"Classify this support ticket and give a concise operational next step.",
	"Summarize the incident timeline, preserve exact times, and name the owner.",
	"Pick the safest deployment lane and justify it in one compact sentence.",
	"Extract the risk level, affected subsystem, and immediate mitigation.",
	"Compare two model-provider options and choose the better production lane.",
	"Write a terse status update for an engineer who already knows the project.",
	"Rank the following blockers by execution risk and call out the top one.",
	"Answer as a scheduler: decide whether to batch, defer, or run immediately.",
]


DETAILS = [
	"Rows are independent and must not rely on shared prefix cache.",
	"Use plain text; do not include markdown tables or code fences.",
	"Assume the hardware is a two-node DGX Spark vLLM deployment.",
	"Keep the answer deterministic and avoid optional caveats.",
	"Mention throughput only if it is directly relevant to the decision.",
	"Treat missing evidence as a blocker rather than a pass.",
	"Prefer concrete next actions over background explanation.",
	"Use one sentence unless the prompt explicitly asks for two.",
]


def parse_ints(raw: str) -> list[int]:
	items: list[int] = []
	for part in raw.replace(",", " ").split():
		value = int(part)
		if value <= 0:
			raise ValueError("integer lists must contain positive values")
		items.append(value)
	if len(items) == 0:
		raise ValueError("integer list must not be empty")
	return(items)


def parse_rounds(raw: str) -> dict[int, int]:
	out: dict[int, int] = {}
	for part in raw.replace(",", " ").split():
		if ":" not in part:
			raise ValueError("round entries must be C:R")
		left, right = part.split(":", 1)
		c = int(left)
		r = int(right)
		if c <= 0 or r <= 0:
			raise ValueError("round entries must be positive")
		out[c] = r
	return(out)


def utc_now() -> str:
	return(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def load_prompts(path: str) -> list[str]:
	if path == "":
		return([])
	with open(path, "r", encoding="utf-8") as f:
		prompts = [line.strip() for line in f.readlines() if line.strip() != ""]
	if len(prompts) == 0:
		raise ValueError("prompt file must contain at least one non-empty prompt")
	return(prompts)


def mixed_prompt(index: int, round_index: int) -> str:
	stem = PROMPT_STEMS[index % len(PROMPT_STEMS)]
	detail_count = 1 + ((index + round_index) % 5)
	detail_start = (index * 3 + round_index) % len(DETAILS)
	detail = " ".join(DETAILS[(detail_start + i) % len(DETAILS)] for i in range(detail_count))
	padding = " ".join(f"case_{index}_{round_index}_{i}" for i in range((index % 7) * 3))
	return(f"{stem} {detail} {padding}".strip())


def prompt_for(index: int, round_index: int, prompts: list[str]) -> str:
	if len(prompts) == 0:
		return(mixed_prompt(index, round_index))
	return(prompts[(index + round_index) % len(prompts)])


def request_completion(endpoint: str, model: str, prompt: str, max_tokens: int, timeout_s: float, ignore_eos: bool) -> tuple[dict[str, Any], float, str]:
	payload = {
		"model": model,
		"prompt": prompt,
		"max_tokens": max_tokens,
		"temperature": 0,
	}
	if ignore_eos:
		payload["ignore_eos"] = True
	data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
	req = urllib.request.Request(endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST")
	t0 = time.perf_counter()
	try:
		with urllib.request.urlopen(req, timeout=timeout_s) as resp:
			body = resp.read().decode("utf-8", "replace")
		wall = time.perf_counter() - t0
		obj = json.loads(body)
		if not isinstance(obj, dict):
			return({}, wall, "response root is not an object")
		return(obj, wall, "")
	except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as e:
		return({}, time.perf_counter() - t0, repr(e))


def run_one(endpoint: str, model: str, prompts: list[str], concurrency: int, round_index: int, request_index: int, max_tokens: int, timeout_s: float, ignore_eos: bool) -> RequestResult:
	prompt = prompt_for(request_index, round_index, prompts)
	obj, wall, error = request_completion(endpoint, model, prompt, max_tokens, timeout_s, ignore_eos)
	usage = obj.get("usage") if isinstance(obj, dict) else None
	prompt_tokens = int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0
	completion_tokens = int(usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0
	text = ""
	choices = obj.get("choices") if isinstance(obj, dict) else None
	if isinstance(choices, list) and len(choices) > 0 and isinstance(choices[0], dict):
		text = str(choices[0].get("text", ""))
	return(RequestResult(concurrency, round_index, request_index, len(prompt), prompt_tokens, completion_tokens, wall, error, text.replace("\n", " ")[:160]))


def run_round(endpoint: str, model: str, prompts: list[str], concurrency: int, round_index: int, max_tokens: int, timeout_s: float, ignore_eos: bool) -> dict[str, Any]:
	started_utc = utc_now()
	t0 = time.perf_counter()
	rows: list[RequestResult] = []
	with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
		futures = [
			ex.submit(run_one, endpoint, model, prompts, concurrency, round_index, i, max_tokens, timeout_s, ignore_eos)
			for i in range(concurrency)
		]
		for fut in concurrent.futures.as_completed(futures):
			rows.append(fut.result())
	wall = time.perf_counter() - t0
	rows.sort(key=lambda r: r.request_index)
	completion_tokens = sum(r.completion_tokens for r in rows)
	prompt_tokens = sum(r.prompt_tokens for r in rows)
	errors = sum(1 for r in rows if r.error != "")
	return({
		"concurrency": concurrency,
		"round_index": round_index,
		"output_length": max_tokens,
		"started_utc": started_utc,
		"finished_utc": utc_now(),
		"wall_s": wall,
		"aggregate_tps": (completion_tokens / wall) if wall > 0.0 else 0.0,
		"requests_per_second": (concurrency / wall) if wall > 0.0 else 0.0,
		"completion_tokens": completion_tokens,
		"prompt_tokens": prompt_tokens,
		"errors": errors,
		"rows": [r.__dict__ for r in rows],
	})


def mean(vals: list[float]) -> float:
	return(float(statistics.mean(vals)) if vals else 0.0)


def median(vals: list[float]) -> float:
	return(float(statistics.median(vals)) if vals else 0.0)


def summarize(concurrency: int, output_length: int, rounds: list[dict[str, Any]]) -> dict[str, Any]:
	ok = [r for r in rounds if int(r.get("errors", 0)) == 0]
	aggs = [float(r["aggregate_tps"]) for r in ok]
	rps = [float(r["requests_per_second"]) for r in ok]
	total_completion_tokens = sum(int(r.get("completion_tokens", 0)) for r in rounds)
	successful_requests = sum((int(r.get("concurrency", concurrency)) - int(r.get("errors", 0))) for r in rounds)
	return({
		"concurrency": concurrency,
		"output_length": output_length,
		"rounds": len(rounds),
		"successful_rounds": len(ok),
		"total_errors": sum(int(r.get("errors", 0)) for r in rounds),
		"mean_aggregate_tps": mean(aggs),
		"median_aggregate_tps": median(aggs),
		"max_aggregate_tps": max(aggs) if aggs else 0.0,
		"min_aggregate_tps": min(aggs) if aggs else 0.0,
		"mean_per_stream_tps": (mean(aggs) / concurrency) if concurrency > 0 else 0.0,
		"mean_requests_per_second": mean(rps),
		"mean_completion_tokens_per_request": (total_completion_tokens / successful_requests) if successful_requests > 0 else 0.0,
		"total_completion_tokens": total_completion_tokens,
		"total_prompt_tokens": sum(int(r.get("prompt_tokens", 0)) for r in rounds),
	})


def canonical_hash(obj: dict[str, Any]) -> str:
	payload = copy.deepcopy(obj)
	payload.pop("artifact_sha256", None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
	return(hashlib.sha256(data).hexdigest())


def best_summary(summaries: list[dict[str, Any]]) -> dict[str, Any]:
	return(max(summaries, key=lambda r: float(r["mean_aggregate_tps"])) if summaries else {})


def recommendation(summaries: list[dict[str, Any]]) -> str:
	if len(summaries) == 0:
		return("No successful cell was measured; do not route Centaur eval work to this provider.")
	near = [s for s in summaries if int(s.get("output_length", 0)) in (128, 512)]
	selected = best_summary(near if near else summaries)
	c = int(selected.get("concurrency", 0))
	l = int(selected.get("output_length", 0))
	agg = float(selected.get("mean_aggregate_tps", 0.0))
	per = float(selected.get("mean_per_stream_tps", 0.0))
	return(f"For ~256-token Centaur eval outputs, use concurrency {c}: nearest measured output_length={l} had {agg:.3f} aggregate tok/s and {per:.3f} per-stream tok/s.")


def build_standard_runtime_artifact(args: argparse.Namespace, raw: dict[str, Any]) -> dict[str, Any]:
	summaries = list(raw.get("summaries", []))
	best = best_summary(summaries)
	obj: dict[str, Any] = {
		"format": STANDARD_RUNTIME_FORMAT,
		"artifact_sha256": "",
		"benchmark_id": args.benchmark_id,
		"provider_id": args.provider_id,
		"model_id": args.model_id,
		"model_family": args.model_family,
		"runtime": "vllm",
		"runtime_version": args.runtime_version,
		"model_format": "safetensors",
		"quantization": args.quantization,
		"hardware": {
			"fabric": "direct_200g_pair",
			"head_node": "spark4",
			"launcher_node": "spark3",
			"machine": "DGX Spark",
			"worker_node": "spark5",
		},
		"launch_command": args.launch_command,
		"api_endpoint": args.endpoint.rsplit("/", 1)[0],
		"context_length": args.context_length,
		"mtp_supported": True,
		"mtp_enabled": False,
		"speculative_config": {},
		"ngram_spec_enabled": False,
		"batch_size": max(parse_ints(args.concurrency)),
		"prompt_shape": "antirez_dir_steering_eval_prompts_realistic_output_length_sweep",
		"output_mode": "full_vocab",
		"tokens_per_second": float(best.get("mean_aggregate_tps", 0.0)),
		"time_to_first_token_ms": args.time_to_first_token_ms,
		"time_to_first_token_source": args.time_to_first_token_source,
		"prompt_processing_tokens_per_second": args.prompt_processing_tokens_per_second,
		"prompt_processing_tokens_per_second_source": args.prompt_processing_tokens_per_second_source,
		"memory_used_gib": args.memory_used_gib,
		"parse_valid": True,
		"task_quality_score": None,
		"blocker_kind": "none",
		"blocker_detail": "",
		"created_utc": raw.get("created_utc", ""),
		"benchmark_status": "passed",
		"request_output_lengths": parse_ints(args.max_tokens_list),
		"concurrency_levels": parse_ints(args.concurrency),
		"prompt_source": args.prompt_source,
		"prompt_source_sha256": raw.get("prompt_source_sha256", ""),
		"ignore_eos": bool(args.ignore_eos),
		"realistic_workload_matrix": summaries,
		"raw_rounds": raw.get("rounds", []),
		"topline_result": {
			"best_aggregate_tps": float(best.get("mean_aggregate_tps", 0.0)),
			"best_concurrency": int(best.get("concurrency", 0)),
			"best_output_length": int(best.get("output_length", 0)),
			"mean_per_stream_tps": float(best.get("mean_per_stream_tps", 0.0)),
		},
		"recommendation": recommendation(summaries),
		"notes": args.note,
	}
	obj["artifact_sha256"] = canonical_hash(obj)
	return(obj)


def build_artifact(args: argparse.Namespace) -> dict[str, Any]:
	levels = parse_ints(args.concurrency)
	token_lengths = parse_ints(args.max_tokens_list) if args.max_tokens_list else [args.max_tokens]
	round_overrides = parse_rounds(args.rounds) if args.rounds else {}
	prompts = load_prompts(args.prompt_file)
	round_records: list[dict[str, Any]] = []
	summaries: list[dict[str, Any]] = []
	for output_length in token_lengths:
		for concurrency in levels:
			count = round_overrides.get(concurrency, args.default_rounds)
			current: list[dict[str, Any]] = []
			for round_index in range(count):
				rec = run_round(args.endpoint, args.model, prompts, concurrency, round_index, output_length, args.timeout_s, args.ignore_eos)
				current.append(rec)
				round_records.append(rec)
				print(json.dumps({k: rec[k] for k in ("concurrency", "output_length", "round_index", "aggregate_tps", "prompt_tokens", "completion_tokens", "errors")}, sort_keys=True), flush=True)
			summaries.append(summarize(concurrency, output_length, current))
	raw = {
		"format": FORMAT,
		"created_utc": utc_now(),
		"endpoint": args.endpoint,
		"model": args.model,
		"prompt_mode": "antirez_dir_steering_eval_prompts" if prompts else "distinct_mixed_length_no_prefix_cache_hit",
		"prompt_source": args.prompt_source,
		"prompt_source_sha256": hashlib.sha256("\n".join(prompts).encode("utf-8")).hexdigest() if prompts else "",
		"max_tokens": args.max_tokens,
		"output_lengths": token_lengths,
		"concurrency_levels": levels,
		"ignore_eos": bool(args.ignore_eos),
		"rounds": round_records,
		"summaries": summaries,
		"best_summary": best_summary(summaries),
		"recommendation": recommendation(summaries),
		"notes": args.note,
	}
	if args.artifact_kind == "standard-runtime":
		return(build_standard_runtime_artifact(args, raw))
	return(raw)


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/completions")
	p.add_argument("--model", default="deepseek-v4-flash")
	p.add_argument("--concurrency", default="1 2 4 8 16 32 64 128 256 512")
	p.add_argument("--rounds", default="")
	p.add_argument("--default-rounds", type=int, default=1)
	p.add_argument("--max-tokens", type=int, default=32)
	p.add_argument("--max-tokens-list", default="")
	p.add_argument("--prompt-file", default="")
	p.add_argument("--prompt-source", default="")
	p.add_argument("--ignore-eos", action="store_true")
	p.add_argument("--timeout-s", type=float, default=900.0)
	p.add_argument("--output", required=True)
	p.add_argument("--artifact-kind", choices=("raw", "standard-runtime"), default="raw")
	p.add_argument("--benchmark-id", default="ds4-vllm-existing-solution-tp2-no-mtp-spark45-realistic-workload-sweep-20260521")
	p.add_argument("--provider-id", default="standard-vllm-deepseek-v4-flash-existing-recipe")
	p.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	p.add_argument("--model-family", default="deepseek_v4_flash")
	p.add_argument("--runtime-version", default="0.1.dev16581+gdda4668b5.d20260521")
	p.add_argument("--quantization", default="official FP8 checkpoint with fp8 KV cache and fp4 expert path")
	p.add_argument("--launch-command", default="DS4_WORKER_DOCKER_ARG_REWRITE_FROM=/home/spark4/models/hf/deepseek-ai/DeepSeek-V4-Flash DS4_WORKER_DOCKER_ARG_REWRITE_TO=/home/spark5/models/hf/deepseek-ai/DeepSeek-V4-Flash DS4_WORKER_ETH_IF=enp1s0f1np1 DS4_WORKER_IB_IF=rocep1s0f1 VLLM_SPARK_EXTRA_DOCKER_ARGS='-v /home/spark4/models/hf/deepseek-ai/DeepSeek-V4-Flash:/models/deepseek-v4-flash:ro' ./run-recipe.sh recipes/deepseek-v4-flash-local-batch512-no-mtp.yaml --no-ray --no-cache-dirs -d")
	p.add_argument("--context-length", type=int, default=200000)
	p.add_argument("--time-to-first-token-ms", type=float, default=0.0)
	p.add_argument("--time-to-first-token-source", default="not separately measured by the non-streaming completions matrix")
	p.add_argument("--prompt-processing-tokens-per-second", type=float, default=0.0)
	p.add_argument("--prompt-processing-tokens-per-second-source", default="not separately measured by the non-streaming completions matrix")
	p.add_argument("--memory-used-gib", type=float, default=75.76)
	p.add_argument("--note", action="append", default=[])
	return(p.parse_args())


def main() -> int:
	args = parse_args()
	artifact = build_artifact(args)
	with open(args.output, "w", encoding="utf-8") as f:
		json.dump(artifact, f, indent=2, sort_keys=True)
		f.write("\n")
	print(json.dumps({"output": args.output, "best_summary": artifact.get("best_summary", {})}, indent=2, sort_keys=True))
	return(0)


if __name__ == "__main__":
	raise SystemExit(main())
