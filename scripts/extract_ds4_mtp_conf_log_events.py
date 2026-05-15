#!/usr/bin/env python3
"""Extract DS4 MTP conf/timing log events into JSONL.

This is purpose-built for Spark runs of antirez/ds4 where `DS4_MTP_CONF_LOG=1`
emits lines like:

  ds4: mtp conf drafted=2 committed=2 target_next=3967 draft_next=3967 ...

It extracts:
  - `mtp_conf` events (drafted/committed/target_next/draft_next)
  - `mtp_spec_miss_first` markers
  - `mtp_timing_micro` key/value payloads
  - best-effort throughput markers (`t/s`)

The output JSONL is intended to feed token enrichment and acceptance summaries.
"""

from __future__ import annotations

import json
import re
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


_RE_KV_INT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(-?[0-9]+)")
_RE_TS = re.compile(r"([0-9]+(?:\\.[0-9]+)?)\\s*t/s")


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _read_lines(path: Path) -> list[str]:
	try:
		return path.read_text(encoding="utf-8", errors="replace").splitlines()
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	return []


def _jsonl_write(path: Path, records: list[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		for rec in records:
			f.write(json.dumps(rec, sort_keys=True) + "\n")


def _json_write(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _coerce_int(v: Any) -> Optional[int]:
	if isinstance(v, int):
		return int(v)
	if isinstance(v, str):
		try:
			return int(v, 10)
		except ValueError:
			return None
	return None


@dataclass(frozen=True)
class ConfEvent:
	drafted: int
	committed: int
	target_next_id: int
	draft_next_id: int


def _parse_conf_event(line: str) -> Optional[ConfEvent]:
	if "ds4: mtp conf" not in line:
		return None
	kvs = {k: v for k, v in _RE_KV_INT.findall(line)}
	drafted = _coerce_int(kvs.get("drafted"))
	committed = _coerce_int(kvs.get("committed"))
	target_next = _coerce_int(kvs.get("target_next"))
	draft_next = _coerce_int(kvs.get("draft_next"))
	if drafted is None or committed is None or target_next is None or draft_next is None:
		return None
	return ConfEvent(
		drafted=int(drafted),
		committed=int(committed),
		target_next_id=int(target_next),
		draft_next_id=int(draft_next),
	)


def _extract_tps(line: str) -> Optional[float]:
	m = _RE_TS.search(line)
	if m is None:
		return None
	try:
		return float(m.group(1))
	except ValueError:
		return None


def extract_events(paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	events: list[dict[str, Any]] = []
	conf: list[ConfEvent] = []
	tps: list[float] = []

	for path in paths:
		for idx, raw in enumerate(_read_lines(path), start=1):
			line = raw.rstrip("\n")

			ev = _parse_conf_event(line)
			if ev is not None:
				conf.append(ev)
				events.append(
					{
						"type": "mtp_conf",
						"source_path": str(path),
						"lineno": int(idx),
						"drafted": int(ev.drafted),
						"committed": int(ev.committed),
						"target_next_id": int(ev.target_next_id),
						"draft_next_id": int(ev.draft_next_id),
						"target_next_matches_draft": bool(ev.target_next_id == ev.draft_next_id),
						"raw": line,
					}
				)
				continue

			if "ds4: mtp spec miss first" in line:
				events.append(
					{
						"type": "mtp_spec_miss_first",
						"source_path": str(path),
						"lineno": int(idx),
						"raw": line,
					}
				)
				continue

			if "ds4: mtp timing micro" in line:
				payload = {k: int(v) for k, v in _RE_KV_INT.findall(line)}
				events.append(
					{
						"type": "mtp_timing_micro",
						"source_path": str(path),
						"lineno": int(idx),
						"payload": payload,
						"raw": line,
					}
				)
				continue

			# Best-effort throughput extraction (ds4 emits these in a few formats).
			val = _extract_tps(line)
			if val is not None:
				tps.append(float(val))
				events.append(
					{
						"type": "tps_marker",
						"source_path": str(path),
						"lineno": int(idx),
						"tps": float(val),
						"raw": line,
					}
				)

	committed_hist: dict[str, int] = {}
	drafted_hist: dict[str, int] = {}
	mismatch = 0
	drafted_tokens_attempted_est = 0
	draft_tokens_accepted_est = 0

	for ev in conf:
		drafted_tokens_attempted_est += int(max(0, ev.drafted))
		draft_tokens_accepted_est += int(max(0, ev.committed))
		committed_hist[str(ev.committed)] = int(committed_hist.get(str(ev.committed), 0) + 1)
		drafted_hist[str(ev.drafted)] = int(drafted_hist.get(str(ev.drafted), 0) + 1)
		if ev.target_next_id != ev.draft_next_id:
			mismatch += 1

	out = {
		"ok": True,
		"inputs": [str(p) for p in paths],
		"events_total": int(len(events)),
		"conf_events": int(len(conf)),
		"spec_miss_first": int(sum(1 for e in events if e.get("type") == "mtp_spec_miss_first")),
		"timing_events": int(sum(1 for e in events if e.get("type") == "mtp_timing_micro")),
		"tps_markers": int(len(tps)),
		"tps_last": (float(tps[-1]) if len(tps) > 0 else None),
		"committed_hist": committed_hist,
		"drafted_hist": drafted_hist,
		"drafted_tokens_attempted_est": int(drafted_tokens_attempted_est),
		"draft_tokens_accepted_est": int(draft_tokens_accepted_est),
		"accept_rate_est": (
			(float(draft_tokens_accepted_est) / float(drafted_tokens_attempted_est))
			if drafted_tokens_attempted_est > 0
			else None
		),
		"target_next_mismatch_count": int(mismatch),
	}
	return events, out


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--in", dest="inputs", action="append", default=[], help="Input log path (repeatable).")
	ap.add_argument("--out-dir", required=True, help="Output directory for events + summary.")
	ap.add_argument("--events-jsonl", default="events.jsonl", help="Output JSONL basename.")
	ap.add_argument("--summary-json", default="summary.json", help="Output summary JSON basename.")
	args = ap.parse_args(argv)

	if not args.inputs:
		_die("missing --in inputs")

	paths = [Path(p) for p in args.inputs]
	out_dir = Path(args.out_dir)

	events, summary = extract_events(paths)
	_jsonl_write(out_dir / str(args.events_jsonl), events)
	_json_write(out_dir / str(args.summary_json), summary)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

