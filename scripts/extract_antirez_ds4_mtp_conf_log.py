#!/usr/bin/env python3
"""Extract and summarize MTP acceptance events from antirez/ds4 stderr/stdout logs.

This targets the CUDA MTP logs emitted by antirez/ds4 when `DS4_MTP_CONF_LOG=1`
and (optionally) `DS4_MTP_TIMING=1` are enabled.

We intentionally keep parsing simple and robust:
- `ds4: mtp conf ...` lines become "conf" events.
- `ds4: mtp spec miss first ...` lines become "miss_first" events.
- `ds4: prefill: ... t/s, generation: ... t/s` extracts throughput.
- `ds4: CUDA startup model cache prepared ...` extracts cache timing (when present).

The acceptance estimate used by this extractor matches prior local experiments:
- drafted_tokens_attempted := sum(conf.drafted) + miss_first_count
- draft_tokens_accepted   := sum(conf.committed)
- acceptance_rate         := accepted / attempted

Note: this is an estimate; it assumes `drafted` / `committed` in the log refer
to draft tokens (not counting the trunk token) and counts first-draft misses as
1 attempted draft token.
"""

from __future__ import annotations

import json
import re
import sys
from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


CONF_RE = re.compile(
	r"ds4: mtp conf drafted=(?P<drafted>-?\d+)\s+committed=(?P<committed>-?\d+)\s+"
	r"mtp_top=(?P<mtp_top>-?\d+)\s+runner=(?P<runner>-?\d+)\s+margin=(?P<margin>-?[0-9.]+)\s+"
	r"target_next=(?P<target_next>-?\d+)\s+draft_next=(?P<draft_next>-?\d+)"
)

MISS_FIRST_RE = re.compile(r"ds4: mtp spec miss first(?:\s+draft=(?P<draft>-?\d+))?")

TPS_RE = re.compile(r"ds4: prefill:\s+(?P<prefill>[0-9.]+)\s+t/s,\s+generation:\s+(?P<gen>[0-9.]+)\s+t/s")

CACHE_PREP_RE = re.compile(
	r"ds4: CUDA startup model cache prepared\s+(?P<gib>[0-9.]+)\s+GiB of tensor spans in\s+(?P<sec>[0-9.]+)s"
)

CUDA_LOADING_RE = re.compile(r"ds4: CUDA loading model tensors")

TIMING_RE = re.compile(r"ds4: mtp timing (?P<kind>[a-z0-9_-]+)\s+(?P<body>.*)")

TIMING_KV_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*)=(?P<value>-?[0-9]+(?:\.[0-9]+)?)")

BENCH_RE = re.compile(r"ds4: mtp bench (?P<body>.*)")

BENCH_KV_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*)=(?P<value>[^\s]+)")

TIMING_COMPONENT_KEYS = {
	"first_eval": "target_eval_ms",
	"draft": "draft_eval_ms",
	"target": "target_eval_ms",
	"head": "output_head_ms",
	"snapshot": "capture_ms",
	"prefix": "token_commit_ms",
	"replay": "verifier_replay_ms",
	"exact_replay": "verifier_replay_ms",
}

TIMING_COUNT_KEYS = {
	"verifier_calls": "target_verifier_invocation_count",
	"target_positions": "target_positions_verified",
	"target_calls": "target_eval_call_count",
	"draft_calls": "draft_eval_call_count",
	"head_calls": "output_head_call_count",
	"replay_calls": "verifier_replay_count",
	"rewind_calls": "cache_rewind_count",
	"cache_sync_calls": "cache_sync_count",
	"cuda_sync_calls": "cuda_sync_count",
	"head_rows": "output_head_rows",
	"full_vocab_rows": "full_vocab_logits_rows",
	"top1_rows": "top1_only_rows",
}


@dataclass(frozen=True)
class ConfEvent:
	drafted: int
	committed: int
	mtp_top: int
	runner: int
	margin: float
	target_next: int
	draft_next: int


@dataclass(frozen=True)
class MissFirstEvent:
	draft: Optional[int]


@dataclass(frozen=True)
class TimingEvent:
	kind: str
	values: dict[str, float]


@dataclass(frozen=True)
class BenchEvent:
	values: dict[str, Any]


def _iter_lines(paths: list[Path]) -> Iterable[str]:
	for path in paths:
		try:
			with path.open("r", encoding="utf-8", errors="replace") as f:
				for line in f:
					yield line.rstrip("\n")
		except OSError as e:
			raise RuntimeError(f"failed to read {path}: {e}") from e


def _as_int(s: str) -> int:
	try:
		return int(s, 10)
	except ValueError:
		return 0


def _as_float(s: str) -> float:
	try:
		return float(s)
	except ValueError:
		return 0.0


