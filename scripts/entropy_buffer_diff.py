#!/usr/bin/env python3
"""Diff entropy-buffer metrics between two JSONL corpora deterministically."""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

try:
    from scripts import entropy_buffer_lib as lib
    from scripts import entropy_buffer_metrics as metrics
except ModuleNotFoundError:
    import entropy_buffer_lib as lib
    import entropy_buffer_metrics as metrics


Number = Union[int, float]


DEFAULT_KEY_PATHS = [
    "totals.records_total",
    "totals.task_run_records",
    "totals.judge_pair_records",
    "totals.unknown_records",
    "diversity.task_id.unique",
    "diversity.task_id.entropy_norm",
    "diversity.task_id.hhi",
    "diversity.task_family.unique",
    "diversity.task_family.entropy_norm",
    "diversity.task_family.hhi",
    "diversity.prompt_template_id.unique",
    "diversity.prompt_template_id.entropy_norm",
    "diversity.prompt_template_id.hhi",
    "diversity.task_family_template_pair.unique",
    "diversity.task_family_template_pair.entropy_norm",
    "diversity.task_family_template_pair.hhi",
    "diversity.task_id_template_pair.unique",
    "diversity.task_id_template_pair.entropy_norm",
    "diversity.model_id.unique",
    "duplicates.output_norm_dup_rate",
    "duplicates.output_exact_dup_rate",
    "duplicates.prompt_norm_dup_rate",
    "duplicates.answer_dup_rate",
    "duplicates.task_template_groups_ge2",
    "reuse.buffer_item_reuse_event_rate",
    "reuse.buffer_item_hhi",
    "reuse.buffer_id_hhi",
    "useful_novelty.flagged_task_run_rate",
    "useful_coverage.clean_task_run_rate",
    "useful_coverage.diversity.task_family.entropy_norm",
    "judge.label_balance_ab",
    "judge.disagreement_rate",
    "judge.disagreement_rate_decided_ab",
    "judge.judge_id_disagreement_vs_majority_rate_max",
    "judge.judge_id_disagreement_vs_majority_rate_decided_ab_max",
    "judge.invalid_rate",
    "judge.tie_rate",
    "tokens.prompt_word_entropy_bits",
    "tokens.output_word_entropy_bits",
    "tokens.output_distinct_1",
    "tokens.output_char_3gram_entropy_bits",
]


def _is_num(v: Any) -> bool:
    if isinstance(v, bool):
        return(False)
    return(isinstance(v, (int, float)))


def _as_float(v: Any) -> Optional[float]:
    if not _is_num(v):
        return(None)
    x = float(v)
    if not math.isfinite(x):
        return(None)
    return(x)


def _get_path(obj: Dict[str, Any], path: str) -> Optional[float]:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return(None)
        if part not in cur:
            return(None)
        cur = cur.get(part)
    return(_as_float(cur))


def _flatten_scalars(obj: Any, prefix: str, out: Dict[str, float]) -> None:
    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            p = key if prefix == "" else f"{prefix}.{key}"
            _flatten_scalars(obj.get(key), p, out)
        return
    x = _as_float(obj)
    if x is None:
        return
    out[prefix] = x


def _diff_paths(before: Dict[str, Any], after: Dict[str, Any], paths: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in sorted(set(paths)):
        b = _get_path(before, path)
        a = _get_path(after, path)
        if b is None and a is None:
            continue
        d = None if (b is None or a is None) else (a - b)
        out.append({"path": path, "before": b, "after": a, "delta": d})
    out.sort(key=lambda x: str(x.get("path", "")))
    return(out)


def _diff_all_scalars(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    bflat: Dict[str, float] = {}
    aflat: Dict[str, float] = {}
    _flatten_scalars(before, "", bflat)
    _flatten_scalars(after, "", aflat)

    out: List[Dict[str, Any]] = []
    for path in sorted(set(bflat.keys()) | set(aflat.keys())):
        b = bflat.get(path, None)
        a = aflat.get(path, None)
        d = None if (b is None or a is None) else (a - b)
        out.append({"path": path, "before": b, "after": a, "delta": d})
    return(out)


def _report_dict(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    report = metrics.summarize(records)
    return({
        "totals": report.totals,
        "runs": report.runs,
        "diversity": report.diversity,
        "tokens": report.tokens,
        "duplicates": report.duplicates,
        "judge": report.judge,
        "reuse": report.reuse,
        "useful_novelty": report.useful_novelty,
        "useful_coverage": report.useful_coverage,
    })


def _fmt_num(v: Any) -> str:
    if v is None:
        return("n/a")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return(f"{float(v):.6f}")
    return(str(v))


def to_markdown_diff(diff: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("# Entropy buffer metric diff")
    lines.append("")
    lines.append("| metric | before | after | delta |")
    lines.append("|---|---:|---:|---:|")
    for row in diff:
        path = str(row.get("path", ""))
        b = row.get("before", None)
        a = row.get("after", None)
        d = row.get("delta", None)
        lines.append(f"| `{path}` | {_fmt_num(b)} | {_fmt_num(a)} | {_fmt_num(d)} |")
    lines.append("")
    return("\n".join(lines))


def _write_text(path: str, text: str) -> None:
    f = open(path, "w", encoding="utf-8")
    try:
        f.write(text)
    finally:
        f.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Diff entropy-buffer metrics between two JSONL corpora.")
    p.add_argument("--before-jsonl", action="append", default=[], help="Before corpus JSONL path (repeatable).")
    p.add_argument("--after-jsonl", action="append", default=[], help="After corpus JSONL path (repeatable).")
    p.add_argument("--metric-path", action="append", default=[], help="Extra metric path to diff (dot-separated).")
    p.add_argument("--all-scalars", action="store_true", help="Diff all numeric scalar leaf values (large).")
    p.add_argument("--out-json", type=str, default="", help="Write JSON diff report to this path.")
    p.add_argument("--out-md", type=str, default="", help="Write Markdown diff to this path.")
    p.add_argument("--json", action="store_true", help="Print JSON diff report to stdout.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if len(args.before_jsonl) == 0:
        raise SystemExit("--before-jsonl is required (repeatable)")
    if len(args.after_jsonl) == 0:
        raise SystemExit("--after-jsonl is required (repeatable)")

    before = _report_dict(lib.load_jsonl(args.before_jsonl))
    after = _report_dict(lib.load_jsonl(args.after_jsonl))

    if args.all_scalars:
        diff = _diff_all_scalars(before, after)
    else:
        paths = list(DEFAULT_KEY_PATHS)
        paths.extend([str(x) for x in (args.metric_path or []) if str(x).strip() != ""])
        diff = _diff_paths(before, after, paths)

    out = {
        "meta": {
            "before_paths": list(args.before_jsonl),
            "after_paths": list(args.after_jsonl),
            "all_scalars": bool(args.all_scalars),
            "default_key_paths": list(DEFAULT_KEY_PATHS),
        },
        "before": before,
        "after": after,
        "diff": diff,
    }

    if args.out_json != "":
        _write_text(args.out_json, json.dumps(out, indent=2, sort_keys=True) + "\n")
    if args.out_md != "":
        _write_text(args.out_md, to_markdown_diff(diff))
    if args.json:
        sys.stdout.write(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
