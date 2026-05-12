#!/usr/bin/env python3
"""Suggest entropy-buffer coverage gaps / next-batch targets from history JSONL deterministically."""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from scripts import entropy_buffer_lib as lib
except ModuleNotFoundError:
    import entropy_buffer_lib as lib


def _entropy_norm_bits(counts: Dict[str, int]) -> float:
    uniq = len(counts)
    if uniq <= 1:
        return(0.0)
    h = lib.shannon_entropy(counts)
    if h <= 0.0:
        return(0.0)
    return(h / math.log2(float(uniq)))


def _low_count_top(counts: Dict[str, int], key_name: str, max_count: int, k: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, c in counts.items():
        if key == "":
            continue
        if int(c) <= int(max_count):
            out.append({key_name: key, "count": int(c)})
    out.sort(key=lambda x: (int(x.get("count", 0)), str(x.get(key_name, ""))))
    return(out[:k])


def _missing_templates_by_family(family_templates: Dict[str, Dict[str, int]], all_templates: Sequence[str], min_family_count: int, limit: int, k: int) -> List[Dict[str, Any]]:
    tmpl_set = {t for t in all_templates if t != ""}
    out: List[Dict[str, Any]] = []
    for fam in sorted(family_templates.keys()):
        tmpl_counts = family_templates.get(fam) or {}
        total = int(sum(tmpl_counts.values()))
        if total < int(min_family_count):
            continue
        used = {t for t in tmpl_counts.keys() if t != ""}
        missing = sorted(tmpl_set - used)
        if len(missing) == 0:
            continue
        out.append({
            "task_family": fam,
            "count": total,
            "missing_template_count": len(missing),
            "missing_prompt_template_id": missing[:max(0, int(limit))],
        })
    out.sort(key=lambda x: (-int(x.get("missing_template_count", 0)), -int(x.get("count", 0)), str(x.get("task_family", ""))))
    return(out[:k])


def _template_entropy_by_family(family_templates: Dict[str, Dict[str, int]], min_family_count: int, k: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for fam in sorted(family_templates.keys()):
        tmpl_counts = family_templates.get(fam) or {}
        total = int(sum(tmpl_counts.values()))
        if total < int(min_family_count):
            continue
        uniq = len([t for t in tmpl_counts.keys() if t != ""])
        ent_norm = _entropy_norm_bits(tmpl_counts)
        out.append({
            "task_family": fam,
            "count": total,
            "prompt_template_id_unique": uniq,
            "entropy_norm": ent_norm,
            "prompt_template_id_top": lib.top_counts(tmpl_counts, k=5),
        })
    out.sort(key=lambda x: (float(x.get("entropy_norm", 0.0)), -int(x.get("count", 0)), str(x.get("task_family", ""))))
    return(out[:k])


def summarize(records: Sequence[Dict[str, Any]], low_count_max: int = 1, min_family_count: int = 3, top_k: int = 10, missing_template_limit: int = 8) -> Dict[str, Any]:
    canon = [lib.canonicalize_record(x) for x in records]
    task_runs = [c for c in canon if c.rtype == "task_run"]
    judge_pairs = [c for c in canon if c.rtype == "judge_pair"]

    task_family_counts: Dict[str, int] = {}
    template_counts: Dict[str, int] = {}
    pair_counts: Dict[str, int] = {}
    task_template_counts: Dict[str, int] = {}
    model_counts: Dict[str, int] = {}
    answer_counts: Dict[str, int] = {}
    answer_letter_counts: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    buffer_id_counts: Dict[str, int] = {}
    buffer_item_id_counts: Dict[str, int] = {}

    family_templates: Dict[str, Dict[str, int]] = {}

    for c in task_runs:
        if c.task_family != "":
            task_family_counts[c.task_family] = task_family_counts.get(c.task_family, 0) + 1
        if c.prompt_template_id != "":
            template_counts[c.prompt_template_id] = template_counts.get(c.prompt_template_id, 0) + 1
        if c.task_family != "" and c.prompt_template_id != "":
            k = f"{c.task_family}|{c.prompt_template_id}"
            pair_counts[k] = pair_counts.get(k, 0) + 1
            family_templates.setdefault(c.task_family, {})
            ft = family_templates[c.task_family]
            ft[c.prompt_template_id] = ft.get(c.prompt_template_id, 0) + 1
        if c.task_id != "" and c.prompt_template_id != "":
            k = f"{c.task_id}|{c.prompt_template_id}"
            task_template_counts[k] = task_template_counts.get(k, 0) + 1
        if c.model_id != "":
            model_counts[c.model_id] = model_counts.get(c.model_id, 0) + 1
        if c.answer != "":
            answer_counts[c.answer] = answer_counts.get(c.answer, 0) + 1
            letter = lib.answer_letter(c.answer)
            if letter != "":
                answer_letter_counts[letter] = answer_letter_counts.get(letter, 0) + 1
        for tag in lib.get_list(c.raw, "tags", "tag"):
            if tag != "":
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if c.buffer_id != "":
            buffer_id_counts[c.buffer_id] = buffer_id_counts.get(c.buffer_id, 0) + 1
        if c.buffer_item_id != "":
            buffer_item_id_counts[c.buffer_item_id] = buffer_item_id_counts.get(c.buffer_item_id, 0) + 1

    judge_pair_counts: Dict[str, int] = {}
    judge_pair_family_template_counts: Dict[str, int] = {}
    for c in judge_pairs:
        if c.a_model_id != "" or c.b_model_id != "":
            key = f"{c.a_model_id}|{c.b_model_id}"
            judge_pair_counts[key] = judge_pair_counts.get(key, 0) + 1
        if c.task_family != "" and c.prompt_template_id != "":
            key = f"{c.task_family}|{c.prompt_template_id}"
            judge_pair_family_template_counts[key] = judge_pair_family_template_counts.get(key, 0) + 1

    templates_all = sorted(template_counts.keys())
    out = {
        "totals": {
            "records_total": len(records),
            "task_run_records": len(task_runs),
            "judge_pair_records": len(judge_pairs),
        },
        "task_run": {
            "low_count_max": int(low_count_max),
            "min_family_count": int(min_family_count),
            "underrepresented_task_family_top": _low_count_top(task_family_counts, "task_family", low_count_max, top_k),
            "underrepresented_prompt_template_id_top": _low_count_top(template_counts, "prompt_template_id", low_count_max, top_k),
            "underrepresented_task_family_template_pair_top": _low_count_top(pair_counts, "task_family_template_pair", low_count_max, top_k),
            "underrepresented_task_id_template_pair_top": _low_count_top(task_template_counts, "task_id_template_pair", low_count_max, top_k),
            "underrepresented_model_id_top": _low_count_top(model_counts, "model_id", low_count_max, top_k),
            "underrepresented_answer_top": _low_count_top(answer_counts, "answer", low_count_max, top_k),
            "underrepresented_answer_letter_top": _low_count_top(answer_letter_counts, "answer_letter", low_count_max, top_k),
            "underrepresented_tags_top": _low_count_top(tag_counts, "tag", low_count_max, top_k),
            "underrepresented_buffer_id_top": _low_count_top(buffer_id_counts, "buffer_id", low_count_max, top_k),
            "underrepresented_buffer_item_id_top": _low_count_top(buffer_item_id_counts, "buffer_item_id", low_count_max, top_k),
            "families_low_template_entropy_norm_top": _template_entropy_by_family(family_templates, min_family_count=min_family_count, k=top_k),
            "families_missing_prompt_template_id_top": _missing_templates_by_family(family_templates, templates_all, min_family_count=min_family_count, limit=missing_template_limit, k=top_k),
        },
        "judge_pair": {
            "underrepresented_model_pair_top": _low_count_top(judge_pair_counts, "model_pair", low_count_max, top_k),
            "underrepresented_task_family_template_pair_top": _low_count_top(judge_pair_family_template_counts, "task_family_template_pair", low_count_max, top_k),
        },
    }
    return(out)


def _md_list(items: Sequence[Dict[str, Any]], key_name: str) -> str:
    lines: List[str] = []
    for js in items:
        key = str(js.get(key_name, ""))
        if key == "":
            continue
        c = int(js.get("count", 0) or 0)
        lines.append(f"- `{key}`: {c}")
    if len(lines) == 0:
        return("")
    return("\n".join(lines))


def _md_families_missing(items: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for js in items:
        fam = str(js.get("task_family", ""))
        if fam == "":
            continue
        miss = js.get("missing_prompt_template_id") or []
        lines.append(f"- `{fam}`: missing={int(js.get('missing_template_count', 0))} examples={miss}")
    if len(lines) == 0:
        return("")
    return("\n".join(lines))


def _md_families_entropy(items: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for js in items:
        fam = str(js.get("task_family", ""))
        if fam == "":
            continue
        cnt = int(js.get("count", 0) or 0)
        uniq = int(js.get("prompt_template_id_unique", 0) or 0)
        ent = float(js.get("entropy_norm", 0.0) or 0.0)
        tops = js.get("prompt_template_id_top") or []
        lines.append(f"- `{fam}`: count={cnt} tmpl_unique={uniq} entropy_norm={ent:.6f} tops={tops}")
    if len(lines) == 0:
        return("")
    return("\n".join(lines))


def _to_md(gaps: Dict[str, Any]) -> str:
    totals = gaps.get("totals") or {}
    tr = gaps.get("task_run") or {}
    jp = gaps.get("judge_pair") or {}

    parts: List[str] = []
    parts.append("# Entropy buffer gaps / next-batch targets\n")
    parts.append("## Totals\n")
    parts.append(f"- records_total: {int(totals.get('records_total', 0))}")
    parts.append(f"- task_run_records: {int(totals.get('task_run_records', 0))}")
    parts.append(f"- judge_pair_records: {int(totals.get('judge_pair_records', 0))}\n")

    parts.append("## Task-run underrepresented (low-count)\n")
    parts.append(_md_list(tr.get("underrepresented_task_family_top", []), "task_family"))
    parts.append(_md_list(tr.get("underrepresented_prompt_template_id_top", []), "prompt_template_id"))
    parts.append(_md_list(tr.get("underrepresented_task_family_template_pair_top", []), "task_family_template_pair"))
    parts.append(_md_list(tr.get("underrepresented_task_id_template_pair_top", []), "task_id_template_pair"))
    parts.append(_md_list(tr.get("underrepresented_model_id_top", []), "model_id"))
    parts.append(_md_list(tr.get("underrepresented_answer_top", []), "answer"))
    parts.append(_md_list(tr.get("underrepresented_answer_letter_top", []), "answer_letter"))
    parts.append(_md_list(tr.get("underrepresented_tags_top", []), "tag"))
    parts.append(_md_list(tr.get("underrepresented_buffer_id_top", []), "buffer_id"))
    parts.append(_md_list(tr.get("underrepresented_buffer_item_id_top", []), "buffer_item_id"))
    parts.append("\n## Families to diversify templates\n")
    parts.append(_md_families_entropy(tr.get("families_low_template_entropy_norm_top", [])))
    parts.append("\n## Families missing templates (relative to seen templates)\n")
    parts.append(_md_families_missing(tr.get("families_missing_prompt_template_id_top", [])))

    parts.append("\n## Judge-pair underrepresented (low-count)\n")
    parts.append(_md_list(jp.get("underrepresented_model_pair_top", []), "model_pair"))
    parts.append(_md_list(jp.get("underrepresented_task_family_template_pair_top", []), "task_family_template_pair"))
    return("\n".join([p for p in parts if p != ""]).strip() + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Suggest entropy-buffer coverage gaps / next-batch targets from history JSONL.")
    p.add_argument("--in-jsonl", action="append", default=[], help="Input JSONL path (repeatable).")
    p.add_argument("--out-json", default="", help="Write gaps report JSON to this path.")
    p.add_argument("--out-md", default="", help="Write gaps report Markdown to this path.")
    p.add_argument("--low-count-max", type=int, default=1, help="Consider items with count <= N as underrepresented.")
    p.add_argument("--min-family-count", type=int, default=3, help="Only score per-family template diversity for families with >= N task-runs.")
    p.add_argument("--top-k", type=int, default=10, help="Number of items to report per list.")
    p.add_argument("--missing-template-limit", type=int, default=8, help="Cap examples for missing template IDs per family.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if len(args.in_jsonl) == 0:
        raise SystemExit("--in-jsonl is required (repeatable)")

    records = lib.load_jsonl(args.in_jsonl)
    gaps = summarize(
        records,
        low_count_max=max(0, int(args.low_count_max)),
        min_family_count=max(0, int(args.min_family_count)),
        top_k=max(1, int(args.top_k)),
        missing_template_limit=max(0, int(args.missing_template_limit)),
    )

    s = json.dumps(gaps, indent=2, sort_keys=True)
    if args.out_json != "":
        f = open(args.out_json, "w", encoding="utf-8")
        try:
            f.write(s + "\n")
        finally:
            f.close()
    else:
        sys.stdout.write(s + "\n")

    if args.out_md != "":
        md = _to_md(gaps)
        f = open(args.out_md, "w", encoding="utf-8")
        try:
            f.write(md)
        finally:
            f.close()
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
