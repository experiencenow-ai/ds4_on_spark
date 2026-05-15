#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _load_tokenizer_vocab(tokenizer_json: Path) -> dict[int, str]:
	try:
		doc = json.loads(tokenizer_json.read_text(encoding="utf-8"))
	except OSError as e:
		_die(f"failed to read tokenizer json: {tokenizer_json}: {e}")
	except json.JSONDecodeError as e:
		_die(f"failed to parse tokenizer json: {tokenizer_json}: {e}")

	model = doc.get("model")
	if not isinstance(model, dict):
		_die("tokenizer.json missing object field: model")
	vocab = model.get("vocab")
	if not isinstance(vocab, dict):
		_die("tokenizer.json missing object field: model.vocab")

	out: dict[int, str] = {}
	for tok, tid in vocab.items():
		if not isinstance(tok, str):
			continue
		if not isinstance(tid, int):
			continue
		# Keep first token for an id; collisions are unexpected but not fatal.
		out.setdefault(int(tid), tok)
	return out


def _pretty_token(tok: str) -> str:
	# Keep this conservative: do not attempt to render byte escapes; just make control
	# characters visible.
	return (
		tok.replace("\r", "\\r")
		.replace("\n", "\\n")
		.replace("\t", "\\t")
	)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for idx, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
		line = raw.strip()
		if not line:
			continue
		try:
			doc = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(doc, dict):
			out.append(doc)
		else:
			out.append({"type": "unknown", "line_idx": idx, "raw": doc})
	return out


def main(argv: Optional[list[str]] = None) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--in-events-jsonl", required=True, help="Input events JSONL (from extract_antirez_ds4_mtp_conf_log.py).")
	ap.add_argument("--out-events-jsonl", required=True, help="Output JSONL path with token string annotations.")
	ap.add_argument(
		"--tokenizer-json",
		default="fixtures/model_contract/deepseek_v4_flash/tokenizer.json",
		help="Tokenizer JSON (tokenizers format). Default: fixtures/model_contract/deepseek_v4_flash/tokenizer.json",
	)
	ap.add_argument("--json", action="store_true", help="Emit JSON summary to stdout (default).")
	args = ap.parse_args(argv)

	in_path = Path(str(args.in_events_jsonl))
	out_path = Path(str(args.out_events_jsonl))
	tokenizer_json = Path(str(args.tokenizer_json))

	if not in_path.is_file():
		_die(f"missing input events jsonl: {in_path}")
	if not tokenizer_json.is_file():
		_die(f"missing tokenizer json: {tokenizer_json}")

	id_to_token = _load_tokenizer_vocab(tokenizer_json)
	events = _read_jsonl(in_path)

	out_path.parent.mkdir(parents=True, exist_ok=True)

	records = 0
	conf_events = 0
	mismatch = 0

	with out_path.open("w", encoding="utf-8") as f:
		for ev in events:
			records += 1
			if ev.get("type") == "mtp_conf":
				conf_events += 1
				tid = ev.get("target_next")
				did = ev.get("draft_next")
				if isinstance(tid, int):
					tok = id_to_token.get(int(tid))
					if tok is not None:
						ev["target_next_token"] = tok
						ev["target_next_token_pretty"] = _pretty_token(tok)
				if isinstance(did, int):
					tok = id_to_token.get(int(did))
					if tok is not None:
						ev["draft_next_token"] = tok
						ev["draft_next_token_pretty"] = _pretty_token(tok)
				if isinstance(tid, int) and isinstance(did, int) and int(tid) != int(did):
					mismatch += 1

			f.write(json.dumps(ev, sort_keys=True))
			f.write("\n")

	summary = {
		"ok": True,
		"tokenizer_json": str(tokenizer_json),
		"stats": {"records": int(records), "conf_events": int(conf_events), "target_next_mismatch": int(mismatch)},
		"paths": {"in_events_jsonl": str(in_path), "out_events_jsonl": str(out_path)},
	}
	print(json.dumps(summary, indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

