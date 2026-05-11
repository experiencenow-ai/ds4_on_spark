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
    buffer_id: str
    buffer_item_id: str
    seen_task_id: int
    seen_buffer_item_id: int
    family_count: int
    template_count: int
    pair_count: int
    buffer_id_count: int
    buffer_item_count: int
    history_noise_rate: float = 0.0
    history_dup_rate: float = 0.0
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

def _safe_div(num: float, den: float) -> float:
    if den == 0.0:
        return(0.0)
    return(num / den)

def _dup_rate(total: int, uniq: int) -> float:
    if total <= 0:
        return(0.0)
    return(float(max(0, total - uniq)) / float(total))

def _history_rates(history: List[Dict[str, Any]]) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float], Dict[str, float]]:
    tmpl_total: Dict[str, int] = {}
    tmpl_flagged: Dict[str, int] = {}
    pair_total: Dict[str, int] = {}
    pair_flagged: Dict[str, int] = {}

    tmpl_out_total: Dict[str, int] = {}
    tmpl_out_uniq: Dict[str, int] = {}
    tmpl_out_seen: Dict[str, set] = {}
    pair_out_total: Dict[str, int] = {}
    pair_out_uniq: Dict[str, int] = {}
    pair_out_seen: Dict[str, set] = {}

    for obj in history:
        c = lib.canonicalize_record(obj)
        if c.rtype != "task_run":
            continue
        tmpl = c.prompt_template_id
        fam = c.task_family
        pair_k = "" if (fam == "" or tmpl == "") else f"{fam}|{tmpl}"
        if tmpl != "":
            tmpl_total[tmpl] = tmpl_total.get(tmpl, 0) + 1
        if pair_k != "":
            pair_total[pair_k] = pair_total.get(pair_k, 0) + 1

        flags = lib.useful_novelty_flags(c.output, c.prompt)
        if len(flags) != 0:
            if tmpl != "":
                tmpl_flagged[tmpl] = tmpl_flagged.get(tmpl, 0) + 1
            if pair_k != "":
                pair_flagged[pair_k] = pair_flagged.get(pair_k, 0) + 1

        if c.output != "" and tmpl != "":
            out_h = lib.text_sha1(lib.normalize_text(c.output))
            tmpl_out_total[tmpl] = tmpl_out_total.get(tmpl, 0) + 1
            tmpl_out_seen.setdefault(tmpl, set())
            if out_h not in tmpl_out_seen[tmpl]:
                tmpl_out_seen[tmpl].add(out_h)
                tmpl_out_uniq[tmpl] = tmpl_out_uniq.get(tmpl, 0) + 1
            if pair_k != "":
                pair_out_total[pair_k] = pair_out_total.get(pair_k, 0) + 1
                pair_out_seen.setdefault(pair_k, set())
                if out_h not in pair_out_seen[pair_k]:
                    pair_out_seen[pair_k].add(out_h)
                    pair_out_uniq[pair_k] = pair_out_uniq.get(pair_k, 0) + 1

    tmpl_noise: Dict[str, float] = {}
    pair_noise: Dict[str, float] = {}
    for key, total in tmpl_total.items():
        tmpl_noise[key] = _safe_div(float(tmpl_flagged.get(key, 0)), float(total))
    for key, total in pair_total.items():
        pair_noise[key] = _safe_div(float(pair_flagged.get(key, 0)), float(total))

    tmpl_dup: Dict[str, float] = {}
    pair_dup: Dict[str, float] = {}
    for key, total in tmpl_out_total.items():
        tmpl_dup[key] = _dup_rate(total, tmpl_out_uniq.get(key, 0))
    for key, total in pair_out_total.items():
        pair_dup[key] = _dup_rate(total, pair_out_uniq.get(key, 0))

    return(tmpl_noise, pair_noise, tmpl_dup, pair_dup)

def _candidate_history_rate(template_rates: Dict[str, float], pair_rates: Dict[str, float], task_family: str, prompt_template_id: str) -> float:
    pair_k = "" if (task_family == "" or prompt_template_id == "") else f"{task_family}|{prompt_template_id}"
    if pair_k != "" and pair_k in pair_rates:
        return(float(pair_rates.get(pair_k, 0.0)))
    return(float(template_rates.get(prompt_template_id, 0.0)))


