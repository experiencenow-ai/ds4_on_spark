#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional


THROUGHPUT_RE = re.compile(r"prefill:\s*(?P<p>[0-9]+(?:\.[0-9]+)?)\s*t/s,\s*generation:\s*(?P<g>[0-9]+(?:\.[0-9]+)?)\s*t/s")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = raw.strip()
		if not line:
			continue
		try:
			doc = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(doc, dict):
			out.append(doc)
	return out


def _extract_last_throughput(log_path: Path) -> Optional[dict[str, float]]:
	if not log_path.is_file():
		return None
	last: Optional[dict[str, float]] = None
	for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
		m = THROUGHPUT_RE.search(raw)
		if not m:
			continue
		try:
			last = {"prefill_tps": float(m.group("p")), "generation_tps": float(m.group("g"))}
		except Exception:
			continue
	return last


def main(argv: Optional[list[str]] = None) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in-events-jsonl", required=True, help="Input events JSONL (optionally enriched).")
	ap.add_argument("--in-log", default="", help="Optional original log path to extract the last throughput line.")
	ap.add_argument("--json", action="store_true", help="Emit JSON output (default).")
	args = ap.parse_args(argv)

	events_path = Path(str(args.in_events_jsonl))
	if not events_path.is_file():
		print(json.dumps({"ok": False, "errors": [f"missing events jsonl: {events_path}"]}, indent=2, sort_keys=True))
		return 2

	events = _read_jsonl(events_path)

	errors: list[str] = []
	conf_events = 0
	miss_first_count = 0
	target_next_mismatch_count = 0

	committed_hist: Counter[int] = Counter()
	committed_total = 0
	drafted_total = 0

	for ev in events:
		typ = ev.get("type")
		if typ == "mtp_spec_miss_first":
			miss_first_count += 1
			continue
		if typ != "mtp_conf":
			continue
		conf_events += 1

		dl = ev.get("draft_len")
		if isinstance(dl, int) and dl >= 0:
			drafted_total += int(dl)

		committed = ev.get("committed")
		if not (isinstance(committed, int) and committed >= 0):
			al = ev.get("mtp_accept_len")
			if isinstance(al, int) and al >= 1:
				committed = int(al - 1)
		if isinstance(committed, int) and committed >= 0:
			committed_hist[int(committed)] += 1
			committed_total += int(committed)

		tn = ev.get("target_next")
		dn = ev.get("draft_next")
		if isinstance(tn, int) and isinstance(dn, int) and int(tn) != int(dn):
			target_next_mismatch_count += 1

	draft_tokens_attempted_est = drafted_total + miss_first_count
	draft_tokens_accepted_est = committed_total
	draft_accept_rate_est = float(draft_tokens_accepted_est) / float(draft_tokens_attempted_est) if draft_tokens_attempted_est > 0 else 0.0

	last_throughput = _extract_last_throughput(Path(args.in_log)) if str(args.in_log) else None

	out = {
		"ok": len(errors) == 0,
		"errors": errors,
		"conf_events": int(conf_events),
		"miss_first_count": int(miss_first_count),
		"target_next_mismatch_count": int(target_next_mismatch_count),
		"committed_hist": {str(k): int(v) for k, v in sorted(committed_hist.items())},
		"committed_total": int(committed_total),
		"drafted_total": int(drafted_total),
		"draft_tokens_attempted_est": int(draft_tokens_attempted_est),
		"draft_tokens_accepted_est": int(draft_tokens_accepted_est),
		"draft_accept_rate_est": float(draft_accept_rate_est),
		"last_throughput": last_throughput,
		"notes": [
			"draft_tokens_attempted_est = drafted_total + miss_first_count",
			"draft_tokens_accepted_est = committed_total",
			"target_next_mismatch_count counts conf events where target_next != draft_next",
		],
	}

	print(json.dumps(out, indent=2, sort_keys=True))
	return 0 if out["ok"] else 1


if __name__ == "__main__":
	raise SystemExit(main())
