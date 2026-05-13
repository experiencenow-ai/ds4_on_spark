#!/usr/bin/env python3
"""Summarize MTP acceptance metrics from a runtime trace JSONL.

This is intentionally lightweight: it does *not* require full scheduler fields
like `candidates[]` or timestamps. It only looks for MTP acceptance fields that
appear in typical runtime logs:

- `mtp_accept_len` (preferred; >= 1)
- `accepted_mtp` / `rejected_mtp` (fallback; accept_len := accepted_mtp + 1)

It can optionally scan for embedded JSON objects in log lines.
"""

from __future__ import annotations

import json
import statistics
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from sim.scheduler import trace_extract


@dataclass(frozen=True)
class AcceptanceEvent:
	accept_len: int
	accepted_mtp: Optional[int] = None
	rejected_mtp: Optional[int] = None


def _coerce_int(value: Any) -> Optional[int]:
	if isinstance(value, int):
		return int(value)
	if isinstance(value, float):
		v = float(value)
		if float(int(v)) == v:
			return int(v)
	return None


def _get_any(container: dict[str, Any], keys: Iterable[str]) -> Any:
	for k in keys:
		if k in container:
			return container.get(k)
	return None


def _extract_acceptance_event(obj: dict[str, Any]) -> Optional[AcceptanceEvent]:
	# Prefer explicit accept_len.
	al_raw = _get_any(obj, ("mtp_accept_len", "mtp_len", "accept_len"))
	al = _coerce_int(al_raw)
	if al is not None and al >= 1:
		am = _coerce_int(_get_any(obj, ("accepted_mtp", "mtp_accepted", "accepted")))
		rm = _coerce_int(_get_any(obj, ("rejected_mtp", "mtp_rejected", "rejected")))
		if am is not None and am < 0:
			am = None
		if rm is not None and rm < 0:
			rm = None
		return AcceptanceEvent(accept_len=int(al), accepted_mtp=am, rejected_mtp=rm)

	# Fallback: accepted_mtp implies accept_len := accepted_mtp + 1.
	am_raw = _get_any(obj, ("accepted_mtp", "mtp_accepted", "accepted"))
	am = _coerce_int(am_raw)
	if am is not None and am >= 0:
		rm = _coerce_int(_get_any(obj, ("rejected_mtp", "mtp_rejected", "rejected")))
		if rm is not None and rm < 0:
			rm = None
		return AcceptanceEvent(accept_len=int(am + 1), accepted_mtp=int(am), rejected_mtp=rm)

	return None


def _iter_json_objects_from_line(line: str, *, allow_substrings: bool) -> Iterable[dict[str, Any]]:
	line = line.strip()
	if line == "" or line.startswith("#"):
		return
	for obj in trace_extract._iter_json_values_from_line(line, allow_substrings=bool(allow_substrings)):
		if isinstance(obj, dict):
			yield obj


def _summarize_ints(values: list[int]) -> dict[str, Any]:
	if len(values) == 0:
		return {"count": 0}
	vals = sorted(int(v) for v in values)
	n = len(vals)
	idx50 = int((n - 1) * 0.50)
	idx95 = int((n - 1) * 0.95)
	idx99 = int((n - 1) * 0.99)
	return {
		"count": n,
		"mean": float(statistics.fmean(float(v) for v in vals)),
		"min": int(vals[0]),
		"p50": int(vals[idx50]),
		"p95": int(vals[idx95]),
		"p99": int(vals[idx99]),
		"max": int(vals[-1]),
	}


def summarize_mtp_acceptance_events(
	events: list[AcceptanceEvent],
	*,
	draft_len: int,
) -> dict[str, Any]:
	out: dict[str, Any] = {
		"ok": False,
		"errors": [],
		"draft_len": int(draft_len),
		"events": int(len(events)),
	}

	if int(draft_len) < 0:
		out["errors"].append("draft_len must be >= 0")
		return out

	accept_lens = [int(e.accept_len) for e in events if int(e.accept_len) >= 1]
	out["mtp_accept_len"] = _summarize_ints(accept_lens)

	accepted_draft = [int(al - 1) for al in accept_lens if int(al) >= 1]
	out["accepted_draft_tokens"] = _summarize_ints(accepted_draft)

	if int(draft_len) > 0:
		dl = int(draft_len)
		counts = [0 for _ in range(dl + 1)]
		invalid = 0
		for al in accept_lens:
			if al < 1 or al > (dl + 1):
				invalid += 1
				continue
			counts[al - 1] += 1
		total = int(sum(counts))
		out["mtp_accept_len_hist"] = {
			"draft_len": int(dl),
			"total": int(total),
			"invalid": int(invalid),
			"accept_len_values": [i + 1 for i in range(dl + 1)],
			"counts": counts,
			"prob": ([float(c) / float(total) for c in counts] if total > 0 else [0.0 for _ in counts]),
		}
		if len(accept_lens) > 0:
			out["acceptance_rate"] = float(statistics.fmean(float(max(0, al - 1)) for al in accept_lens) / float(dl))

	out["ok"] = (len(out["errors"]) == 0)
	return out


def summarize_mtp_acceptance_jsonl(
	lines: Iterable[str],
	*,
	draft_len: int,
	allow_substrings: bool,
) -> dict[str, Any]:
	events: list[AcceptanceEvent] = []
	records = 0

	for line in lines:
		for obj in _iter_json_objects_from_line(line, allow_substrings=allow_substrings):
			records += 1
			if "type" in obj and obj.get("type") in ("meta", "trace_meta"):
				continue

			# Prefer the extracted view when possible; fall back to raw records for
			# runtimes that emit MTP-only metrics without route fields.
			rec = trace_extract.extract_route_record(obj) or obj
			ev = _extract_acceptance_event(rec) or _extract_acceptance_event(obj)

			if ev is None:
				continue
			events.append(ev)

	out = summarize_mtp_acceptance_events(events, draft_len=draft_len)
	out["records"] = int(records)
	out["notes"] = [
		"accept_len is interpreted as accepted_mtp+1 when only accepted_mtp is present",
	]
	return out


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--in-jsonl", default="-", help="Input JSONL path (or '-' for stdin).")
	ap.add_argument("--draft-len", type=int, default=0, help="MTP draft length (gamma). Optional; enables hist/rate.")
	ap.add_argument(
		"--extract-substrings",
		type=int,
		default=1,
		help="Scan non-JSON lines for embedded JSON objects (0/1).",
	)
	ap.add_argument("--json", action="store_true", help="Emit JSON output (default).")
	args = ap.parse_args(argv)

	in_path = str(args.in_jsonl)
	if in_path == "-":
		lines = sys.stdin
	else:
		lines = Path(in_path).open("r", encoding="utf-8")

	try:
		res = summarize_mtp_acceptance_jsonl(
			lines,
			draft_len=int(args.draft_len),
			allow_substrings=bool(int(args.extract_substrings)),
		)
	finally:
		if in_path != "-":
			lines.close()

	# Default to JSON (stable for reports/CI); keep --json for symmetry with other tools.
	print(json.dumps(res, indent=2, sort_keys=True))
	return 0 if bool(res.get("ok", False)) else 1


if __name__ == "__main__":
	raise SystemExit(main())

