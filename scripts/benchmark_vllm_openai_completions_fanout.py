#!/usr/bin/env python3
"""Benchmark vLLM OpenAI completions fanout with mixed prompt shapes."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


FORMAT = "ds4-vllm-openai-completions-fanout-v1"


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


def mixed_prompt(index: int, round_index: int) -> str:
	stem = PROMPT_STEMS[index % len(PROMPT_STEMS)]
	detail_count = 1 + ((index + round_index) % 5)
	detail_start = (index * 3 + round_index) % len(DETAILS)
	detail = " ".join(DETAILS[(detail_start + i) % len(DETAILS)] for i in range(detail_count))
	padding = " ".join(f"case_{index}_{round_index}_{i}" for i in range((index % 7) * 3))
	return(f"{stem} {detail} {padding}".strip())


def request_completion(endpoint: str, model: str, prompt: str, max_tokens: int, timeout_s: float) -> tuple[dict[str, Any], float, str]:
	payload = {
		"model": model,
		"prompt": prompt,
		"max_tokens": max_tokens,
		"temperature": 0,
	}
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


def run_one(endpoint: str, model: str, concurrency: int, round_index: int, request_index: int, max_tokens: int, timeout_s: float) -> RequestResult:
	prompt = mixed_prompt(request_index, round_index)
	obj, wall, error = request_completion(endpoint, model, prompt, max_tokens, timeout_s)
	usage = obj.get("usage") if isinstance(obj, dict) else None
	prompt_tokens = int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0
	completion_tokens = int(usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0
	text = ""
	choices = obj.get("choices") if isinstance(obj, dict) else None
	if isinstance(choices, list) and len(choices) > 0 and isinstance(choices[0], dict):
		text = str(choices[0].get("text", ""))
	return(RequestResult(concurrency, round_index, request_index, len(prompt), prompt_tokens, completion_tokens, wall, error, text.replace("\n", " ")[:160]))


def run_round(endpoint: str, model: str, concurrency: int, round_index: int, max_tokens: int, timeout_s: float) -> dict[str, Any]:
	t0 = time.perf_counter()
	rows: list[RequestResult] = []
	with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
		futures = [
			ex.submit(run_one, endpoint, model, concurrency, round_index, i, max_tokens, timeout_s)
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


def summarize(concurrency: int, rounds: list[dict[str, Any]]) -> dict[str, Any]:
	ok = [r for r in rounds if int(r.get("errors", 0)) == 0]
	aggs = [float(r["aggregate_tps"]) for r in ok]
	rps = [float(r["requests_per_second"]) for r in ok]
	return({
		"concurrency": concurrency,
		"rounds": len(rounds),
		"successful_rounds": len(ok),
		"total_errors": sum(int(r.get("errors", 0)) for r in rounds),
		"mean_aggregate_tps": mean(aggs),
		"median_aggregate_tps": median(aggs),
		"max_aggregate_tps": max(aggs) if aggs else 0.0,
		"min_aggregate_tps": min(aggs) if aggs else 0.0,
		"mean_per_stream_tps": (mean(aggs) / concurrency) if concurrency > 0 else 0.0,
		"mean_requests_per_second": mean(rps),
		"total_completion_tokens": sum(int(r.get("completion_tokens", 0)) for r in rounds),
		"total_prompt_tokens": sum(int(r.get("prompt_tokens", 0)) for r in rounds),
	})


def build_artifact(args: argparse.Namespace) -> dict[str, Any]:
	levels = parse_ints(args.concurrency)
	round_overrides = parse_rounds(args.rounds) if args.rounds else {}
	round_records: list[dict[str, Any]] = []
	summaries: list[dict[str, Any]] = []
	for concurrency in levels:
		count = round_overrides.get(concurrency, args.default_rounds)
		current: list[dict[str, Any]] = []
		for round_index in range(count):
			rec = run_round(args.endpoint, args.model, concurrency, round_index, args.max_tokens, args.timeout_s)
			current.append(rec)
			round_records.append(rec)
			print(json.dumps({k: rec[k] for k in ("concurrency", "round_index", "aggregate_tps", "prompt_tokens", "completion_tokens", "errors")}, sort_keys=True), flush=True)
		summaries.append(summarize(concurrency, current))
	return({
		"format": FORMAT,
		"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
		"endpoint": args.endpoint,
		"model": args.model,
		"prompt_mode": "distinct_mixed_length_no_prefix_cache_hit",
		"max_tokens": args.max_tokens,
		"concurrency_levels": levels,
		"rounds": round_records,
		"summaries": summaries,
		"best_summary": max(summaries, key=lambda r: float(r["mean_aggregate_tps"])) if summaries else {},
		"notes": args.note,
	})


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/completions")
	p.add_argument("--model", default="deepseek-v4-flash")
	p.add_argument("--concurrency", default="1 2 4 8 16 32 64 128 256 512")
	p.add_argument("--rounds", default="")
	p.add_argument("--default-rounds", type=int, default=1)
	p.add_argument("--max-tokens", type=int, default=32)
	p.add_argument("--timeout-s", type=float, default=900.0)
	p.add_argument("--output", required=True)
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