def _score(history: List[Dict[str, Any]], candidates: List[Dict[str, Any]], noise_weight: float = 0.75, dup_weight: float = 0.50, max_noise_rate: float = 1.0, max_dup_rate: float = 1.0, buffer_id_weight: float = 0.15, buffer_item_weight: float = 0.60) -> List[CandidateScore]:
    hist_task_ids: Dict[str, int] = {}
    hist_family: Dict[str, int] = {}
    hist_template: Dict[str, int] = {}
    hist_pair: Dict[str, int] = {}
    hist_tags: Dict[str, int] = {}
    hist_buffer_id: Dict[str, int] = {}
    hist_buffer_item: Dict[str, int] = {}

    tmpl_noise, pair_noise, tmpl_dup, pair_dup = _history_rates(history)

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
        if c.buffer_id != "":
            hist_buffer_id[c.buffer_id] = hist_buffer_id.get(c.buffer_id, 0) + 1
        if c.buffer_item_id != "":
            hist_buffer_item[c.buffer_item_id] = hist_buffer_item.get(c.buffer_item_id, 0) + 1

    scored: List[CandidateScore] = []
    for obj in candidates:
        task_id = lib.get_str(obj, "task_id", "task")
        task_family = lib.get_str(obj, "task_family", "family", "suite", "category")
        prompt_template_id = lib.get_str(obj, "prompt_template_id", "template_id", "prompt_template", "template")
        tags = _get_list(obj, "tags", "tag")
        buffer_id = lib.get_str(obj, "buffer_id", "entropy_buffer_id")
        buffer_item_id = lib.get_str(obj, "buffer_item_id", "entropy_buffer_item_id", "buffer_key")
        seen = 1 if task_id in hist_task_ids else 0
        seen_buf_item = 1 if (buffer_item_id != "" and buffer_item_id in hist_buffer_item) else 0
        fam_c = hist_family.get(task_family, 0)
        tmpl_c = hist_template.get(prompt_template_id, 0)
        pair_k = f"{task_family}|{prompt_template_id}"
        pair_c = hist_pair.get(pair_k, 0)
        buf_c = hist_buffer_id.get(buffer_id, 0)
        buf_item_c = hist_buffer_item.get(buffer_item_id, 0)
        noise_rate = _candidate_history_rate(tmpl_noise, pair_noise, task_family, prompt_template_id)
        dup_rate = _candidate_history_rate(tmpl_dup, pair_dup, task_family, prompt_template_id)
        if max_noise_rate < 1.0 and noise_rate > max_noise_rate:
            continue
        if max_dup_rate < 1.0 and dup_rate > max_dup_rate:
            continue
        delta = {
            "task_family": _delta_entropy_for_add(hist_family, task_family),
            "prompt_template_id": _delta_entropy_for_add(hist_template, prompt_template_id),
            "task_family_template_pair": _delta_entropy_for_add(hist_pair, pair_k),
            "tags": _delta_entropy_for_add_tags(hist_tags, tags),
            "buffer_id": _delta_entropy_for_add(hist_buffer_id, buffer_id),
            "buffer_item_id": _delta_entropy_for_add(hist_buffer_item, buffer_item_id),
        }
        score = 0.0
        score += (2.0 * delta["task_family"])
        score += (1.5 * delta["prompt_template_id"])
        score += (1.0 * delta["task_family_template_pair"])
        score += (0.8 * delta["tags"])
        score += (float(buffer_id_weight) * delta["buffer_id"])
        score += (float(buffer_item_weight) * delta["buffer_item_id"])
        score += (0.10 * _inv_freq_bonus(fam_c))
        score += (0.05 * _inv_freq_bonus(tmpl_c))
        score += (0.05 * _inv_freq_bonus(pair_c))
        score += (0.02 * _inv_freq_bonus(buf_c))
        score += (0.05 * _inv_freq_bonus(buf_item_c))
        score -= (float(noise_weight) * float(noise_rate))
        score -= (float(dup_weight) * float(dup_rate))
        if len(tags) != 0:
            tag_bonus = sum(_inv_freq_bonus(hist_tags.get(t, 0)) for t in tags) / float(len(tags))
            score += (0.05 * tag_bonus)
        if seen != 0:
            score -= 10.0
        if buffer_item_id != "" and hist_buffer_item.get(buffer_item_id, 0) > 0:
            score -= 0.25
        scored.append(CandidateScore(
            task_id=task_id,
            task_family=task_family,
            prompt_template_id=prompt_template_id,
            tags=tags,
            buffer_id=buffer_id,
            buffer_item_id=buffer_item_id,
            seen_task_id=seen,
            seen_buffer_item_id=seen_buf_item,
            family_count=fam_c,
            template_count=tmpl_c,
            pair_count=pair_c,
            buffer_id_count=buf_c,
            buffer_item_count=buf_item_c,
            history_noise_rate=noise_rate,
            history_dup_rate=dup_rate,
            score=score,
            delta_entropy_bits=delta,
        ))

    scored.sort(key=lambda c: _candidate_sort_key(c.score, c.seen_task_id, c.task_family, c.prompt_template_id, c.task_id), reverse=True)
    return(scored)


