#!/usr/bin/env python3
"""Benchmark K-slot pipeline row replacement against serial PP=1 runs."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from scripts.pipeline_batch_scheduler import (
	BatchRunSummary,
	PipelineBatchScheduler,
	PipelineBatchSchedulerError,
	PromptRequest,
	load_requests,
	write_summary,
)


DEFAULT_REQUESTS = (
	PromptRequest("math_short", "what is 2+2?", 5),
	PromptRequest("capital_short", "Name the capital of France.", 8),
	PromptRequest("code_tiny", "Write a Python expression for 7 squared.", 13),
	PromptRequest("reason_steps", "Explain why batching helps throughput in two sentences.", 21),
	PromptRequest("memory_prompt", "List three facts about KV cache reuse.", 34),
	PromptRequest("routing_prompt", "Draft a concise model-routing decision for a cheap extractor.", 55),
	PromptRequest("longer_prompt", "Summarize the tradeoff between latency and throughput for local LLM serving.", 80),
	PromptRequest("checksum_prompt", "Return a short note about deterministic token checks.", 7),
)


@dataclass(frozen=True)
class SerialGeneration:
	request_id: str
	token_ids: tuple[int, ...]
	tok_s: float
	wall_seconds: float


def _load_requests(path: str | None) -> list[PromptRequest]:
	if path is None:
		return list(DEFAULT_REQUESTS)
	return load_requests(Path(path))


def _module(name: str) -> Any:
	return __import__(name, fromlist=["make_pipeline_batch_backend", "run_serial_pp1_baseline"])


def _parse_serial_generation(item: Any) -> SerialGeneration:
	if isinstance(item, SerialGeneration):
		return item
	if not isinstance(item, dict):
		raise PipelineBatchSchedulerError("serial generation item must be an object")
	request_id = str(item.get("request_id", ""))
	token_ids_raw = item.get("token_ids")
	if not request_id:
		raise PipelineBatchSchedulerError("serial generation missing request_id")
	if not isinstance(token_ids_raw, list) or not all(isinstance(x, int) for x in token_ids_raw):
		raise PipelineBatchSchedulerError(f"{request_id}: serial token_ids must be a list of integers")
	wall = float(item.get("wall_seconds", 0.0))
	tok_s = float(item.get("tok_s", 0.0))
	if tok_s <= 0.0 and wall > 0.0:
		tok_s = float(len(token_ids_raw)) / wall
	if tok_s <= 0.0:
		raise PipelineBatchSchedulerError(f"{request_id}: serial tok_s must be positive")
	return SerialGeneration(request_id, tuple(int(x) for x in token_ids_raw), tok_s, wall)


def _run_serial(module: Any, args: argparse.Namespace, requests: Sequence[PromptRequest]) -> tuple[SerialGeneration, ...]:
	if hasattr(module, "run_serial_pp1_baseline"):
		raw = module.run_serial_pp1_baseline(args=args, requests=tuple(requests))
	else:
		raw = _run_lane_a_serial(module, args, requests)
	if not isinstance(raw, Sequence):
		raise PipelineBatchSchedulerError("run_serial_pp1_baseline must return a sequence")
	results = tuple(_parse_serial_generation(item) for item in raw)
	request_ids = {r.request_id for r in requests}
	seen = {r.request_id for r in results}
	if seen != request_ids:
		raise PipelineBatchSchedulerError(f"serial request id mismatch: expected={sorted(request_ids)} got={sorted(seen)}")
	return results


def _run_lane_a_serial(module: Any, args: argparse.Namespace, requests: Sequence[PromptRequest]) -> tuple[SerialGeneration, ...]:
	session_cls = getattr(module, "PipelineSession", None)
	if session_cls is None:
		raise PipelineBatchSchedulerError("backend module must expose run_serial_pp1_baseline or PipelineSession")
	session = session_cls()
	if not hasattr(session, "run_pp1_baseline"):
		raise PipelineBatchSchedulerError("PipelineSession must expose run_pp1_baseline for serial PP=1")
	out_root = Path(args.out_dir) / "serial_pp1"
	results: list[SerialGeneration] = []
	for request in requests:
		t0 = time.perf_counter()
		run = session.run_pp1_baseline(request.prompt, request.max_tokens, out_root / request.request_id)
		wall = max(time.perf_counter() - t0, 0.0)
		token_ids = tuple(int(x) for x in getattr(run, "generated_token_ids"))
		tok_s = (float(len(token_ids)) / wall) if wall > 0.0 else 0.0
		results.append(SerialGeneration(request.request_id, token_ids, tok_s, wall))
	return tuple(results)


def _make_batch_backend(module: Any, args: argparse.Namespace) -> Any:
	if hasattr(module, "make_pipeline_batch_backend"):
		return module.make_pipeline_batch_backend(args=args)
	session_cls = getattr(module, "PipelineSession", None)
	if session_cls is None:
		raise PipelineBatchSchedulerError("backend module must expose make_pipeline_batch_backend or PipelineSession")
	session = session_cls()
	missing = [
		name
		for name in ("prefill_row", "decode_batch", "reset_row")
		if not hasattr(session, name)
	]
	if missing:
		raise PipelineBatchSchedulerError(
			"PipelineSession is missing batch row-replacement methods: "
			+ ",".join(missing)
			+ "; expected prefill_row/decode_batch/reset_row for Lane C"
		)
	return session


def _verify_matches(batch: BatchRunSummary, serial: Sequence[SerialGeneration]) -> list[str]:
	errors: list[str] = []
	serial_by_id = {r.request_id: r for r in serial}
	for result in batch.results:
		expected = serial_by_id.get(result.request_id)
		if expected is None:
			errors.append(f"{result.request_id}: missing serial baseline")
		elif result.token_ids != expected.token_ids:
			errors.append(f"{result.request_id}: token mismatch batch={list(result.token_ids)} serial={list(expected.token_ids)}")
	return errors


def _bench_summary(
	args: argparse.Namespace,
	requests: Sequence[PromptRequest],
	serial: Sequence[SerialGeneration],
	batch: BatchRunSummary,
	match_errors: Sequence[str],
) -> dict[str, Any]:
	serial_sum_tok_s = sum(r.tok_s for r in serial)
	speedup = (batch.aggregate_tok_s / serial_sum_tok_s) if serial_sum_tok_s > 0.0 else 0.0
	return {
		"k": int(args.k),
		"request_count": len(requests),
		"serial_sum_tok_s": serial_sum_tok_s,
		"batch_aggregate_tok_s": batch.aggregate_tok_s,
		"speedup_vs_sum_serial": speedup,
		"min_speedup": float(args.min_speedup),
		"token_id_match": len(match_errors) == 0,
		"match_errors": list(match_errors),
		"scheduler_events_path": batch.events_path,
		"serial": [
			{
				"request_id": r.request_id,
				"token_ids": list(r.token_ids),
				"tok_s": r.tok_s,
				"wall_seconds": r.wall_seconds,
			}
			for r in serial
		],
		"batch": batch.to_jsonable(),
	}


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
	ap = argparse.ArgumentParser(description="Compare DS4 K-slot pipeline throughput against serial PP=1.")
	ap.add_argument("--requests", help="Optional JSON request list. Defaults to 8 varied prompts.")
	ap.add_argument("--out-dir", required=True)
	ap.add_argument("--k", type=int, default=8)
	ap.add_argument("--backend-module", required=True, help="Module with run_serial_pp1_baseline and make_pipeline_batch_backend.")
	ap.add_argument("--min-speedup", type=float, default=2.0)
	return ap


def main(argv: Iterable[str] | None = None) -> int:
	try:
		args = build_parser().parse_args(list(argv) if argv is not None else None)
		out_dir = Path(args.out_dir)
		requests = _load_requests(args.requests)
		module = _module(args.backend_module)
		serial = _run_serial(module, args, requests)
		backend = _make_batch_backend(module, args)
		events_path = out_dir / "scheduler_events.jsonl"
		batch = PipelineBatchScheduler(backend, int(args.k)).run(requests, events_path)
		write_summary(out_dir / "batch_scheduler_summary.json", batch)
		match_errors = _verify_matches(batch, serial)
		summary = _bench_summary(args, requests, serial, batch, match_errors)
		write_json(out_dir / "bench_pipeline_batch_vs_serial.json", summary)
		print(json.dumps(summary, indent=2, sort_keys=True))
		if match_errors:
			return 2
		if float(summary["speedup_vs_sum_serial"]) < float(args.min_speedup):
			return 3
		return 0
	except (OSError, json.JSONDecodeError, PipelineBatchSchedulerError, NotImplementedError, RuntimeError) as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1


if __name__ == "__main__":
	raise SystemExit(main())