def _parse_timing_values(body: str) -> dict[str, float]:
	values: dict[str, float] = {}
	for m in TIMING_KV_RE.finditer(body):
		values[str(m.group("key"))] = _as_float(m.group("value"))
	return values


def _parse_bench_values(body: str) -> dict[str, Any]:
	values: dict[str, Any] = {}
	for m in BENCH_KV_RE.finditer(body):
		key = str(m.group("key"))
		raw = str(m.group("value"))
		if re.fullmatch(r"-?[0-9]+", raw):
			values[key] = _as_int(raw)
		elif re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", raw):
			values[key] = _as_float(raw)
		else:
			values[key] = raw
	return values


def _zero_components() -> dict[str, float]:
	return {
		"verifier_replay_ms": 0.0,
		"draft_eval_ms": 0.0,
		"target_eval_ms": 0.0,
		"output_head_ms": 0.0,
		"cache_sync_ms": 0.0,
		"cuda_sync_ms": 0.0,
		"logging_ms": 0.0,
		"capture_ms": 0.0,
		"token_commit_ms": 0.0,
		"scheduler_overhead_ms": 0.0,
	}


def _zero_counts() -> dict[str, int]:
	return {
		"target_verifier_invocation_count": 0,
		"target_positions_verified": 0,
		"target_eval_call_count": 0,
		"draft_eval_call_count": 0,
		"output_head_call_count": 0,
		"verifier_replay_count": 0,
		"cache_rewind_count": 0,
		"cache_sync_count": 0,
		"cuda_sync_count": 0,
		"output_head_rows": 0,
		"full_vocab_logits_rows": 0,
		"top1_only_rows": 0,
	}


def _timing_int(values: dict[str, float], key: str, default: int = 0) -> int:
	if key not in values:
		return int(default)
	return int(values.get(key, default))


def summarize_timing_events(events: list[TimingEvent]) -> dict[str, Any]:
	components = _zero_components()
	counts = _zero_counts()
	total_ms = 0.0
	verifier_ms = 0.0
	emitted_tokens = 0
	kinds: Counter[str] = Counter()
	for ev in events:
		kinds[str(ev.kind)] += 1
		event_component_ms = 0.0
		verify_ms = float(ev.values.get("verify", 0.0))
		verifier_ms += verify_ms
		if "target" not in ev.values and "head" not in ev.values:
			components["target_eval_ms"] += verify_ms
		for key, component in TIMING_COMPONENT_KEYS.items():
			component_ms = float(ev.values.get(key, 0.0))
			components[component] += component_ms
			if verify_ms == 0.0 or key not in ("target", "head"):
				event_component_ms += component_ms
		event_component_ms += verify_ms
		for key, count_field in TIMING_COUNT_KEYS.items():
			if key in ev.values:
				counts[count_field] += _timing_int(ev.values, key)
		drafted = _timing_int(ev.values, "drafted")
		committed = _timing_int(ev.values, "committed")
		if "draft_calls" not in ev.values and drafted > 1 and float(ev.values.get("draft", 0.0)) > 0.0:
			counts["draft_eval_call_count"] += (drafted - 1)
		if "target_calls" not in ev.values and verify_ms > 0.0:
			if str(ev.kind) == "decode2":
				counts["target_eval_call_count"] += 2
			else:
				counts["target_eval_call_count"] += 1
		if "head_calls" not in ev.values and verify_ms > 0.0:
			if str(ev.kind) == "decode2":
				counts["output_head_call_count"] += 2
			else:
				counts["output_head_call_count"] += 1
		if "replay_calls" not in ev.values and (float(ev.values.get("replay", 0.0)) > 0.0 or float(ev.values.get("exact_replay", 0.0)) > 0.0):
			counts["verifier_replay_count"] += 1
		if "rewind_calls" not in ev.values and (float(ev.values.get("replay", 0.0)) > 0.0 or float(ev.values.get("exact_replay", 0.0)) > 0.0):
			counts["cache_rewind_count"] += 1
		if "emitted" in ev.values:
			emitted_tokens += _timing_int(ev.values, "emitted")
		elif "committed" in ev.values:
			emitted_tokens += (committed + 1)
		event_total_ms = float(ev.values.get("total", 0.0))
		if event_total_ms > event_component_ms:
			components["scheduler_overhead_ms"] += (event_total_ms - event_component_ms)
		total_ms += event_total_ms
	slowest_component = None
	if len(events) > 0:
		slowest_component = max(components.items(), key=lambda kv: float(kv[1]))[0]
	if slowest_component is not None and float(components.get(slowest_component, 0.0)) <= 0.0:
		slowest_component = None
	return {
		"events": int(len(events)),
		"kinds": {str(k): int(v) for k, v in sorted(kinds.items(), key=lambda kv: kv[0])},
		"per_component_ms": components,
		"call_counts": counts,
		"verifier_ms": float(verifier_ms),
		"emitted_tokens": int(emitted_tokens),
		"total_reported_ms": float(total_ms),
		"slowest_component": slowest_component,
	}


