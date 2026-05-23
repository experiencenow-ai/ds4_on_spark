#!/usr/bin/env python3
"""Compare two pipeline-quality-regression JSONL runs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


FORMAT = "pipeline-quality-comparison-v1"


def load_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
	rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
	questions = [row for row in rows if row.get("record_type") == "question"]
	summaries = [row for row in rows if row.get("record_type") == "summary"]
	if not summaries:
		raise ValueError(f"summary record missing from {path}")
	return questions, summaries[-1]


def pass_rate(passed: int, total: int) -> float:
	return passed / total if total > 0 else 0.0


def exact_mcnemar_pvalue(baseline_only: int, candidate_only: int) -> float:
	discordant = baseline_only + candidate_only
	if discordant == 0:
		return 1.0
	tail = 0.0
	limit = min(baseline_only, candidate_only)
	for k in range(limit + 1):
		tail += math.comb(discordant, k)
	return min(1.0, (2.0 * tail) / (2 ** discordant))


def domain_key(row: dict[str, Any]) -> tuple[str, str]:
	return str(row.get("source") or ""), str(row.get("domain") or "")


def summarize_by_domain(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, int]]:
	out: dict[tuple[str, str], dict[str, int]] = {}
	for row in rows:
		bucket = out.setdefault(domain_key(row), {"question_count": 0, "passed": 0, "failed": 0})
		bucket["question_count"] += 1
		if row.get("passed") is True:
			bucket["passed"] += 1
		else:
			bucket["failed"] += 1
	return out


def build_comparison(baseline_path: Path, candidate_path: Path, baseline_label: str, candidate_label: str, equivalent_pp: float) -> dict[str, Any]:
	base_rows, base_summary = load_rows(baseline_path)
	cand_rows, cand_summary = load_rows(candidate_path)
	base_by_id = {str(row.get("case_id")): row for row in base_rows}
	cand_by_id = {str(row.get("case_id")): row for row in cand_rows}
	common_ids = sorted(set(base_by_id) & set(cand_by_id))
	if len(common_ids) == 0:
		raise ValueError("no overlapping case_id values")
	baseline_only = 0
	candidate_only = 0
	both_pass = 0
	both_fail = 0
	for case_id in common_ids:
		base_pass = bool(base_by_id[case_id].get("passed"))
		cand_pass = bool(cand_by_id[case_id].get("passed"))
		if base_pass and cand_pass:
			both_pass += 1
		elif base_pass:
			baseline_only += 1
		elif cand_pass:
			candidate_only += 1
		else:
			both_fail += 1
	base_passed = sum(1 for row in base_rows if row.get("passed") is True)
	cand_passed = sum(1 for row in cand_rows if row.get("passed") is True)
	base_total = len(base_rows)
	cand_total = len(cand_rows)
	base_rate = pass_rate(base_passed, base_total)
	cand_rate = pass_rate(cand_passed, cand_total)
	diff_pp = (cand_rate - base_rate) * 100.0
	if abs(diff_pp) <= equivalent_pp:
		verdict = "equivalent"
	elif diff_pp > 0:
		verdict = "better"
	else:
		verdict = "worse"
	p_value = exact_mcnemar_pvalue(baseline_only, candidate_only)
	base_domains = summarize_by_domain(base_rows)
	cand_domains = summarize_by_domain(cand_rows)
	domain_table = []
	for key in sorted(set(base_domains) | set(cand_domains)):
		base = base_domains.get(key, {"question_count": 0, "passed": 0, "failed": 0})
		cand = cand_domains.get(key, {"question_count": 0, "passed": 0, "failed": 0})
		domain_table.append({
			"source": key[0],
			"domain": key[1],
			"baseline_passed": base["passed"],
			"baseline_total": base["question_count"],
			"baseline_pass_rate": pass_rate(base["passed"], base["question_count"]),
			"candidate_passed": cand["passed"],
			"candidate_total": cand["question_count"],
			"candidate_pass_rate": pass_rate(cand["passed"], cand["question_count"]),
		})
	return {
		"format": FORMAT,
		"baseline_label": baseline_label,
		"candidate_label": candidate_label,
		"baseline_path": str(baseline_path),
		"candidate_path": str(candidate_path),
		"baseline_run_id": base_summary.get("run_id", ""),
		"candidate_run_id": cand_summary.get("run_id", ""),
		"baseline_passed": base_passed,
		"baseline_total": base_total,
		"baseline_pass_rate": base_rate,
		"candidate_passed": cand_passed,
		"candidate_total": cand_total,
		"candidate_pass_rate": cand_rate,
		"difference_percentage_points": diff_pp,
		"mcnemar_p_value": p_value,
		"both_pass": both_pass,
		"both_fail": both_fail,
		"baseline_only_pass": baseline_only,
		"candidate_only_pass": candidate_only,
		"verdict": verdict,
		"verdict_line": f"{candidate_label} quality is {verdict} than {baseline_label} by {diff_pp:.2f} percentage points on ds4-eval, p-value {p_value:.6g}.",
		"domain_table": domain_table,
	}


def build_markdown(comparison: dict[str, Any]) -> str:
	lines = [
		"# vLLM MXFP4 TP=2 ds4-eval Comparison",
		"",
		comparison["verdict_line"],
		"",
		"| Run | Pass | Total | Pass rate |",
		"| --- | ---: | ---: | ---: |",
		f"| {comparison['baseline_label']} | {comparison['baseline_passed']} | {comparison['baseline_total']} | {comparison['baseline_pass_rate']:.3f} |",
		f"| {comparison['candidate_label']} | {comparison['candidate_passed']} | {comparison['candidate_total']} | {comparison['candidate_pass_rate']:.3f} |",
		"",
		"| Source | Domain | Baseline | Candidate |",
		"| --- | --- | ---: | ---: |",
	]
	for row in comparison["domain_table"]:
		lines.append(f"| {row['source']} | {row['domain']} | {row['baseline_passed']}/{row['baseline_total']} | {row['candidate_passed']}/{row['candidate_total']} |")
	lines.extend([
		"",
		f"Discordant pairs: baseline-only pass {comparison['baseline_only_pass']}, candidate-only pass {comparison['candidate_only_pass']}.",
	])
	return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
	ap = argparse.ArgumentParser()
	ap.add_argument("--baseline", required=True)
	ap.add_argument("--candidate", required=True)
	ap.add_argument("--baseline-label", default="antirez IQ2XXS PP=1")
	ap.add_argument("--candidate-label", default="vLLM MXFP4 TP=2")
	ap.add_argument("--equivalent-pp", type=float, default=3.0)
	ap.add_argument("--out", required=True)
	ap.add_argument("--markdown-out", default="")
	return ap


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	comparison = build_comparison(Path(args.baseline), Path(args.candidate), args.baseline_label, args.candidate_label, args.equivalent_pp)
	Path(args.out).parent.mkdir(parents=True, exist_ok=True)
	Path(args.out).write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	if args.markdown_out:
		Path(args.markdown_out).parent.mkdir(parents=True, exist_ok=True)
		Path(args.markdown_out).write_text(build_markdown(comparison), encoding="utf-8")
	print(json.dumps(comparison, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
