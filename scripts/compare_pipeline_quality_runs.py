#!/usr/bin/env python3
"""Compare two pipeline-quality-regression JSONL runs."""

from __future__ import annotations

import argparse
import json
import math
import re
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


def answer_marker_present(text: str) -> bool:
	return re.search(r"(?im)\banswer\s*[:：]", text) is not None


def comparison_status(base_pass: bool, cand_pass: bool) -> str:
	if base_pass and cand_pass:
		return "both_pass"
	if base_pass:
		return "baseline_only_pass"
	if cand_pass:
		return "candidate_only_pass"
	return "both_fail"


def row_brief(case_id: str, base: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
	base_pass = bool(base.get("passed"))
	cand_pass = bool(cand.get("passed"))
	return {
		"case_index": cand.get("case_index", base.get("case_index", 0)),
		"case_id": case_id,
		"source": cand.get("source", base.get("source", "")),
		"domain": cand.get("domain", base.get("domain", "")),
		"expected_answer": cand.get("expected_answer", base.get("expected_answer", "")),
		"baseline_passed": base_pass,
		"baseline_observed_answer": base.get("observed_answer", ""),
		"baseline_generated_tokens": int(base.get("generated_tokens") or 0),
		"candidate_passed": cand_pass,
		"candidate_observed_answer": cand.get("observed_answer", ""),
		"candidate_generated_tokens": int(cand.get("generated_tokens") or 0),
		"candidate_answer_marker_present": answer_marker_present(str(cand.get("generated_text") or "")),
		"comparison_status": comparison_status(base_pass, cand_pass),
	}


def length_cap_summary(capped: list[dict[str, Any]]) -> dict[str, Any]:
	without_marker = sum(1 for row in capped if not row["candidate_answer_marker_present"])
	discordant = sum(1 for row in capped if row["comparison_status"] in ("baseline_only_pass", "candidate_only_pass"))
	return {
		"length_capped_count": len(capped),
		"length_capped_passed": sum(1 for row in capped if row["candidate_passed"]),
		"length_capped_without_answer_marker": without_marker,
		"length_capped_discordant_count": discordant,
		"cap_altered_comparison_delta": discordant > 0,
		"verdict": "may_affect_comparison" if discordant > 0 else "no_comparison_delta_but_grading_risk",
	}


def collect_case_outcomes(common_ids: list[str], base_by_id: dict[str, dict[str, Any]], cand_by_id: dict[str, dict[str, Any]], length_cap_tokens: int) -> dict[str, Any]:
	out = {"baseline_only": 0, "candidate_only": 0, "both_pass": 0, "both_fail": 0, "discordant_cases": [], "length_capped_cases": []}
	for case_id in common_ids:
		base = base_by_id[case_id]
		cand = cand_by_id[case_id]
		base_pass = bool(base.get("passed"))
		cand_pass = bool(cand.get("passed"))
		if int(cand.get("generated_tokens") or 0) >= length_cap_tokens:
			out["length_capped_cases"].append(row_brief(case_id, base, cand))
		status = comparison_status(base_pass, cand_pass)
		if status == "both_pass":
			out["both_pass"] += 1
		elif status == "baseline_only_pass":
			out["baseline_only"] += 1
			out["discordant_cases"].append(row_brief(case_id, base, cand))
		elif status == "candidate_only_pass":
			out["candidate_only"] += 1
			out["discordant_cases"].append(row_brief(case_id, base, cand))
		else:
			out["both_fail"] += 1
	return out


def quality_verdict(diff_pp: float, equivalent_pp: float) -> str:
	if abs(diff_pp) <= equivalent_pp:
		return "equivalent"
	return "better" if diff_pp > 0 else "worse"


def build_domain_table(base_rows: list[dict[str, Any]], cand_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	base_domains = summarize_by_domain(base_rows)
	cand_domains = summarize_by_domain(cand_rows)
	rows = []
	for key in sorted(set(base_domains) | set(cand_domains)):
		base = base_domains.get(key, {"question_count": 0, "passed": 0, "failed": 0})
		cand = cand_domains.get(key, {"question_count": 0, "passed": 0, "failed": 0})
		rows.append({
			"source": key[0],
			"domain": key[1],
			"baseline_passed": base["passed"],
			"baseline_total": base["question_count"],
			"baseline_pass_rate": pass_rate(base["passed"], base["question_count"]),
			"candidate_passed": cand["passed"],
			"candidate_total": cand["question_count"],
			"candidate_pass_rate": pass_rate(cand["passed"], cand["question_count"]),
		})
	return rows


def analysis_recommendations() -> list[str]:
	return [
		"Record length_capped and answer_marker_present on future pipeline-quality question rows.",
		"Treat length-capped rows without an explicit Answer: marker as grading-risk cases even when fallback extraction happens to match.",
		"Add a stop policy or answer-line extraction mode before using long max_tokens runs for quality deltas.",
	]


def build_comparison(baseline_path: Path, candidate_path: Path, baseline_label: str, candidate_label: str, equivalent_pp: float, length_cap_tokens: int) -> dict[str, Any]:
	base_rows, base_summary = load_rows(baseline_path)
	cand_rows, cand_summary = load_rows(candidate_path)
	base_by_id = {str(row.get("case_id")): row for row in base_rows}
	cand_by_id = {str(row.get("case_id")): row for row in cand_rows}
	common_ids = sorted(set(base_by_id) & set(cand_by_id))
	if len(common_ids) == 0:
		raise ValueError("no overlapping case_id values")
	outcomes = collect_case_outcomes(common_ids, base_by_id, cand_by_id, length_cap_tokens)
	base_passed = sum(1 for row in base_rows if row.get("passed") is True)
	cand_passed = sum(1 for row in cand_rows if row.get("passed") is True)
	base_total = len(base_rows)
	cand_total = len(cand_rows)
	base_rate = pass_rate(base_passed, base_total)
	cand_rate = pass_rate(cand_passed, cand_total)
	diff_pp = (cand_rate - base_rate) * 100.0
	verdict = quality_verdict(diff_pp, equivalent_pp)
	p_value = exact_mcnemar_pvalue(outcomes["baseline_only"], outcomes["candidate_only"])
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
		"both_pass": outcomes["both_pass"],
		"both_fail": outcomes["both_fail"],
		"baseline_only_pass": outcomes["baseline_only"],
		"candidate_only_pass": outcomes["candidate_only"],
		"discordant_cases": sorted(outcomes["discordant_cases"], key=lambda row: int(row.get("case_index") or 0)),
		"length_cap_tokens": length_cap_tokens,
		"length_cap_summary": length_cap_summary(outcomes["length_capped_cases"]),
		"length_capped_cases": sorted(outcomes["length_capped_cases"], key=lambda row: int(row.get("case_index") or 0)),
		"recommendations": analysis_recommendations(),
		"verdict": verdict,
		"verdict_line": f"{candidate_label} quality is {verdict} than {baseline_label} by {diff_pp:.2f} percentage points on ds4-eval, p-value {p_value:.6g}.",
		"domain_table": build_domain_table(base_rows, cand_rows),
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
		"",
		"## Discordant Cases",
		"",
		"| # | Case | Source | Domain | Baseline | Candidate |",
		"| ---: | --- | --- | --- | --- | --- |",
	])
	for row in comparison.get("discordant_cases", []):
		lines.append(f"| {row['case_index']} | {row['case_id']} | {row['source']} | {row['domain']} | {row['baseline_observed_answer']} ({'pass' if row['baseline_passed'] else 'fail'}) | {row['candidate_observed_answer']} ({'pass' if row['candidate_passed'] else 'fail'}) |")
	cap = comparison["length_cap_summary"]
	lines.extend([
		"",
		"## Length Cap Review",
		"",
		f"Candidate rows at the {comparison['length_cap_tokens']}-token cap: {cap['length_capped_count']}.",
		f"Capped rows without an explicit `Answer:` marker: {cap['length_capped_without_answer_marker']}.",
		f"Capped rows that changed the baseline/candidate pass delta: {cap['length_capped_discordant_count']}.",
		f"Length-cap verdict: `{cap['verdict']}`.",
		"",
		"| # | Case | Status | Observed | Expected | Answer marker |",
		"| ---: | --- | --- | --- | --- | --- |",
	])
	for row in comparison.get("length_capped_cases", []):
		lines.append(f"| {row['case_index']} | {row['case_id']} | {row['comparison_status']} | {row['candidate_observed_answer']} | {row['expected_answer']} | {row['candidate_answer_marker_present']} |")
	lines.extend(["", "Recommendations:"])
	for item in comparison.get("recommendations", []):
		lines.append(f"- {item}")
	return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
	ap = argparse.ArgumentParser()
	ap.add_argument("--baseline", required=True)
	ap.add_argument("--candidate", required=True)
	ap.add_argument("--baseline-label", default="antirez IQ2XXS PP=1")
	ap.add_argument("--candidate-label", default="vLLM MXFP4 TP=2")
	ap.add_argument("--equivalent-pp", type=float, default=3.0)
	ap.add_argument("--length-cap-tokens", type=int, default=16000)
	ap.add_argument("--out", required=True)
	ap.add_argument("--markdown-out", default="")
	return ap


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	comparison = build_comparison(Path(args.baseline), Path(args.candidate), args.baseline_label, args.candidate_label, args.equivalent_pp, args.length_cap_tokens)
	Path(args.out).parent.mkdir(parents=True, exist_ok=True)
	Path(args.out).write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
	if args.markdown_out:
		Path(args.markdown_out).parent.mkdir(parents=True, exist_ok=True)
		Path(args.markdown_out).write_text(build_markdown(comparison), encoding="utf-8")
	print(json.dumps(comparison, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
