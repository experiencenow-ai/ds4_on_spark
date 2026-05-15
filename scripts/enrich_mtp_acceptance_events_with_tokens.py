#!/usr/bin/env python3
"""Enrich MTP acceptance events with token strings from a tokenizer.json vocab.

This expects the JSONL produced by `extract_ds4_mtp_conf_log_events.py` and adds:
  - `target_next_token`, `draft_next_token`
  - `*_token_pretty` (repr-style for whitespace/newlines)

It also emits a small mismatch report for `mtp_conf` lines where
`target_next_id != draft_next_id`.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _read_json(path: Path) -> Any:
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	except json.JSONDecodeError as e:
		_die(f"failed to parse JSON {path}: {e}")
	return None


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	try:
		with path.open("r", encoding="utf-8") as f:
			for raw in f:
				line = raw.strip()
				if line == "":
					continue
				obj = json.loads(line)
				if isinstance(obj, dict):
					out.append(obj)
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	except json.JSONDecodeError as e:
		_die(f"failed to parse JSONL {path}: {e}")
	return out


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		for rec in records:
			f.write(json.dumps(rec, sort_keys=True) + "\n")


def _write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _token_pretty(s: Optional[str]) -> Optional[str]:
	if s is None:
		return None
	# repr() makes whitespace/newlines visible; strip surrounding quotes.
	r = repr(s)
	if len(r) >= 2 and r[0] == "'" and r[-1] == "'":
		return r[1:-1]
	return r


def _load_vocab_id_to_token(tokenizer_json: dict[str, Any]) -> dict[int, str]:
	model = tokenizer_json.get("model", {})
	vocab = model.get("vocab")
	if not isinstance(vocab, dict):
		_die("tokenizer.json missing model.vocab dict")
	id_to_token: dict[int, str] = {}
	for tok, tid in vocab.items():
		if not isinstance(tok, str):
			continue
		if not isinstance(tid, int):
			continue
		id_to_token[int(tid)] = tok
	return id_to_token


def enrich_events(
	events: list[dict[str, Any]],
	*,
	id_to_token: dict[int, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	out_events: list[dict[str, Any]] = []
	mismatches: list[dict[str, Any]] = []
	conf_total = 0

	for ev in events:
		ev2 = dict(ev)
		if ev2.get("type") == "mtp_conf":
			conf_total += 1
			tid = ev2.get("target_next_id")
			did = ev2.get("draft_next_id")
			tok_t = id_to_token.get(int(tid)) if isinstance(tid, int) else None
			tok_d = id_to_token.get(int(did)) if isinstance(did, int) else None
			ev2["target_next_token"] = tok_t
			ev2["draft_next_token"] = tok_d
			ev2["target_next_token_pretty"] = _token_pretty(tok_t)
			ev2["draft_next_token_pretty"] = _token_pretty(tok_d)
			if isinstance(tid, int) and isinstance(did, int) and tid != did:
				mismatches.append(
					{
						"target_next_id": int(tid),
						"draft_next_id": int(did),
						"target_next_token_pretty": _token_pretty(tok_t),
						"draft_next_token_pretty": _token_pretty(tok_d),
						"source_path": ev2.get("source_path"),
						"lineno": ev2.get("lineno"),
						"raw": ev2.get("raw"),
					}
				)
		out_events.append(ev2)

	report = {
		"ok": True,
		"conf_events": int(conf_total),
		"mismatch_count": int(len(mismatches)),
		"mismatches": mismatches[:64],
	}
	return out_events, report


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--in-jsonl", required=True, help="Input events JSONL (from extract_ds4_mtp_conf_log_events.py).")
	ap.add_argument("--tokenizer-json", required=True, help="HF tokenizer.json with model.vocab.")
	ap.add_argument("--out-jsonl", required=True, help="Output enriched JSONL.")
	ap.add_argument("--out-report-json", required=True, help="Mismatch report JSON output.")
	args = ap.parse_args(argv)

	events = _iter_jsonl(Path(args.in_jsonl))
	tokenizer = _read_json(Path(args.tokenizer_json))
	if not isinstance(tokenizer, dict):
		_die("tokenizer JSON top-level is not an object")
	id_to_token = _load_vocab_id_to_token(tokenizer)

	enriched, report = enrich_events(events, id_to_token=id_to_token)
	_write_jsonl(Path(args.out_jsonl), enriched)
	_write_json(Path(args.out_report_json), report)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

