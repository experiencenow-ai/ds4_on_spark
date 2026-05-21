#!/usr/bin/env python3
"""Classify ds4-eval failures from an executed pipeline-quality fixture."""

from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


FORMAT = "ds4-eval-failure-analysis-v1"
DEFAULT_RUN_ID = "lane-d-pp1-redo-20260521T0412Z"
DEFAULT_JSONL = Path("fixtures/pipeline_quality") / f"{DEFAULT_RUN_ID}.jsonl"
DEFAULT_STDOUT = Path("fixtures/pipeline_quality") / f"{DEFAULT_RUN_ID}.stdout.txt.gz"
DEFAULT_OUT = Path("fixtures/pipeline_quality") / f"{DEFAULT_RUN_ID}.failure_analysis.json"
FAILURE_CLASSES = ("truncation", "wrong_answer", "format_error", "refusal", "other")
REFUSAL_PATTERNS = (
	"i cannot answer",
	"i can't answer",
	"cannot determine",
	"unable to answer",
	"not enough information to answer",
	"i do not have enough information",
	"i don't have enough information",
)


def _read_text(path: Path) -> str:
	if path.suffix == ".gz":
		with gzip.open(path, "rt", encoding="utf-8") as f:
			return f.read()
	return path.read_text(encoding="utf-8")


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	records: list[dict[str, Any]] = []
	summary: dict[str, Any] = {}
	for line in path.read_text(encoding="utf-8").splitlines():
		if not line.strip():
			continue
		obj = json.loads(line)
		if not isinstance(obj, dict):
			continue
		if obj.get("record_type") == "summary":
			summary = obj
		elif obj.get("record_type") == "question":
			records.append(obj)
	if not records:
		raise ValueError(f"{path}: no question records found")
	return records, summary


def _parse_stdout_report(path: Path | None) -> dict[int, dict[str, Any]]:
	if path is None or not path.exists():
		return {}
	report: dict[int, dict[str, Any]] = {}
	line_re = re.compile(
		r"^\s*(\d+)\s+"
		r"(PASSED|FAILED|SKIPPED|STOPPED|PENDING|RUNNING)\s+"
		r"(\d+)\s+(\d+)\s+(\d+)\s+"
		r"(\S+)\s+(\S+)\s+(.+)$"
	)
	for line in _read_text(path).splitlines():
		match = line_re.match(line)
		if not match:
			continue
		test = match.group(8)
		source, case_id = test.rsplit("/", 1) if "/" in test else ("", test)
		report[int(match.group(1))] = {
			"state": match.group(2),
			"prompt_tokens": int(match.group(3)),
			"generated_tokens": int(match.group(4)),
			"total_tokens": int(match.group(5)),
			"given": match.group(6),
			"correct": match.group(7),
			"source": source,
			"case_id": case_id,
			"raw_report_line": line,
		}
	return report


def _visible_text(text: str) -> str:
	pos = text.find("</think>")
	return text[pos + len("</think>"):] if pos >= 0 else text


def _is_refusal(text: str) -> bool:
	visible = _visible_text(text).lower()
	return any(pattern in visible for pattern in REFUSAL_PATTERNS)


def _classify_failure(row: dict[str, Any], report: dict[str, Any], max_tokens: int) -> tuple[str, str]:
	generated_tokens = int(report.get("generated_tokens") or row.get("generated_tokens") or 0)
	observed = str(row.get("observed_answer") or report.get("given") or "")
	if max_tokens > 0 and generated_tokens >= max_tokens:
		return ("truncation", f"generated_tokens={generated_tokens} reached max_tokens={max_tokens}")
	if observed in ("", "?"):
		return ("format_error", f"observed_answer={observed or '<empty>'}")
	if _is_refusal(str(row.get("generated_text") or "")):
		return ("refusal", "visible answer contains a refusal phrase")
	if row.get("ds4_eval_status") == "FAILED" or row.get("passed") is False:
		return ("wrong_answer", f"observed_answer={observed} expected_answer={row.get('expected_answer')}")
	return ("other", "record was not marked failed by known fields")


def _counter_rows(counter: Counter[str], key_name: str) -> list[dict[str, Any]]:
	return [{key_name: key, "count": counter[key]} for key in sorted(counter, key=lambda k: (-counter[k], k))]


