#!/usr/bin/env python3
"""Recommend next entropy-buffer task batch to increase coverage deterministically."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    score: float = 0.0
    delta_entropy_bits: Dict[str, float] = field(default_factory=dict)


def _get_list(obj: Dict[str, Any], *names: str) -> List[str]:
    return(lib.get_list(obj, *names))


def _delta_entropy_for_add(counts: Dict[str, int], key: str) -> float:
    if key == "":
        return(0.0)
    before = lib.shannon_entropy(counts)
    counts2 = dict(counts)
    counts2[key] = counts2.get(key, 0) + 1
    after = lib.shannon_entropy(counts2)
    return(after - before)

def _delta_entropy_for_add_tags(counts: Dict[str, int], tags: List[str]) -> float:
    if len(tags) == 0:
        return(0.0)
    before = lib.shannon_entropy(counts)
    counts2 = dict(counts)
    for tag in sorted(set(tags)):
        if tag == "":
            continue
        counts2[tag] = counts2.get(tag, 0) + 1
    after = lib.shannon_entropy(counts2)
    return(after - before)


def _inv_freq_bonus(count: int) -> float:
    return(1.0 / (1.0 + float(max(0, count))))


def _candidate_sort_key(score: float, seen_task_id: int, task_family: str, prompt_template_id: str, task_id: str) -> Tuple[float, int, str, str, str]:
    return(score, -int(seen_task_id), task_family, prompt_template_id, task_id)


def _score(history: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[CandidateScore]:
    hist_task_ids: Dict[str, int] = {}
    hist_family: Dict[str, int] = {}
    hist_template: Dict[str, int] = {}
    hist_pair: Dict[str, int] = {}
    hist_tags: Dict[str, int] = {}

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
        for tag in lib.get_list(c.raw, "tags", "tag"):
            hist_tags[tag] = hist_tags.get(tag, 0) + 1

    scored: List[CandidateScore] = []
    for obj in candidates:
        task_id = lib.get_str(obj, "task_id", "task")
        task_family = lib.get_str(obj, "task_family", "family", "suite", "category")
        prompt_template_id = lib.get_str(obj, "prompt_template_id", "template_id", "prompt_template", "template")
        tags = _get_list(obj, "tags", "tag")
        seen = 1 if task_id in hist_task_ids else 0
        fam_c = hist_family.get(task_family, 0)
        tmpl_c = hist_template.get(prompt_template_id, 0)
        pair_k = f"{task_family}|{prompt_template_id}"
        pair_c = hist_pair.get(pair_k, 0)
        delta = {
            "task_family": _delta_entropy_for_add(hist_family, task_family),
            "prompt_template_id": _delta_entropy_for_add(hist_template, prompt_template_id),
            "task_family_template_pair": _delta_entropy_for_add(hist_pair, pair_k),
            "tags": _delta_entropy_for_add_tags(hist_tags, tags),
        }
        score = 0.0
        score += (2.0 * delta["task_family"])
        score += (1.5 * delta["prompt_template_id"])
        score += (1.0 * delta["task_family_template_pair"])
        score += (0.8 * delta["tags"])
        score += (0.10 * _inv_freq_bonus(fam_c))
        score += (0.05 * _inv_freq_bonus(tmpl_c))
        score += (0.05 * _inv_freq_bonus(pair_c))
        if len(tags) != 0:
            tag_bonus = sum(_inv_freq_bonus(hist_tags.get(t, 0)) for t in tags) / float(len(tags))
            score += (0.05 * tag_bonus)
        if seen != 0:
            score -= 10.0
        scored.append(CandidateScore(
            task_id=task_id,
            task_family=task_family,
            prompt_template_id=prompt_template_id,
            tags=tags,
            seen_task_id=seen,
            family_count=fam_c,
            template_count=tmpl_c,
            pair_count=pair_c,
            score=score,
            delta_entropy_bits=delta,
        ))

    scored.sort(key=lambda c: _candidate_sort_key(c.score, c.seen_task_id, c.task_family, c.prompt_template_id, c.task_id), reverse=True)
    return(scored)


def _select(scored: List[CandidateScore], history: List[Dict[str, Any]], limit: int, max_per_family: int, max_per_template: int, avoid_seen_task_id: bool) -> List[CandidateScore]:
    if limit <= 0:
        return([])
    if max_per_family < 0:
        max_per_family = 0
    if max_per_template < 0:
        max_per_template = 0

    hist_task_ids: Dict[str, int] = {}
    hist_family: Dict[str, int] = {}
    hist_template: Dict[str, int] = {}
    hist_pair: Dict[str, int] = {}
    hist_tags: Dict[str, int] = {}
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
        for tag in lib.get_list(c.raw, "tags", "tag"):
            hist_tags[tag] = hist_tags.get(tag, 0) + 1

    family_sel: Dict[str, int] = {}
    template_sel: Dict[str, int] = {}

    out: List[CandidateScore] = []
    remaining = list(scored)
    while len(out) < limit and len(remaining) != 0:
        best: Optional[CandidateScore] = None
        best_key = (float("-inf"), 0, "", "", "")

        for c in remaining:
            if avoid_seen_task_id and hist_task_ids.get(c.task_id, 0) > 0:
                continue
            if max_per_family > 0 and family_sel.get(c.task_family, 0) >= max_per_family:
                continue
            if max_per_template > 0 and template_sel.get(c.prompt_template_id, 0) >= max_per_template:
                continue

            pair_k = f"{c.task_family}|{c.prompt_template_id}"
            delta = {
                "task_family": _delta_entropy_for_add(hist_family, c.task_family),
                "prompt_template_id": _delta_entropy_for_add(hist_template, c.prompt_template_id),
                "task_family_template_pair": _delta_entropy_for_add(hist_pair, pair_k),
                "tags": _delta_entropy_for_add_tags(hist_tags, list(c.tags)),
            }
            score = 0.0
            score += (2.0 * delta["task_family"])
            score += (1.5 * delta["prompt_template_id"])
            score += (1.0 * delta["task_family_template_pair"])
            score += (0.8 * delta["tags"])
            score += (0.10 * _inv_freq_bonus(hist_family.get(c.task_family, 0)))
            score += (0.05 * _inv_freq_bonus(hist_template.get(c.prompt_template_id, 0)))
            score += (0.05 * _inv_freq_bonus(hist_pair.get(pair_k, 0)))
            if len(c.tags) != 0:
                tag_bonus = sum(_inv_freq_bonus(hist_tags.get(t, 0)) for t in c.tags) / float(len(c.tags))
                score += (0.05 * tag_bonus)
            if c.seen_task_id != 0:
                score -= 10.0

            key = _candidate_sort_key(score, c.seen_task_id, c.task_family, c.prompt_template_id, c.task_id)
            if key > best_key:
                best_key = key
                best = CandidateScore(
                    task_id=c.task_id,
                    task_family=c.task_family,
                    prompt_template_id=c.prompt_template_id,
                    tags=list(c.tags),
                    seen_task_id=c.seen_task_id,
                    family_count=c.family_count,
                    template_count=c.template_count,
                    pair_count=c.pair_count,
                    score=score,
                    delta_entropy_bits=delta,
                )

        if best is None:
            break

        out.append(best)
        family_sel[best.task_family] = family_sel.get(best.task_family, 0) + 1
        template_sel[best.prompt_template_id] = template_sel.get(best.prompt_template_id, 0) + 1
        if best.task_family != "":
            hist_family[best.task_family] = hist_family.get(best.task_family, 0) + 1
        if best.prompt_template_id != "":
            hist_template[best.prompt_template_id] = hist_template.get(best.prompt_template_id, 0) + 1
        if best.task_family != "" and best.prompt_template_id != "":
            pair_k = f"{best.task_family}|{best.prompt_template_id}"
            hist_pair[pair_k] = hist_pair.get(pair_k, 0) + 1
        for tag in best.tags:
            if tag != "":
                hist_tags[tag] = hist_tags.get(tag, 0) + 1

        remaining = [c for c in remaining if not (c.task_id == best.task_id and c.prompt_template_id == best.prompt_template_id)]
    return(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Recommend next entropy-buffer task batch from candidate JSONL.")
    p.add_argument("--history-jsonl", action="append", default=[], help="Past task/judge JSONL (repeatable).")
    p.add_argument("--candidates-jsonl", action="append", default=[], help="Candidate task JSONL (repeatable).")
    p.add_argument("--limit", type=int, default=25, help="Max recommendations.")
    p.add_argument("--max-per-family", type=int, default=0, help="Hard cap per task_family (0 disables).")
    p.add_argument("--max-per-template", type=int, default=0, help="Hard cap per prompt_template_id (0 disables).")
    p.add_argument("--avoid-seen-task-id", action="store_true", help="Exclude candidates whose task_id already appears in history.")
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
    top = _select(scored, history, max(0, args.limit), args.max_per_family, args.max_per_template, bool(args.avoid_seen_task_id))

    recs: List[Dict[str, Any]] = []
    for c in top:
        recs.append({
            "task_id": c.task_id,
            "task_family": c.task_family,
            "prompt_template_id": c.prompt_template_id,
            "tags": c.tags,
            "score": c.score,
            "delta_entropy_bits": dict(c.delta_entropy_bits),
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
            "max_per_family": args.max_per_family,
            "max_per_template": args.max_per_template,
            "avoid_seen_task_id": bool(args.avoid_seen_task_id),
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