def extract_events(lines: Iterable[str]) -> dict[str, Any]:
	conf_events: list[ConfEvent] = []
	miss_first_events: list[MissFirstEvent] = []
	timing_events: list[TimingEvent] = []
	bench_events: list[BenchEvent] = []
	cuda_loading_lines = 0
	prefill_tps: Optional[float] = None
	generation_tps: Optional[float] = None
	startup_cache_gib: Optional[float] = None
	startup_cache_s: Optional[float] = None

	for line in lines:
		if line.strip() == "":
			continue

		m = CONF_RE.search(line)
		if m is not None:
			conf_events.append(
				ConfEvent(
					drafted=_as_int(m.group("drafted")),
					committed=_as_int(m.group("committed")),
					mtp_top=_as_int(m.group("mtp_top")),
					runner=_as_int(m.group("runner")),
					margin=_as_float(m.group("margin")),
					target_next=_as_int(m.group("target_next")),
					draft_next=_as_int(m.group("draft_next")),
				)
			)
			continue

		m = MISS_FIRST_RE.search(line)
		if m is not None:
			draft_raw = m.group("draft")
			miss_first_events.append(MissFirstEvent(draft=_as_int(draft_raw) if draft_raw is not None else None))
			continue

		m = TPS_RE.search(line)
		if m is not None:
			prefill_tps = _as_float(m.group("prefill"))
			generation_tps = _as_float(m.group("gen"))
			continue

		m = TIMING_RE.search(line)
		if m is not None:
			timing_events.append(TimingEvent(kind=str(m.group("kind")), values=_parse_timing_values(str(m.group("body")))))
			continue

		m = BENCH_RE.search(line)
		if m is not None:
			bench_events.append(BenchEvent(values=_parse_bench_values(str(m.group("body")))))
			continue

		m = CACHE_PREP_RE.search(line)
		if m is not None:
			startup_cache_gib = _as_float(m.group("gib"))
			startup_cache_s = _as_float(m.group("sec"))
			continue

		if CUDA_LOADING_RE.search(line) is not None:
			cuda_loading_lines += 1

	timing_acceptance = [
		ev for ev in timing_events
		if str(ev.kind) == "suffix2" and "drafted" in ev.values and "committed" in ev.values
	]
	committed_hist = Counter(int(ev.committed) for ev in conf_events if int(ev.committed) >= 0)
	for ev in timing_acceptance:
		committed_hist[_timing_int(ev.values, "committed")] += 1

	accepted = sum(int(ev.committed) for ev in conf_events if int(ev.committed) >= 0)
	accepted += sum(_timing_int(ev.values, "committed") for ev in timing_acceptance)
	attempted = sum(int(ev.drafted) for ev in conf_events if int(ev.drafted) >= 0) + int(len(miss_first_events))
	attempted += sum(_timing_int(ev.values, "drafted") for ev in timing_acceptance)
	accept_rate = (float(accepted) / float(attempted)) if attempted > 0 else None

	target_next_mismatch = 0
	for ev in conf_events:
		if int(ev.drafted) <= 1:
			continue
		if int(ev.target_next) < 0 or int(ev.draft_next) < 0:
			continue
		if int(ev.target_next) != int(ev.draft_next):
			target_next_mismatch += 1

	out: dict[str, Any] = {
		"ok": True,
		"counts": {
			"conf_events": int(len(conf_events)),
			"miss_first_events": int(len(miss_first_events)),
			"timing_acceptance_events": int(len(timing_acceptance)),
		},
		"totals": {
			"draft_tokens_attempted_est": int(attempted),
			"draft_tokens_accepted_est": int(accepted),
			"draft_accept_rate_est": accept_rate,
		},
		"hist": {
			"committed": {str(k): int(v) for k, v in sorted(committed_hist.items(), key=lambda kv: kv[0])},
		},
		"mismatches": {
			"target_next_mismatch_events": int(target_next_mismatch),
		},
		"speed": {
			"prefill_tps": prefill_tps,
			"generation_tps": generation_tps,
		},
		"cuda": {
			"cuda_loading_lines": int(cuda_loading_lines),
			"startup_cache_gib": startup_cache_gib,
			"startup_cache_s": startup_cache_s,
		},
		"timing": summarize_timing_events(timing_events),
		"benchmark": {
			"events": [ev.values for ev in bench_events],
			"external_wall_s": next(
				(float(ev.values["external_wall_s"]) for ev in reversed(bench_events) if "external_wall_s" in ev.values),
				None,
			),
			"exit_code": next(
				(int(ev.values["exit_code"]) for ev in reversed(bench_events) if "exit_code" in ev.values),
				None,
			),
			"phase": next(
				(str(ev.values["phase"]) for ev in reversed(bench_events) if "phase" in ev.values),
				None,
			),
			"spec_disabled": next(
				(int(ev.values["spec_disabled"]) for ev in reversed(bench_events) if "spec_disabled" in ev.values),
				None,
			),
		},
	}

	# If we didn't find any acceptance-related records, treat this as not-ok.
	if len(conf_events) == 0 and len(miss_first_events) == 0 and len(timing_acceptance) == 0:
		out["ok"] = False
		out["errors"] = [
			"no mtp conf or mtp spec miss first events found; enable DS4_MTP_CONF_LOG=1 and capture stderr",
		]

	return out