def _domain_rows(buckets: dict[tuple[str, str], Counter[str]]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for (source, domain), counts in buckets.items():
		total = sum(counts.values())
		row: dict[str, Any] = {"source": source, "domain": domain, "failed": total}
		for name in FAILURE_CLASSES:
			row[name] = counts.get(name, 0)
		rows.append(row)
	return sorted(rows, key=lambda item: (-int(item["failed"]), str(item["source"]), str(item["domain"])))


def _source_rows(buckets: dict[str, Counter[str]]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for source, counts in buckets.items():
		total = sum(counts.values())
		row: dict[str, Any] = {"source": source, "failed": total}
		for name in FAILURE_CLASSES:
			row[name] = counts.get(name, 0)
		rows.append(row)
	return sorted(rows, key=lambda item: (-int(item["failed"]), str(item["source"])))


def _largest(counter: Counter[str]) -> dict[str, Any]:
	if not counter:
		return {}
	name, count = max(counter.items(), key=lambda item: (item[1], item[0]))
	return {
		"failure_class": name,
		"count": count,
		"investigation_lead": count > 5,
	}


def _verdict(largest: dict[str, Any], failures: int) -> str:
	if largest.get("failure_class") == "truncation" and int(largest.get("count") or 0) > 5:
		return (
			f"materially diverged at evaluation termination/control: {largest['count']}/{failures} "
			"failures reached the 16000-token generation ceiling, so the 73/92 baseline is dominated "
			"by hard-budget truncation rather than finished wrong answers."
		)
	return (
		"consistent with a direct quality gap after accounting for token-budget artifacts: no single "
		"budget/format/refusal class dominates the failures."
	)


def analyze(args: argparse.Namespace) -> dict[str, Any]:
	jsonl_path = Path(args.jsonl)
	stdout_path = Path(args.stdout) if args.stdout else None
	records, summary = _load_jsonl(jsonl_path)
	report = _parse_stdout_report(stdout_path)
	max_tokens = int(args.max_tokens or 0)
	if max_tokens <= 0:
		max_tokens = max(int(row.get("generated_tokens") or 0) for row in records)
	failures: list[dict[str, Any]] = []
	class_counts: Counter[str] = Counter()
	domain_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
	source_counts: dict[str, Counter[str]] = defaultdict(Counter)
	for row in records:
		if row.get("ds4_eval_status") != "FAILED" and row.get("passed") is not False:
			continue
		case_index = int(row.get("case_index") or 0)
		report_row = report.get(case_index, {})
		failure_class, evidence = _classify_failure(row, report_row, max_tokens)
		class_counts[failure_class] += 1
		source = str(row.get("source") or report_row.get("source") or "")
		domain = str(row.get("domain") or "")
		domain_counts[(source, domain)][failure_class] += 1
		source_counts[source][failure_class] += 1
		failures.append({
			"case_index": case_index,
			"case_id": row.get("case_id"),
			"source": source,
			"domain": domain,
			"failure_class": failure_class,
			"evidence": evidence,
			"expected_answer": row.get("expected_answer"),
			"observed_answer": row.get("observed_answer"),
			"generated_tokens": int(report_row.get("generated_tokens") or row.get("generated_tokens") or 0),
			"elapsed_sec": float(row.get("elapsed_sec") or 0.0),
			"stdout_report_line": report_row.get("raw_report_line", ""),
		})
	largest = _largest(class_counts)
	return {
		"format": FORMAT,
		"run_id": args.run_id or summary.get("run_id") or "",
		"source_jsonl": str(jsonl_path),
		"source_stdout": str(stdout_path) if stdout_path else "",
		"question_count": int(summary.get("question_count") or len(records)),
		"passed": int(summary.get("passed") or 0),
		"failed": len(failures),
		"pass_rate": int(summary.get("passed") or 0) / len(records),
		"aggregate_output_tokens_per_s": summary.get("aggregate_output_tokens_per_s"),
		"max_tokens": max_tokens,
		"failure_class_breakdown": _counter_rows(class_counts, "failure_class"),
		"source_breakdown": _source_rows(source_counts),
		"domain_breakdown": _domain_rows(domain_counts),
		"largest_failure_class": largest,
		"verdict": _verdict(largest, len(failures)),
		"failures": failures,
	}


def build_parser() -> argparse.ArgumentParser:
	ap = argparse.ArgumentParser()
	ap.add_argument("--jsonl", default=str(DEFAULT_JSONL))
	ap.add_argument("--stdout", default=str(DEFAULT_STDOUT))
	ap.add_argument("--out", default=str(DEFAULT_OUT))
	ap.add_argument("--run-id", default=DEFAULT_RUN_ID)
	ap.add_argument("--max-tokens", type=int, default=0)
	return ap


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	result = analyze(args)
	out = Path(args.out)
	out.parent.mkdir(parents=True, exist_ok=True)
	out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	print(json.dumps({
		"run_id": result["run_id"],
		"question_count": result["question_count"],
		"passed": result["passed"],
		"failed": result["failed"],
		"failure_class_breakdown": result["failure_class_breakdown"],
		"largest_failure_class": result["largest_failure_class"],
		"verdict": result["verdict"],
		"out": str(out),
	}, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
