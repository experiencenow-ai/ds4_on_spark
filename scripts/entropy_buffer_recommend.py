#!/usr/bin/env python3
"""Recommend next entropy-buffer task batch to increase coverage deterministically."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

try:
    from scripts import entropy_buffer_lib as lib
except ModuleNotFoundError:
    import entropy_buffer_lib as lib


@dataclass
class CandidateScore:
    task_id: str
    task_family: str
    prompt_template_id: str
    tags: List[str]
    seen_task_id: int
    family_count: int
    template_count: int
    pair_count: int


def _get_list(obj: Dict[str, Any], *names: str) -> List[str]:
    for name in names:
        if name in obj and obj[name] is not None:
            v = obj[name]
            if isinstance(v, list):
                return([str(x) for x in v])
            if isinstance(v, str) and v.strip() != "":
                return([x.strip() for x in v.split(",") if x.strip() != ""])
    return([])


def _score(history: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[CandidateScore]:
    hist_task_ids: Dict[str, int] = {}
    hist_family: Dict[str, int] = {}
    hist_template: Dict[str, int] = {}
    hist_pair: Dict[str, int] = {}

    for obj in history:
        c = lib.canonicalize_record(obj)
        if c.rtype != "task_run":
            continue
        if c.task_id != "":
            hist_task_ids[c.task_id] = hist_task_ids.get(c.task_id, 0) + 1
        if c.task_family != "":
            hist_family[c.task_family] = hist_family.get(c.task_family, 0) + 1
        if c.prompt_template_id != "":
            hist_template[c.prompt_template_id] = hist_template.get(c.prompt_template_id, 0) + 1
        if c.task_family != "" and c.prompt_template_id != "":
            k = f"{c.task_family}|{c.prompt_template_id}"
            hist_pair[k] = hist_pair.get(k, 0) + 1

    scored: List[CandidateScore] = []
    for obj in candidates:
        task_id = lib.get_str(obj, "task_id", "task")
        task_family = lib.get_str(obj, "task_family", "family", "suite", "category")
        prompt_template_id = lib.get_str(obj, "prompt_template_id", "template_id", "prompt_template", "template")
        tags = _get_list(obj, "tags", "tag")
        seen = 1 if task_id in hist_task_ids else 0
        fam_c = hist_family.get(task_family, 0)
        tmpl_c = hist_template.get(prompt_template_id, 0)
        pair_c = hist_pair.get(f"{task_family}|{prompt_template_id}", 0)
        scored.append(CandidateScore(
            task_id=task_id,
            task_family=task_family,
            prompt_template_id=prompt_template_id,
            tags=tags,
            seen_task_id=seen,
            family_count=fam_c,
            template_count=tmpl_c,
            pair_count=pair_c,
        ))

    scored.sort(key=lambda c: (
        c.seen_task_id,
        c.family_count,
        c.template_count,
        c.pair_count,
        c.task_family,
        c.prompt_template_id,
        c.task_id,
    ))
    return(scored)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Recommend next entropy-buffer task batch from candidate JSONL.")
    p.add_argument("--history-jsonl", action="append", default=[], help="Past task/judge JSONL (repeatable).")
    p.add_argument("--candidates-jsonl", action="append", default=[], help="Candidate task JSONL (repeatable).")
    p.add_argument("--limit", type=int, default=25, help="Max recommendations.")
    p.add_argument("--out-json", type=str, default="", help="Write recommendations JSON to this path.")
    p.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if len(args.history_jsonl) == 0:
        raise SystemExit("--history-jsonl is required (repeatable)")
    if len(args.candidates_jsonl) == 0:
        raise SystemExit("--candidates-jsonl is required (repeatable)")

    history = lib.load_jsonl(args.history_jsonl)
    candidates = lib.load_jsonl(args.candidates_jsonl)
    scored = _score(history, candidates)
    top = scored[: max(0, args.limit)]

    recs: List[Dict[str, Any]] = []
    for c in top:
        recs.append({
            "task_id": c.task_id,
            "task_family": c.task_family,
            "prompt_template_id": c.prompt_template_id,
            "tags": c.tags,
            "reasons": {
                "seen_task_id": bool(c.seen_task_id),
                "history_family_count": c.family_count,
                "history_template_count": c.template_count,
                "history_family_template_pair_count": c.pair_count,
            },
        })

    js: Dict[str, Any] = {
        "recommendations": recs,
        "meta": {
            "history_records": len(history),
            "candidates_records": len(candidates),
            "limit": args.limit,
        },
    }

    text = json.dumps(js, indent=2, sort_keys=True) + "\n"
    if args.out_json != "":
        f = open(args.out_json, "w", encoding="utf-8")
        try:
            f.write(text)
        finally:
            f.close()
    if args.json:
        sys.stdout.write(text)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