def write_events_jsonl(
	conf_events: list[ConfEvent],
	miss_first_events: list[MissFirstEvent],
	timing_events: list[TimingEvent],
	bench_events: list[BenchEvent],
	dst: Path,
) -> None:
	with dst.open("w", encoding="utf-8") as f:
		for ev in conf_events:
			f.write(
				json.dumps(
					{
						"type": "mtp_conf",
						"drafted": int(ev.drafted),
						"committed": int(ev.committed),
						"mtp_top": int(ev.mtp_top),
						"runner": int(ev.runner),
						"margin": float(ev.margin),
						"target_next": int(ev.target_next),
						"draft_next": int(ev.draft_next),
					},
					sort_keys=True,
				)
				+ "\n"
			)
		for ev in miss_first_events:
			f.write(json.dumps({"type": "mtp_miss_first", "draft": ev.draft}, sort_keys=True) + "\n")
		for ev in timing_events:
			f.write(json.dumps({"type": "mtp_timing", "kind": ev.kind, "values": ev.values}, sort_keys=True) + "\n")
		for ev in bench_events:
			f.write(json.dumps({"type": "mtp_bench", "values": ev.values}, sort_keys=True) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--in", dest="inputs", action="append", default=[], help="Input log file path (repeatable).")
	ap.add_argument("--out-json", default="", help="Write summary JSON here (optional).")
	ap.add_argument("--out-jsonl", default="", help="Write extracted JSONL events here (optional).")
	ap.add_argument("--json", action="store_true", help="Print summary JSON to stdout (default).")
	args = ap.parse_args(argv)

	inputs = [Path(p) for p in (args.inputs or [])]
	if not inputs:
		inputs = [Path("-")]

	lines: Iterable[str]
	if len(inputs) == 1 and str(inputs[0]) == "-":
		lines = (ln.rstrip("\n") for ln in sys.stdin)
	else:
		lines = _iter_lines(inputs)

	# Re-parse twice if we need to emit JSONL events.
	all_lines = list(lines)
	res = extract_events(all_lines)

	out_json_path = str(args.out_json)
	if out_json_path:
		Path(out_json_path).write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")

	out_jsonl_path = str(args.out_jsonl)
	if out_jsonl_path:
		conf_events: list[ConfEvent] = []
		miss_first_events: list[MissFirstEvent] = []
		timing_events: list[TimingEvent] = []
		bench_events: list[BenchEvent] = []
		for line in all_lines:
			m = CONF_RE.search(line)
			if m is not None:
				conf_events.append(
					ConfEvent(
						drafted=_as_int(m.group("drafted")),
						committed=_as_int(m.group("committed")),
						mtp_top=_as_int(m.group("mtp_top")),
						runner=_as_int(m.group("runner")),
						margin=_as_float(m.group("margin")),
						target_next=_as_int(m.group("target_next")),
						draft_next=_as_int(m.group("draft_next")),
					)
				)
				continue
			m = MISS_FIRST_RE.search(line)
			if m is not None:
				draft_raw = m.group("draft")
				miss_first_events.append(MissFirstEvent(draft=_as_int(draft_raw) if draft_raw is not None else None))
				continue
			m = TIMING_RE.search(line)
			if m is not None:
				timing_events.append(TimingEvent(kind=str(m.group("kind")), values=_parse_timing_values(str(m.group("body")))))
				continue
			m = BENCH_RE.search(line)
			if m is not None:
				bench_events.append(BenchEvent(values=_parse_bench_values(str(m.group("body")))))
				continue
		write_events_jsonl(conf_events, miss_first_events, timing_events, bench_events, Path(out_jsonl_path))

	print(json.dumps(res, indent=2, sort_keys=True))
	return 0 if bool(res.get("ok", False)) else 1


if __name__ == "__main__":
	raise SystemExit(main())
