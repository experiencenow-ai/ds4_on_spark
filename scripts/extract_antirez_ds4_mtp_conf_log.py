#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


KV_RE = re.compile(r"(?P<k>[A-Za-z_][A-Za-z0-9_]*)=(?P<v>[^\s]+)")


@dataclass(frozen=True)
class ExtractStats:
	lines: int = 0
	conf_events: int = 0
	timing_events: int = 0
	miss_first_events: int = 0
	parse_errors: int = 0


def _coerce_num(s: str) -> Any:
	try:
		if s.startswith("0x") or s.startswith("0X"):
			return int(s, 16)
		if re.fullmatch(r"-?[0-9]+", s):
			return int(s)
		if re.fullmatch(r"-?[0-9]+\\.[0-9]+", s):
			return float(s)
	except Exception:
		return s
	return s


def _extract_kv_pairs(tail: str) -> dict[str, Any]:
	out: dict[str, Any] = {}
	for m in KV_RE.finditer(tail):
		k = m.group("k")
		v_raw = m.group("v")
		out[k] = _coerce_num(v_raw)
	return out


def _iter_lines(path: Path) -> Iterable[str]:
	with path.open("r", encoding="utf-8", errors="replace") as f:
		for line in f:
			yield line.rstrip("\n")


def extract_events(
	lines: Iterable[str],
	*,
	conf_marker: str,
	timing_marker: str,
	miss_first_marker: str,
) -> tuple[list[dict[str, Any]], ExtractStats]:
	events: list[dict[str, Any]] = []
	stats = ExtractStats()

	for idx, raw in enumerate(lines, start=1):
		line = raw.strip()
		stats = ExtractStats(
			lines=stats.lines + 1,
			conf_events=stats.conf_events,
			timing_events=stats.timing_events,
			miss_first_events=stats.miss_first_events,
			parse_errors=stats.parse_errors,
		)
		if line == "":
			continue

		try:
			if conf_marker in line:
				pos = line.index(conf_marker)
				tail = line[pos + len(conf_marker) :].strip()
				kv = _extract_kv_pairs(tail)
				ev: dict[str, Any] = {"type": "mtp_conf", "line_idx": idx}
				if isinstance(kv.get("draft_len"), int):
					ev["draft_len"] = int(kv["draft_len"])
				elif isinstance(kv.get("drafted"), int):
					ev["draft_len"] = int(kv["drafted"])
				if isinstance(kv.get("committed"), int):
					ev["committed"] = int(kv["committed"])
				if isinstance(kv.get("target_next"), int):
					ev["target_next"] = int(kv["target_next"])
				if isinstance(kv.get("draft_next"), int):
					ev["draft_next"] = int(kv["draft_next"])
				if isinstance(kv.get("mtp_accept_len"), int):
					ev["mtp_accept_len"] = int(kv["mtp_accept_len"])
				for k, v in kv.items():
					if k in ev:
						continue
					ev[k] = v
				events.append(ev)
				stats = ExtractStats(
					lines=stats.lines,
					conf_events=stats.conf_events + 1,
					timing_events=stats.timing_events,
					miss_first_events=stats.miss_first_events,
					parse_errors=stats.parse_errors,
				)
				continue

			if miss_first_marker in line:
				pos = line.index(miss_first_marker)
				tail = line[pos + len(miss_first_marker) :].strip()
				kv = _extract_kv_pairs(tail)
				ev = {"type": "mtp_spec_miss_first", "line_idx": idx}
				if isinstance(kv.get("draft"), int):
					ev["draft"] = int(kv["draft"])
				elif isinstance(kv.get("first"), int):
					ev["draft"] = int(kv["first"])
				else:
					# format sometimes uses `... miss first draft=NNN` with no key other than `draft`
					pass
				if isinstance(kv.get("draft"), int):
					ev["draft"] = int(kv["draft"])
				events.append(ev)
				stats = ExtractStats(
					lines=stats.lines,
					conf_events=stats.conf_events,
					timing_events=stats.timing_events,
					miss_first_events=stats.miss_first_events + 1,
					parse_errors=stats.parse_errors,
				)
				continue

			if timing_marker in line:
				pos = line.index(timing_marker)
				tail = line[pos + len(timing_marker) :].strip()
				kv = _extract_kv_pairs(tail)
				ev = {"type": "mtp_timing_micro", "line_idx": idx}
				for k, v in kv.items():
					ev[k] = v
				events.append(ev)
				stats = ExtractStats(
					lines=stats.lines,
					conf_events=stats.conf_events,
					timing_events=stats.timing_events + 1,
					miss_first_events=stats.miss_first_events,
					parse_errors=stats.parse_errors,
				)
				continue
		except Exception:
			stats = ExtractStats(
				lines=stats.lines,
				conf_events=stats.conf_events,
				timing_events=stats.timing_events,
				miss_first_events=stats.miss_first_events,
				parse_errors=stats.parse_errors + 1,
			)
			continue

	return events, stats


def main(argv: Optional[list[str]] = None) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in-log", required=True, help="Input ds4 stdout/stderr log (text).")
	ap.add_argument("--out-jsonl", required=True, help="Output JSONL path for extracted events.")
	ap.add_argument("--conf-marker", default="ds4: mtp conf", help="Substring marker for MTP conf lines.")
	ap.add_argument("--timing-marker", default="ds4: mtp timing micro", help="Substring marker for MTP timing micro lines.")
	ap.add_argument("--miss-first-marker", default="ds4: mtp spec miss first", help="Substring marker for first-draft miss lines.")
	ap.add_argument("--json", action="store_true", help="Emit JSON summary to stdout (default).")
	args = ap.parse_args(argv)

	in_path = Path(str(args.in_log))
	out_jsonl = Path(str(args.out_jsonl))
	out_jsonl.parent.mkdir(parents=True, exist_ok=True)

	events, stats = extract_events(
		_iter_lines(in_path),
		conf_marker=str(args.conf_marker),
		timing_marker=str(args.timing_marker),
		miss_first_marker=str(args.miss_first_marker),
	)
	with out_jsonl.open("w", encoding="utf-8") as f:
		for ev in events:
			f.write(json.dumps(ev, sort_keys=True))
			f.write("\n")

	summary = {
		"ok": True,
		"markers": {"conf": str(args.conf_marker), "timing_micro": str(args.timing_marker), "miss_first": str(args.miss_first_marker)},
		"paths": {"in_log": str(in_path), "out_jsonl": str(out_jsonl)},
		"stats": {
			"lines": int(stats.lines),
			"conf_events": int(stats.conf_events),
			"timing_events": int(stats.timing_events),
			"miss_first_events": int(stats.miss_first_events),
			"parse_errors": int(stats.parse_errors),
		},
	}
	print(json.dumps(summary, indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