def _select(scored: List[CandidateScore], history: List[Dict[str, Any]], limit: int, max_per_family: int, max_per_template: int, avoid_seen_task_id: bool, avoid_seen_buffer_item_id: bool = False, noise_weight: float = 0.75, dup_weight: float = 0.50, max_noise_rate: float = 1.0, max_dup_rate: float = 1.0, buffer_id_weight: float = 0.15, buffer_item_weight: float = 0.60) -> List[CandidateScore]:
    if limit <= 0:
        return([])
    if max_per_family < 0:
        max_per_family = 0
    if max_per_template < 0:
        max_per_template = 0

    tmpl_noise, pair_noise, tmpl_dup, pair_dup = _history_rates(history)

    hist_task_ids: Dict[str, int] = {}
    hist_family: Dict[str, int] = {}
    hist_template: Dict[str, int] = {}
    hist_pair: Dict[str, int] = {}
    hist_tags: Dict[str, int] = {}
    hist_buffer_id: Dict[str, int] = {}
    hist_buffer_item: Dict[str, int] = {}
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
        if c.buffer_id != "":
            hist_buffer_id[c.buffer_id] = hist_buffer_id.get(c.buffer_id, 0) + 1
        if c.buffer_item_id != "":
            hist_buffer_item[c.buffer_item_id] = hist_buffer_item.get(c.buffer_item_id, 0) + 1

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
            if avoid_seen_buffer_item_id and c.buffer_item_id != "" and hist_buffer_item.get(c.buffer_item_id, 0) > 0:
                continue
            if max_per_family > 0 and family_sel.get(c.task_family, 0) >= max_per_family:
                continue
            if max_per_template > 0 and template_sel.get(c.prompt_template_id, 0) >= max_per_template:
                continue

            pair_k = f"{c.task_family}|{c.prompt_template_id}"
            noise_rate = _candidate_history_rate(tmpl_noise, pair_noise, c.task_family, c.prompt_template_id)
            dup_rate = _candidate_history_rate(tmpl_dup, pair_dup, c.task_family, c.prompt_template_id)
            if max_noise_rate < 1.0 and noise_rate > max_noise_rate:
                continue
            if max_dup_rate < 1.0 and dup_rate > max_dup_rate:
                continue
            delta = {
                "task_family": _delta_entropy_for_add(hist_family, c.task_family),
                "prompt_template_id": _delta_entropy_for_add(hist_template, c.prompt_template_id),
                "task_family_template_pair": _delta_entropy_for_add(hist_pair, pair_k),
                "tags": _delta_entropy_for_add_tags(hist_tags, list(c.tags)),
                "buffer_id": _delta_entropy_for_add(hist_buffer_id, c.buffer_id),
                "buffer_item_id": _delta_entropy_for_add(hist_buffer_item, c.buffer_item_id),
            }
            score = 0.0
            score += (2.0 * delta["task_family"])
            score += (1.5 * delta["prompt_template_id"])
            score += (1.0 * delta["task_family_template_pair"])
            score += (0.8 * delta["tags"])
            score += (float(buffer_id_weight) * delta["buffer_id"])
            score += (float(buffer_item_weight) * delta["buffer_item_id"])
            score += (0.10 * _inv_freq_bonus(hist_family.get(c.task_family, 0)))
            score += (0.05 * _inv_freq_bonus(hist_template.get(c.prompt_template_id, 0)))
            score += (0.05 * _inv_freq_bonus(hist_pair.get(pair_k, 0)))
            score += (0.02 * _inv_freq_bonus(hist_buffer_id.get(c.buffer_id, 0)))
            score += (0.05 * _inv_freq_bonus(hist_buffer_item.get(c.buffer_item_id, 0)))
            score -= (float(noise_weight) * float(noise_rate))
            score -= (float(dup_weight) * float(dup_rate))
            if len(c.tags) != 0:
                tag_bonus = sum(_inv_freq_bonus(hist_tags.get(t, 0)) for t in c.tags) / float(len(c.tags))
                score += (0.05 * tag_bonus)
            if c.seen_task_id != 0:
                score -= 10.0
            if c.buffer_item_id != "" and hist_buffer_item.get(c.buffer_item_id, 0) > 0:
                score -= 0.25

            key = _candidate_sort_key(score, c.seen_task_id, c.task_family, c.prompt_template_id, c.task_id)
            if key > best_key:
                best_key = key
                best = CandidateScore(
                    task_id=c.task_id,
                    task_family=c.task_family,
                    prompt_template_id=c.prompt_template_id,
                    tags=list(c.tags),
                    buffer_id=c.buffer_id,
                    buffer_item_id=c.buffer_item_id,
                    seen_task_id=c.seen_task_id,
                    seen_buffer_item_id=(1 if hist_buffer_item.get(c.buffer_item_id, 0) > 0 else 0),
                    family_count=c.family_count,
                    template_count=c.template_count,
                    pair_count=c.pair_count,
                    buffer_id_count=hist_buffer_id.get(c.buffer_id, 0),
                    buffer_item_count=hist_buffer_item.get(c.buffer_item_id, 0),
                    history_noise_rate=noise_rate,
                    history_dup_rate=dup_rate,
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
        if best.buffer_id != "":
            hist_buffer_id[best.buffer_id] = hist_buffer_id.get(best.buffer_id, 0) + 1
        if best.buffer_item_id != "":
            hist_buffer_item[best.buffer_item_id] = hist_buffer_item.get(best.buffer_item_id, 0) + 1

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
    p.add_argument("--avoid-seen-buffer-item-id", action="store_true", help="Exclude candidates whose buffer_item_id already appears in history.")
    p.add_argument("--noise-weight", type=float, default=0.75, help="Penalty multiplier for historical useful-novelty flag rate.")
    p.add_argument("--dup-weight", type=float, default=0.50, help="Penalty multiplier for historical normalized-output duplicate rate.")
    p.add_argument("--buffer-id-weight", type=float, default=0.15, help="Coverage weight for buffer_id entropy gain (0 disables).")
    p.add_argument("--buffer-item-weight", type=float, default=0.60, help="Coverage weight for buffer_item_id entropy gain (0 disables).")
    p.add_argument("--max-noise-rate", type=float, default=1.0, help="Drop candidates above this historical noise rate (1.0 disables).")
    p.add_argument("--max-dup-rate", type=float, default=1.0, help="Drop candidates above this historical dup rate (1.0 disables).")
    p.add_argument("--out-json", type=str, default="", help="Write recommendations JSON to this path.")
    p.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if len(args.history_jsonl) == 0:
        raise SystemExit("--history-jsonl is required (repeatable)")
    if len(args.candidates_jsonl) == 0:
        raise SystemExit("--candidates-jsonl is required (repeatable)")

    history = lib.load_jsonl(args.history_jsonl)
    candidates = lib.load_jsonl(args.candidates_jsonl)
    scored = _score(history, candidates, float(args.noise_weight), float(args.dup_weight), float(args.max_noise_rate), float(args.max_dup_rate), float(args.buffer_id_weight), float(args.buffer_item_weight))
    top = _select(scored, history, max(0, args.limit), args.max_per_family, args.max_per_template, bool(args.avoid_seen_task_id), bool(args.avoid_seen_buffer_item_id), float(args.noise_weight), float(args.dup_weight), float(args.max_noise_rate), float(args.max_dup_rate), float(args.buffer_id_weight), float(args.buffer_item_weight))

    recs: List[Dict[str, Any]] = []
    for c in top:
        recs.append({
            "task_id": c.task_id,
            "task_family": c.task_family,
            "prompt_template_id": c.prompt_template_id,
            "tags": c.tags,
            "buffer_id": c.buffer_id,
            "buffer_item_id": c.buffer_item_id,
            "score": c.score,
            "delta_entropy_bits": dict(c.delta_entropy_bits),
            "penalties": {
                "history_noise_rate": c.history_noise_rate,
                "history_dup_rate": c.history_dup_rate,
                "noise_weight": float(args.noise_weight),
                "dup_weight": float(args.dup_weight),
            },
            "reasons": {
                "seen_task_id": bool(c.seen_task_id),
                "seen_buffer_item_id": bool(c.seen_buffer_item_id),
                "history_family_count": c.family_count,
                "history_template_count": c.template_count,
                "history_family_template_pair_count": c.pair_count,
                "history_buffer_id_count": c.buffer_id_count,
                "history_buffer_item_id_count": c.buffer_item_count,
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
            "avoid_seen_buffer_item_id": bool(args.avoid_seen_buffer_item_id),
            "noise_weight": float(args.noise_weight),
            "dup_weight": float(args.dup_weight),
            "buffer_id_weight": float(args.buffer_id_weight),
            "buffer_item_weight": float(args.buffer_item_weight),
            "max_noise_rate": float(args.max_noise_rate),
            "max_dup_rate": float(args.max_dup_rate),
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
