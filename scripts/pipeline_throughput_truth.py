#!/usr/bin/env python3
"""Summarize executed pipeline quality regression throughput records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FORMAT = "pipeline-throughput-truth-v1"
QUALITY_FORMAT = "pipeline-quality-regression-v1"


def load_records(path: Path) -> list[dict[str, Any]]:
	records: list[dict[str, Any]] = []
	for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
		if not line.strip():
			continue
		obj = json.loads(line)
		if not isinstance(obj, dict):
			raise ValueError(f"{path}:{lineno}: record must be an object")
		if obj.get("format") != QUALITY_FORMAT:
			raise ValueError(f"{path}:{lineno}: unsupported format {obj.get('format')!r}")
		records.append(obj)
	return records


def summarize(path: Path) -> dict[str, Any]:
	records = load_records(path)
	questions = [row for row in records if row.get("record_type") == "question"]
	if not questions:
		raise ValueError(f"{path}: no question records")
	generated_tokens = sum(int(row.get("generated_tokens") or 0) for row in questions)
	elapsed_sec = sum(float(row.get("elapsed_sec") or 0.0) for row in questions)
	passed = sum(1 for row in questions if row.get("passed") is True)
	failed = sum(1 for row in questions if row.get("passed") is False)
	return {
		"format": FORMAT,
		"source_path": str(path),
		"run_id": str(questions[0].get("run_id") or ""),
		"backend_mode": str(questions[0].get("backend_mode") or ""),
		"question_count": len(questions),
		"passed": passed,
		"failed": failed,
		"generated_tokens": generated_tokens,
		"elapsed_sec": elapsed_sec,
		"aggregate_output_tokens_per_s": generated_tokens / elapsed_sec if elapsed_sec > 0.0 else 0.0,
		"case_tokens_per_s": [
			{
				"case_id": row.get("case_id"),
				"passed": row.get("passed"),
				"generated_tokens": row.get("generated_tokens"),
				"elapsed_sec": row.get("elapsed_sec"),
				"output_tokens_per_s": row.get("output_tokens_per_s"),
			}
			for row in questions
		],
	}


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("quality_jsonl")
	ap.add_argument("--out", default="")
	args = ap.parse_args(argv)
	obj = summarize(Path(args.quality_jsonl))
	text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
	if args.out:
		Path(args.out).parent.mkdir(parents=True, exist_ok=True)
		Path(args.out).write_text(text, encoding="utf-8")
	else:
		print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
