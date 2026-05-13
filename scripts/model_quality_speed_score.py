#!/usr/bin/env python3
"""Score model quality/speed tradeoffs from baseline CSV rows."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass
class ScoreRow:
    raw: Dict[str, str]
    model: str
    run_id: str
    scope: str
    quality_score: Optional[float]
    quality_source: str
    public_quality_prior: Optional[float]
    public_quality_basis: str
    public_quality_source: str
    local_quality_score: Optional[float]
    decode_tps: Optional[float]
    prefill_tps: Optional[float]
    ttft_s: Optional[float]
    total_wall_s: Optional[float]
    output_tokens: Optional[float]
    total_tasks: Optional[float]
    passed_tasks: Optional[float]
    correct_task_rate: Optional[float]
    correct_tasks_per_s: Optional[float]
    quality_adjusted_decode_tps: Optional[float]
    quality_adjusted_prefill_tps: Optional[float]
    tokens_per_success: Optional[float]
    wall_s_per_success: Optional[float]
    speculative_method: str
    speculative_draft_model: str
    speculative_num_speculative_tokens: Optional[float]
    spec_decode_num_drafts: Optional[float]
    spec_decode_num_draft_tokens: Optional[float]
    spec_decode_num_accepted_tokens: Optional[float]
    spec_decode_mean_accept_len: Optional[float]
    spec_decode_accept_rate: Optional[float]
    dominated_by: str = ""


def _get(row: Dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name].strip() != "":
            return(row[name].strip())
    return("")


def _float(row: Dict[str, str], *names: str) -> Optional[float]:
    s = _get(row, *names)
    if s == "":
        return(None)
    try:
        v = float(s)
    except ValueError as e:
        raise ValueError(f"invalid float for {names[0]}: {s}") from e
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"non-finite float for {names[0]}: {s}")
    return(v)


def _clamp_score(v: Optional[float], field: str) -> Optional[float]:
    if v is None:
        return(None)
    if v < 0.0 or v > 100.0:
        raise ValueError(f"{field} must be in [0,100], got {v}")
    return(v)


def _ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den <= 0.0:
        return(None)
    return(num / den)


def _quality(row: Dict[str, str]) -> tuple[Optional[float], str, Optional[float], Optional[float]]:
    explicit = _clamp_score(_float(row, "quality_score"), "quality_score")
    public_prior = _clamp_score(_float(row, "public_quality_prior", "public_prior"), "public_quality_prior")
    local_score = _clamp_score(_float(row, "local_quality_score", "local_score"), "local_quality_score")
    passed = _float(row, "passed_tasks", "local_passed")
    total = _float(row, "total_tasks", "local_total")
    if local_score is None and passed is not None and total is not None and total > 0.0:
        local_score = _clamp_score((100.0 * passed / total), "local_quality_score")
    if explicit is not None:
        return(explicit, "explicit", public_prior, local_score)
    if local_score is not None and public_prior is not None:
        return(((0.70 * local_score) + (0.30 * public_prior)), "local70_public30", public_prior, local_score)
    if local_score is not None:
        return(local_score, "local_only", public_prior, local_score)
    if public_prior is not None:
        return(public_prior, "public_prior_only", public_prior, local_score)
    return(None, "missing", public_prior, local_score)


def score_rows(
    rows: Iterable[Dict[str, str]],
    speed_field: str = "decode_tps",
    pareto_group: str = "scope",
) -> List[ScoreRow]:
    scored: List[ScoreRow] = []
    for idx, row in enumerate(rows):
        model = _get(row, "model", "model_id", "target")
        if model == "":
            raise ValueError(f"row {idx + 1}: model is required")
        run_id = _get(row, "run_id", "run", "variant")
        scope = _get(row, "scope")
        quality_score, quality_source, public_prior, local_score = _quality(row)
        public_quality_basis = _get(row, "public_quality_basis", "public_basis")
        public_quality_source = _get(row, "public_quality_source", "public_source")
        decode_tps = _float(row, "decode_tps", "generation_tps", "output_tps")
        prefill_tps = _float(row, "prefill_tps", "prompt_tps")
        ttft_s = _float(row, "ttft_s", "ttft_first_output_s")
        total_wall_s = _float(row, "total_wall_s", "wall_s", "generate_wall_s")
        output_tokens = _float(row, "output_tokens", "generated_tokens")
        total_tasks = _float(row, "total_tasks", "local_total")
        passed_tasks = _float(row, "passed_tasks", "local_passed")
        correct_task_rate = _ratio(passed_tasks, total_tasks)
        correct_tasks_per_s = _ratio(passed_tasks, total_wall_s)
        qfrac = None if quality_score is None else (quality_score / 100.0)
        qad = None if qfrac is None or decode_tps is None else (qfrac * decode_tps)
        qap = None if qfrac is None or prefill_tps is None else (qfrac * prefill_tps)
        tokens_per_success = _ratio(output_tokens, passed_tasks)
        wall_s_per_success = _ratio(total_wall_s, passed_tasks)
        speculative_method = _get(row, "speculative_method")
        speculative_draft_model = _get(row, "speculative_draft_model")
        speculative_num_speculative_tokens = _float(row, "speculative_num_speculative_tokens")
        spec_decode_num_drafts = _float(row, "spec_decode_num_drafts")
        spec_decode_num_draft_tokens = _float(row, "spec_decode_num_draft_tokens")
        spec_decode_num_accepted_tokens = _float(row, "spec_decode_num_accepted_tokens")
        spec_decode_mean_accept_len = _float(row, "spec_decode_mean_accept_len")
        spec_decode_accept_rate = _float(row, "spec_decode_accept_rate")
        scored.append(ScoreRow(
            raw=dict(row),
            model=model,
            run_id=run_id,
            scope=scope,
            quality_score=quality_score,
            quality_source=quality_source,
            public_quality_prior=public_prior,
            public_quality_basis=public_quality_basis,
            public_quality_source=public_quality_source,
            local_quality_score=local_score,
            decode_tps=decode_tps,
            prefill_tps=prefill_tps,
            ttft_s=ttft_s,
            total_wall_s=total_wall_s,
            output_tokens=output_tokens,
            total_tasks=total_tasks,
            passed_tasks=passed_tasks,
            correct_task_rate=correct_task_rate,
            correct_tasks_per_s=correct_tasks_per_s,
            quality_adjusted_decode_tps=qad,
            quality_adjusted_prefill_tps=qap,
            tokens_per_success=tokens_per_success,
            wall_s_per_success=wall_s_per_success,
            speculative_method=speculative_method,
            speculative_draft_model=speculative_draft_model,
            speculative_num_speculative_tokens=speculative_num_speculative_tokens,
            spec_decode_num_drafts=spec_decode_num_drafts,
            spec_decode_num_draft_tokens=spec_decode_num_draft_tokens,
            spec_decode_num_accepted_tokens=spec_decode_num_accepted_tokens,
            spec_decode_mean_accept_len=spec_decode_mean_accept_len,
            spec_decode_accept_rate=spec_decode_accept_rate,
        ))
    mark_pareto(scored, speed_field, pareto_group)
    return(scored)


def _value(row: ScoreRow, field: str) -> Optional[float]:
    if not hasattr(row, field):
        raise ValueError(f"unknown speed field: {field}")
    v = getattr(row, field)
    if v is None:
        return(None)
    return(float(v))


def _mark_pareto_group(rows: Sequence[ScoreRow], speed_field: str) -> None:
    for row in rows:
        row.dominated_by = ""
    for i, row in enumerate(rows):
        q = row.quality_score
        s = _value(row, speed_field)
        if q is None or s is None:
            continue
        for j, other in enumerate(rows):
            if i == j:
                continue
            oq = other.quality_score
            os = _value(other, speed_field)
            if oq is None or os is None:
                continue
            if oq >= q and os >= s and (oq > q or os > s):
                row.dominated_by = other.model if other.run_id == "" else f"{other.model}/{other.run_id}"
                break


def mark_pareto(rows: Sequence[ScoreRow], speed_field: str, pareto_group: str = "scope") -> None:
    if pareto_group not in ("all", "scope"):
        raise ValueError(f"invalid pareto_group: {pareto_group}")
    if pareto_group == "all":
        _mark_pareto_group(rows, speed_field)
        return
    groups: Dict[str, List[ScoreRow]] = defaultdict(list)
    for row in rows:
        key = row.scope.strip() if row.scope is not None else ""
        groups[key].append(row)
    for _, g in groups.items():
        _mark_pareto_group(g, speed_field)


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return("")
    if abs(v) >= 1000.0:
        return(f"{v:.1f}")
    if abs(v) >= 10.0:
        return(f"{v:.2f}")
    return(f"{v:.4f}")


def rows_to_dicts(rows: Sequence[ScoreRow]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        d = {
            "model": row.model,
            "run_id": row.run_id,
            "scope": row.scope,
            "quality_score": row.quality_score,
            "quality_source": row.quality_source,
            "public_quality_prior": row.public_quality_prior,
            "public_quality_basis": row.public_quality_basis,
            "public_quality_source": row.public_quality_source,
            "local_quality_score": row.local_quality_score,
            "decode_tps": row.decode_tps,
            "prefill_tps": row.prefill_tps,
            "ttft_s": row.ttft_s,
            "total_wall_s": row.total_wall_s,
            "output_tokens": row.output_tokens,
            "passed_tasks": row.passed_tasks,
            "total_tasks": row.total_tasks,
            "correct_task_rate": row.correct_task_rate,
            "correct_tasks_per_s": row.correct_tasks_per_s,
            "quality_adjusted_decode_tps": row.quality_adjusted_decode_tps,
            "quality_adjusted_prefill_tps": row.quality_adjusted_prefill_tps,
            "tokens_per_success": row.tokens_per_success,
            "wall_s_per_success": row.wall_s_per_success,
            "speculative_method": row.speculative_method,
            "speculative_draft_model": row.speculative_draft_model,
            "speculative_num_speculative_tokens": row.speculative_num_speculative_tokens,
            "spec_decode_num_drafts": row.spec_decode_num_drafts,
            "spec_decode_num_draft_tokens": row.spec_decode_num_draft_tokens,
            "spec_decode_num_accepted_tokens": row.spec_decode_num_accepted_tokens,
            "spec_decode_mean_accept_len": row.spec_decode_mean_accept_len,
            "spec_decode_accept_rate": row.spec_decode_accept_rate,
            "dominated_by": row.dominated_by,
        }
        out.append(d)
    return(out)


def print_markdown(rows: Sequence[ScoreRow]) -> None:
    ordered = sorted(rows, key=lambda r: (r.quality_adjusted_decode_tps is not None, r.quality_adjusted_decode_tps or -1.0), reverse=True)
    print("| model | run | scope | quality | source | passed/total | decode t/s | wall s | out tok | quality-adjusted t/s | correct rate | tasks/s | tokens/success | Pareto |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in ordered:
        pareto = "yes" if row.dominated_by == "" and row.quality_score is not None else f"no: {row.dominated_by}"
        passed_total = ""
        if row.passed_tasks is not None and row.total_tasks is not None:
            passed_total = f"{int(row.passed_tasks)}/{int(row.total_tasks)}"
        print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row.model,
            row.run_id,
            row.scope,
            _fmt(row.quality_score),
            row.quality_source,
            passed_total,
            _fmt(row.decode_tps),
            _fmt(row.total_wall_s),
            _fmt(row.output_tokens),
            _fmt(row.quality_adjusted_decode_tps),
            _fmt(row.correct_task_rate),
            _fmt(row.correct_tasks_per_s),
            _fmt(row.tokens_per_success),
            pareto,
        ))


def read_csv(path: str) -> List[Dict[str, str]]:
    if path == "-":
        return(list(csv.DictReader(sys.stdin)))
    with open(path, "r", encoding="utf-8", newline="") as f:
        return(list(csv.DictReader(f)))


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Score model quality/speed tradeoffs from a baseline CSV.")
    p.add_argument("csv_path", help="CSV path, or '-' for stdin")
    p.add_argument("--speed-field", default="decode_tps", choices=("decode_tps", "prefill_tps", "correct_task_rate", "correct_tasks_per_s", "quality_adjusted_decode_tps", "quality_adjusted_prefill_tps"))
    p.add_argument("--pareto-group", default="scope", choices=("scope", "all"), help="Compute Pareto frontier within scope groups (default) or globally across all rows.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    args = p.parse_args(argv)
    rows = score_rows(read_csv(args.csv_path), args.speed_field, pareto_group=args.pareto_group)
    if args.json:
        print(json.dumps(rows_to_dicts(rows), indent=2, sort_keys=True))
    else:
        print_markdown(rows)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
