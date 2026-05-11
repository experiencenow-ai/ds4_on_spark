#!/usr/bin/env python3
"""Summarize entropy-buffer diversity/degeneracy metrics from mixed JSONL logs."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from scripts import entropy_buffer_lib as lib
except ModuleNotFoundError:
    import entropy_buffer_lib as lib


@dataclass
class MetricsReport:
    totals: Dict[str, Any]
    diversity: Dict[str, Any]
    tokens: Dict[str, Any]
    duplicates: Dict[str, Any]
    judge: Dict[str, Any]
    reuse: Dict[str, Any]
    useful_novelty: Dict[str, Any]
    runs: Dict[str, Any]


def _inc(counts: Dict[str, int], key: str) -> None:
    if key == "":
        return
    counts[key] = counts.get(key, 0) + 1


def _dup_rate(values: Sequence[str]) -> float:
    if len(values) == 0:
        return(0.0)
    uniq = len(set(values))
    return(float(len(values) - uniq) / float(len(values)))

def _run_key(run_id: str) -> str:
    if run_id != "":
        return(run_id)
    return("<missing_run_id>")

def _run_summary(task_runs: Sequence[lib.CanonicalRecord]) -> Dict[str, Any]:
    task_id_counts: Dict[str, int] = {}
    task_family_counts: Dict[str, int] = {}
    template_counts: Dict[str, int] = {}
    family_template_counts: Dict[str, int] = {}
    task_template_counts: Dict[str, int] = {}
    model_counts: Dict[str, int] = {}
    answer_counts: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    outputs_norm: List[str] = []
    answers_nonempty: List[str] = []
    novelty_flagged = 0

    for c in task_runs:
        _inc(task_id_counts, c.task_id)
        _inc(task_family_counts, c.task_family)
        _inc(template_counts, c.prompt_template_id)
        if c.task_family != "" and c.prompt_template_id != "":
            _inc(family_template_counts, f"{c.task_family}|{c.prompt_template_id}")
        if c.task_id != "" and c.prompt_template_id != "":
            _inc(task_template_counts, f"{c.task_id}|{c.prompt_template_id}")
        _inc(model_counts, c.model_id)
        _inc(answer_counts, c.answer)
        if c.answer != "":
            answers_nonempty.append(c.answer)
        for tag in lib.get_list(c.raw, "tags", "tag"):
            _inc(tag_counts, tag)
        if c.output != "":
            outputs_norm.append(lib.normalize_text(c.output))
        if len(lib.useful_novelty_flags(c.output, c.prompt)) != 0:
            novelty_flagged += 1

    count = len(task_runs)
    return({
        "count": count,
        "diversity": {
            "task_id": _div_stats(task_id_counts),
            "task_family": _div_stats(task_family_counts),
            "prompt_template_id": _div_stats(template_counts),
            "task_family_template_pair": _div_stats(family_template_counts),
            "task_id_template_pair": _div_stats(task_template_counts),
            "model_id": _div_stats(model_counts),
            "answer": _div_stats(answer_counts),
            "tags": _div_stats(tag_counts),
        },
        "duplicates": {
            "output_norm_dup_rate": _dup_rate(outputs_norm),
            "answer_dup_rate": _dup_rate(answers_nonempty),
        },
        "useful_novelty": {
            "flagged_task_runs": novelty_flagged,
            "flagged_task_run_rate": 0.0 if count == 0 else (float(novelty_flagged) / float(count)),
        },
    })

def _runs_block(task_runs: Sequence[lib.CanonicalRecord]) -> Dict[str, Any]:
    by_run: Dict[str, List[lib.CanonicalRecord]] = {}
    for c in task_runs:
        by_run.setdefault(_run_key(c.run_id), []).append(c)

    by_run_id: Dict[str, Any] = {}
    dup_rate_top: List[Dict[str, Any]] = []
    flagged_rate_top: List[Dict[str, Any]] = []
    low_pair_entropy_top: List[Dict[str, Any]] = []

    for run_id in sorted(by_run.keys()):
        summary = _run_summary(by_run[run_id])
        by_run_id[run_id] = summary
        dup_rate = float(((summary.get("duplicates") or {}).get("output_norm_dup_rate")) or 0.0)
        flagged_rate = float(((summary.get("useful_novelty") or {}).get("flagged_task_run_rate")) or 0.0)
        pair_ent = float(((((summary.get("diversity") or {}).get("task_family_template_pair") or {}).get("entropy_norm")) or 0.0))
        cnt = int(summary.get("count", 0) or 0)
        dup_rate_top.append({"run_id": run_id, "count": cnt, "output_norm_dup_rate": dup_rate})
        flagged_rate_top.append({"run_id": run_id, "count": cnt, "flagged_task_run_rate": flagged_rate})
        low_pair_entropy_top.append({"run_id": run_id, "count": cnt, "task_family_template_pair_entropy_norm": pair_ent})

    dup_rate_top.sort(key=lambda x: (-float(x.get("output_norm_dup_rate", 0.0)), -int(x.get("count", 0)), str(x.get("run_id", ""))))
    flagged_rate_top.sort(key=lambda x: (-float(x.get("flagged_task_run_rate", 0.0)), -int(x.get("count", 0)), str(x.get("run_id", ""))))
    low_pair_entropy_top.sort(key=lambda x: (float(x.get("task_family_template_pair_entropy_norm", 0.0)), -int(x.get("count", 0)), str(x.get("run_id", ""))))

    return({
        "run_id_unique": len([k for k in by_run_id.keys() if k != "<missing_run_id>"]),
        "by_run_id": by_run_id,
        "output_norm_dup_rate_by_run_id_top": dup_rate_top[:10],
        "flagged_task_run_rate_by_run_id_top": flagged_rate_top[:10],
        "low_pair_entropy_norm_by_run_id_top": low_pair_entropy_top[:10],
    })


def _majority_disagreement(labels: Sequence[str]) -> float:
    if len(labels) == 0:
        return(0.0)
    counts: Dict[str, int] = {}
    for lab in labels:
        _inc(counts, lab)
    maxc = max(counts.values())
    return(1.0 - (float(maxc) / float(len(labels))))

def _judge_slice_stats(label_counts: Dict[str, int], item_labels: Dict[str, List[str]], item_labels_decided_ab: Dict[str, List[str]]) -> Dict[str, Any]:
    total = int(sum(label_counts.values()))
    wins_a = int(label_counts.get("a", 0))
    wins_b = int(label_counts.get("b", 0))
    ties = int(label_counts.get("tie", 0))
    invalid = int(label_counts.get("invalid", 0))
    decided = wins_a + wins_b
    imbalance = 0.0 if decided == 0 else (abs(float(wins_a - wins_b)) / float(decided))
    balance = 1.0 - imbalance

    item_disagreements: List[float] = []
    for labs in item_labels.values():
        if len(labs) >= 2:
            item_disagreements.append(_majority_disagreement(labs))
    disagreement_rate = 0.0 if len(item_disagreements) == 0 else (sum(item_disagreements) / float(len(item_disagreements)))

    item_disagreements_decided_ab: List[float] = []
    for labs in item_labels_decided_ab.values():
        if len(labs) >= 2:
            item_disagreements_decided_ab.append(_majority_disagreement(labs))
    disagreement_rate_decided_ab = 0.0 if len(item_disagreements_decided_ab) == 0 else (sum(item_disagreements_decided_ab) / float(len(item_disagreements_decided_ab)))

    return({
        "count": total,
        "pair_item_count": len(item_labels),
        "label_counts": dict(sorted(label_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "label_entropy_bits": lib.shannon_entropy(label_counts),
        "decided_count_ab": decided,
        "decided_rate_ab": 0.0 if total == 0 else (float(decided) / float(total)),
        "tie_rate": 0.0 if total == 0 else (float(ties) / float(total)),
        "invalid_rate": 0.0 if total == 0 else (float(invalid) / float(total)),
        "label_balance_ab": balance,
        "label_imbalance_ab": imbalance,
        "disagreement_rate": disagreement_rate,
        "disagreement_rate_decided_ab": disagreement_rate_decided_ab,
    })

def _judge_slice_top(items: Sequence[Dict[str, Any]], key_name: str, sort_key: str, k: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for js in items:
        key = str(js.get(key_name, ""))
        if key == "":
            continue
        out.append(js)
    out.sort(key=lambda x: (-float(x.get(sort_key, 0.0)), -int(x.get("count", 0) or 0), str(x.get(key_name, ""))))
    return(out[:k])

def _judge_slice_low(items: Sequence[Dict[str, Any]], key_name: str, sort_key: str, k: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for js in items:
        key = str(js.get(key_name, ""))
        if key == "":
            continue
        out.append(js)
    out.sort(key=lambda x: (float(x.get(sort_key, 0.0)), -int(x.get("count", 0) or 0), str(x.get(key_name, ""))))
    return(out[:k])


def _safe_div(num: float, den: float) -> float:
    if den == 0.0:
        return(0.0)
    return(num / den)


def _percentile(values: Sequence[float], p: float) -> float:
    if len(values) == 0:
        return(0.0)
    if p <= 0.0:
        return(float(min(values)))
    if p >= 1.0:
        return(float(max(values)))
    xs = sorted(values)
    idx = int(round(p * float(len(xs) - 1)))
    if idx < 0:
        idx = 0
    if idx >= len(xs):
        idx = len(xs) - 1
    return(float(xs[idx]))


def _len_stats(values: Sequence[int]) -> Dict[str, Any]:
    if len(values) == 0:
        return({
            "count": 0,
            "min": 0,
            "max": 0,
            "mean": 0.0,
            "p50": 0.0,
            "p90": 0.0,
        })
    s = float(sum(values))
    return({
        "count": len(values),
        "min": int(min(values)),
        "max": int(max(values)),
        "mean": (s / float(len(values))),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
    })

def _num_stats(values: Sequence[float]) -> Dict[str, Any]:
    if len(values) == 0:
        return({
            "count": 0,
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "p50": 0.0,
            "p90": 0.0,
        })
    s = float(sum(values))
    return({
        "count": len(values),
        "min": float(min(values)),
        "max": float(max(values)),
        "mean": (s / float(len(values))),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
    })


def _hhi(counts: Dict[str, int]) -> float:
    total = float(sum(counts.values()))
    if total <= 0.0:
        return(0.0)
    h = 0.0
    for c in counts.values():
        p = float(c) / total
        h += (p * p)
    return(h)

def _entropy_norm_bits(counts: Dict[str, int]) -> float:
    uniq = len(counts)
    if uniq <= 1:
        return(0.0)
    h = lib.shannon_entropy(counts)
    return(_safe_div(h, math.log2(float(uniq))))


def _effective_num(counts: Dict[str, int]) -> float:
    h = lib.shannon_entropy(counts)
    return(pow(2.0, h))


def _div_stats(counts: Dict[str, int]) -> Dict[str, Any]:
    return({
        "unique": len(counts),
        "entropy_bits": lib.shannon_entropy(counts),
        "entropy_norm": _entropy_norm_bits(counts),
        "effective_num": _effective_num(counts),
        "top": lib.top_counts(counts),
    })


_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _char_ngrams_norm(text: str, n: int) -> List[str]:
    if n <= 0:
        return([])
    s = lib.normalize_text(text)
    s = _ALNUM_RE.sub("", s)
    if len(s) < n:
        return([])
    out: List[str] = []
    for i in range(0, len(s) - n + 1):
        out.append(s[i:i + n])
    return(out)

def _distinct_ratio(counts: Dict[str, int]) -> float:
    total = float(sum(counts.values()))
    if total <= 0.0:
        return(0.0)
    return(float(len(counts)) / total)

def _rate_top(totals: Dict[str, int], flagged: Dict[str, int], key_name: str, k: int = 10) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for key, total in totals.items():
        if key == "" or total <= 0:
            continue
        bad = flagged.get(key, 0)
        items.append({
            key_name: key,
            "count": total,
            "flagged": bad,
            "flagged_rate": float(bad) / float(total),
        })
    items.sort(key=lambda x: (-float(x.get("flagged_rate", 0.0)), -int(x.get("count", 0)), str(x.get(key_name, ""))))
    return(items[:k])

def _dup_rate_top(totals: Dict[str, int], uniq: Dict[str, int], key_name: str, k: int = 10) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for key, total in totals.items():
        if key == "" or total <= 0:
            continue
        u = uniq.get(key, 0)
        rate = 0.0 if total <= 0 else (float(total - u) / float(total))
        items.append({
            key_name: key,
            "count": total,
            "unique": u,
            "dup_rate": rate,
        })
    items.sort(key=lambda x: (-float(x.get("dup_rate", 0.0)), -int(x.get("count", 0)), str(x.get(key_name, ""))))
    return(items[:k])

def _split_pair_key(key: str) -> Tuple[str, str]:
    if "|" not in key:
        return(key, "")
    a, b = key.split("|", 1)
    return(a, b)

def _task_template_dup_rate_top(task_template_outputs_norm: Dict[str, List[str]], k: int = 10) -> List[Dict[str, Any]]:
    totals: Dict[str, int] = {}
    uniq: Dict[str, int] = {}
    for key, outs in task_template_outputs_norm.items():
        if key == "" or len(outs) < 2:
            continue
        totals[key] = len(outs)
        uniq[key] = len(set(outs))
    items = _dup_rate_top(totals, uniq, "task_id_template_pair", k=k)
    out: List[Dict[str, Any]] = []
    for js in items:
        key = str(js.get("task_id_template_pair", ""))
        task_id, tmpl = _split_pair_key(key)
        out.append({
            "task_id_template_pair": key,
            "task_id": task_id,
            "prompt_template_id": tmpl,
            "count": int(js.get("count", 0) or 0),
            "unique": int(js.get("unique", 0) or 0),
            "dup_rate": float(js.get("dup_rate", 0.0) or 0.0),
        })
    return(out)


def summarize(records: Iterable[Dict[str, Any]]) -> MetricsReport:
    canon: List[lib.CanonicalRecord] = []
    unknown = 0
    for obj in records:
        c = lib.canonicalize_record(obj)
        canon.append(c)
        if c.rtype == "unknown":
            unknown += 1

    task_runs = [c for c in canon if c.rtype == "task_run"]
    judge_pairs = [c for c in canon if c.rtype == "judge_pair"]

    task_id_counts: Dict[str, int] = {}
    task_family_counts: Dict[str, int] = {}
    template_counts: Dict[str, int] = {}
    family_template_counts: Dict[str, int] = {}
    task_template_counts: Dict[str, int] = {}
    model_counts: Dict[str, int] = {}
    answers: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    buffer_ids: Dict[str, int] = {}
    buffer_items: Dict[str, int] = {}

    outputs_exact: List[str] = []
    outputs_norm: List[str] = []
    prompts_norm: List[str] = []

    task_template_outputs_norm: Dict[str, List[str]] = {}

    prompt_words: List[str] = []
    prompt_2grams: Dict[str, int] = {}
    prompt_3grams: Dict[str, int] = {}
    out_words: List[str] = []
    out_2grams: Dict[str, int] = {}
    out_3grams: Dict[str, int] = {}
    prompt_char3: Dict[str, int] = {}
    out_char3: Dict[str, int] = {}

    prompt_len_chars: List[int] = []
    prompt_len_words: List[int] = []
    output_len_chars: List[int] = []
    output_len_words: List[int] = []

    input_tokens: List[float] = []
    output_tokens: List[float] = []
    wall_ms: List[float] = []
    ms_per_output_token: List[float] = []
    output_tok_per_s: List[float] = []
    total_tok_per_s: List[float] = []
    input_tokens_present = 0
    output_tokens_present = 0
    wall_ms_present = 0

    answers_nonempty: List[str] = []
    answer_source_counts: Dict[str, int] = {}
    answer_task_runs_nonempty = 0
    answer_task_runs_extracted = 0
    buffer_id_present = 0
    buffer_item_id_present = 0

    novelty_flag_counts: Dict[str, int] = {}
    novelty_flagged = 0
    template_task_total: Dict[str, int] = {}
    template_task_flagged: Dict[str, int] = {}
    family_task_total: Dict[str, int] = {}
    family_task_flagged: Dict[str, int] = {}
    pair_task_total: Dict[str, int] = {}
    pair_task_flagged: Dict[str, int] = {}
    model_task_total: Dict[str, int] = {}
    model_task_flagged: Dict[str, int] = {}

    template_out_total: Dict[str, int] = {}
    template_out_uniq: Dict[str, int] = {}
    template_out_seen: Dict[str, set] = {}
    pair_out_total: Dict[str, int] = {}
    pair_out_uniq: Dict[str, int] = {}
    pair_out_seen: Dict[str, set] = {}
    model_out_total: Dict[str, int] = {}
    model_out_uniq: Dict[str, int] = {}
    model_out_seen: Dict[str, set] = {}

    for c in task_runs:
        tmpl = c.prompt_template_id
        fam = c.task_family
        mid = c.model_id
        pair_k = "" if (fam == "" or tmpl == "") else f"{fam}|{tmpl}"
        if tmpl != "":
            template_task_total[tmpl] = template_task_total.get(tmpl, 0) + 1
        if fam != "":
            family_task_total[fam] = family_task_total.get(fam, 0) + 1
        if pair_k != "":
            pair_task_total[pair_k] = pair_task_total.get(pair_k, 0) + 1
        if mid != "":
            model_task_total[mid] = model_task_total.get(mid, 0) + 1

        _inc(task_id_counts, c.task_id)
        _inc(task_family_counts, c.task_family)
        _inc(template_counts, c.prompt_template_id)
        if c.task_family != "" and c.prompt_template_id != "":
            _inc(family_template_counts, f"{c.task_family}|{c.prompt_template_id}")
        if c.task_id != "" and c.prompt_template_id != "":
            _inc(task_template_counts, f"{c.task_id}|{c.prompt_template_id}")
        _inc(model_counts, c.model_id)
        _inc(answers, c.answer)
        if c.answer != "":
            answers_nonempty.append(c.answer)
            answer_task_runs_nonempty += 1
            if c.answer_source == "extract":
                answer_task_runs_extracted += 1
        if c.answer_source != "":
            answer_source_counts[c.answer_source] = answer_source_counts.get(c.answer_source, 0) + 1
        for tag in lib.get_list(c.raw, "tags", "tag"):
            _inc(tag_counts, tag)
        if c.buffer_id != "":
            buffer_id_present += 1
            _inc(buffer_ids, c.buffer_id)
        if c.buffer_item_id != "":
            buffer_item_id_present += 1
            _inc(buffer_items, c.buffer_item_id)

        itok = lib.get_int(c.raw, "input_tokens", "prompt_tokens", "input_token_count")
        otok = lib.get_int(c.raw, "output_tokens", "completion_tokens", "output_token_count")
        wms = lib.get_float(c.raw, "wall_ms", "latency_ms", "duration_ms", "elapsed_ms")
        if itok is not None:
            input_tokens.append(float(itok))
            input_tokens_present += 1
        if otok is not None:
            output_tokens.append(float(otok))
            output_tokens_present += 1
        if wms is not None:
            wall_ms.append(float(wms))
            wall_ms_present += 1
        if wms is not None and wms > 0.0 and otok is not None and otok > 0:
            ms_per_output_token.append(float(wms) / float(otok))
            output_tok_per_s.append((float(otok) * 1000.0) / float(wms))
            if itok is not None:
                total_tok = float(itok + otok)
                total_tok_per_s.append((total_tok * 1000.0) / float(wms))

        flags = lib.useful_novelty_flags(c.output, c.prompt)
        if len(flags) != 0:
            novelty_flagged += 1
            if tmpl != "":
                template_task_flagged[tmpl] = template_task_flagged.get(tmpl, 0) + 1
            if fam != "":
                family_task_flagged[fam] = family_task_flagged.get(fam, 0) + 1
            if pair_k != "":
                pair_task_flagged[pair_k] = pair_task_flagged.get(pair_k, 0) + 1
            if mid != "":
                model_task_flagged[mid] = model_task_flagged.get(mid, 0) + 1
            for f in flags:
                novelty_flag_counts[f] = novelty_flag_counts.get(f, 0) + 1

        if c.output != "":
            outputs_exact.append(c.output)
            outputs_norm.append(lib.normalize_text(c.output))
            ws = lib.words(c.output)
            out_words.extend(ws)
            output_len_chars.append(len(c.output))
            output_len_words.append(len(ws))
            for ng in lib.word_ngrams(ws, 2):
                out_2grams[ng] = out_2grams.get(ng, 0) + 1
            for ng in lib.word_ngrams(ws, 3):
                out_3grams[ng] = out_3grams.get(ng, 0) + 1
            for ng in _char_ngrams_norm(c.output, 3):
                out_char3[ng] = out_char3.get(ng, 0) + 1

            out_norm = lib.normalize_text(c.output)
            out_h = lib.text_sha1(out_norm)
            if tmpl != "":
                template_out_total[tmpl] = template_out_total.get(tmpl, 0) + 1
                template_out_seen.setdefault(tmpl, set())
                if out_h not in template_out_seen[tmpl]:
                    template_out_seen[tmpl].add(out_h)
                    template_out_uniq[tmpl] = template_out_uniq.get(tmpl, 0) + 1
            if pair_k != "":
                pair_out_total[pair_k] = pair_out_total.get(pair_k, 0) + 1
                pair_out_seen.setdefault(pair_k, set())
                if out_h not in pair_out_seen[pair_k]:
                    pair_out_seen[pair_k].add(out_h)
                    pair_out_uniq[pair_k] = pair_out_uniq.get(pair_k, 0) + 1
            if mid != "":
                model_out_total[mid] = model_out_total.get(mid, 0) + 1
                model_out_seen.setdefault(mid, set())
                if out_h not in model_out_seen[mid]:
                    model_out_seen[mid].add(out_h)
                    model_out_uniq[mid] = model_out_uniq.get(mid, 0) + 1
        if c.prompt != "":
            prompts_norm.append(lib.normalize_text(c.prompt))
            ws = lib.words(c.prompt)
            prompt_words.extend(ws)
            prompt_len_chars.append(len(c.prompt))
            prompt_len_words.append(len(ws))
            for ng in lib.word_ngrams(ws, 2):
                prompt_2grams[ng] = prompt_2grams.get(ng, 0) + 1
            for ng in lib.word_ngrams(ws, 3):
                prompt_3grams[ng] = prompt_3grams.get(ng, 0) + 1
            for ng in _char_ngrams_norm(c.prompt, 3):
                prompt_char3[ng] = prompt_char3.get(ng, 0) + 1
        if c.task_id != "" and c.prompt_template_id != "" and c.output != "":
            k = f"{c.task_id}|{c.prompt_template_id}"
            task_template_outputs_norm.setdefault(k, []).append(lib.normalize_text(c.output))

    label_counts: Dict[str, int] = {}
    item_labels: Dict[str, List[str]] = {}
    item_labels_decided_ab: Dict[str, List[str]] = {}
    item_judge_ids: Dict[str, Dict[str, int]] = {}
    judge_id_counts: Dict[str, int] = {}
    model_pair_label_counts: Dict[str, Dict[str, int]] = {}
    tmpl_label_counts: Dict[str, Dict[str, int]] = {}
    fam_label_counts: Dict[str, Dict[str, int]] = {}
    pair_label_counts: Dict[str, Dict[str, int]] = {}
    tmpl_item_labels: Dict[str, Dict[str, List[str]]] = {}
    fam_item_labels: Dict[str, Dict[str, List[str]]] = {}
    pair_item_labels: Dict[str, Dict[str, List[str]]] = {}
    tmpl_item_labels_decided_ab: Dict[str, Dict[str, List[str]]] = {}
    fam_item_labels_decided_ab: Dict[str, Dict[str, List[str]]] = {}
    pair_item_labels_decided_ab: Dict[str, Dict[str, List[str]]] = {}
    judge_in_tokens: List[float] = []
    judge_out_tokens: List[float] = []
    judge_latency_ms: List[float] = []
    parse_valid_true = 0
    parse_valid_false = 0
    judge_task_family_present = 0
    judge_prompt_template_present = 0
    judge_family_template_pair_present = 0
    for c in judge_pairs:
        _inc(label_counts, c.label)
        _inc(judge_id_counts, c.judge_id)
        if c.a_model_id != "" or c.b_model_id != "":
            pair_key = f"{c.a_model_id}|{c.b_model_id}"
            model_pair_label_counts.setdefault(pair_key, {})
            _inc(model_pair_label_counts[pair_key], c.label)
        pv = c.raw.get("parse_valid", None)
        if isinstance(pv, bool):
            if pv:
                parse_valid_true += 1
            else:
                parse_valid_false += 1
        toks = c.raw.get("tokens", None)
        if isinstance(toks, dict):
            ji = lib.get_int(toks, "judge_in", "judge_input", "judge_prompt", "in")
            jo = lib.get_int(toks, "judge_out", "judge_output", "judge_completion", "out")
            if ji is not None:
                judge_in_tokens.append(float(ji))
            if jo is not None:
                judge_out_tokens.append(float(jo))
        lats = c.raw.get("latency_ms", None)
        if isinstance(lats, dict):
            jl = lib.get_float(lats, "judge", "judge_ms", "judge_latency_ms")
            if jl is not None:
                judge_latency_ms.append(float(jl))
        item = c.item_id
        if item == "":
            item = lib.make_item_id(c.task_id, c.prompt_template_id, c.a_model_id, c.b_model_id)
        item_labels.setdefault(item, []).append(c.label)
        if item != "" and c.judge_id != "":
            item_judge_ids.setdefault(item, {})
            item_judge_ids[item][c.judge_id] = item_judge_ids[item].get(c.judge_id, 0) + 1
        if c.label in ("a", "b"):
            item_labels_decided_ab.setdefault(item, []).append(c.label)

        tmpl = c.prompt_template_id
        fam = c.task_family
        fam_tmpl = "" if (fam == "" or tmpl == "") else f"{fam}|{tmpl}"
        if fam != "":
            judge_task_family_present += 1
        if tmpl != "":
            judge_prompt_template_present += 1
        if fam_tmpl != "":
            judge_family_template_pair_present += 1
        if tmpl != "":
            tmpl_label_counts.setdefault(tmpl, {})
            _inc(tmpl_label_counts[tmpl], c.label)
            tmpl_item_labels.setdefault(tmpl, {})
            tmpl_item_labels[tmpl].setdefault(item, []).append(c.label)
            if c.label in ("a", "b"):
                tmpl_item_labels_decided_ab.setdefault(tmpl, {})
                tmpl_item_labels_decided_ab[tmpl].setdefault(item, []).append(c.label)
        if fam != "":
            fam_label_counts.setdefault(fam, {})
            _inc(fam_label_counts[fam], c.label)
            fam_item_labels.setdefault(fam, {})
            fam_item_labels[fam].setdefault(item, []).append(c.label)
            if c.label in ("a", "b"):
                fam_item_labels_decided_ab.setdefault(fam, {})
                fam_item_labels_decided_ab[fam].setdefault(item, []).append(c.label)
        if fam_tmpl != "":
            pair_label_counts.setdefault(fam_tmpl, {})
            _inc(pair_label_counts[fam_tmpl], c.label)
            pair_item_labels.setdefault(fam_tmpl, {})
            pair_item_labels[fam_tmpl].setdefault(item, []).append(c.label)
            if c.label in ("a", "b"):
                pair_item_labels_decided_ab.setdefault(fam_tmpl, {})
                pair_item_labels_decided_ab[fam_tmpl].setdefault(item, []).append(c.label)

    item_disagreements: List[float] = []
    for labs in item_labels.values():
        if len(labs) >= 2:
            item_disagreements.append(_majority_disagreement(labs))
    disagreement_rate = 0.0 if len(item_disagreements) == 0 else (sum(item_disagreements) / float(len(item_disagreements)))

    item_disagreements_decided_ab: List[float] = []
    for labs in item_labels_decided_ab.values():
        if len(labs) >= 2:
            item_disagreements_decided_ab.append(_majority_disagreement(labs))
    disagreement_rate_decided_ab = 0.0 if len(item_disagreements_decided_ab) == 0 else (sum(item_disagreements_decided_ab) / float(len(item_disagreements_decided_ab)))

    item_disagreement_top: List[Dict[str, Any]] = []
    for item_id, labs in item_labels.items():
        if len(labs) < 2:
            continue
        counts: Dict[str, int] = {}
        for lab in labs:
            _inc(counts, lab)
        labs_ab = item_labels_decided_ab.get(item_id, [])
        dis_all = _majority_disagreement(labs)
        dis_ab = 0.0 if len(labs_ab) < 2 else _majority_disagreement(labs_ab)
        decided_ab = sum(counts.get(k, 0) for k in ("a", "b"))
        item_disagreement_top.append({
            "item_id": item_id,
            "count": len(labs),
            "label_counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "judge_id_unique": len(item_judge_ids.get(item_id, {})),
            "disagreement_rate": dis_all,
            "decided_count_ab": decided_ab,
            "disagreement_rate_decided_ab": dis_ab,
        })
    item_disagreement_top.sort(key=lambda x: (-float(x.get("disagreement_rate", 0.0)), -int(x.get("count", 0)), str(x.get("item_id", ""))))
    item_disagreement_top = item_disagreement_top[:20]

    reuse_count = sum(1 for v in buffer_items.values() if v >= 2)
    reuse_events = sum(max(0, v - 1) for v in buffer_items.values())
    totals = {
        "records_total": len(canon),
        "task_run_records": len(task_runs),
        "judge_pair_records": len(judge_pairs),
        "unknown_records": unknown,
    }

    diversity = {
        "task_id": _div_stats(task_id_counts),
        "task_family": _div_stats(task_family_counts),
        "prompt_template_id": _div_stats(template_counts),
        "task_family_template_pair": _div_stats(family_template_counts),
        "task_id_template_pair": _div_stats(task_template_counts),
        "model_id": _div_stats(model_counts),
        "answer": _div_stats(answers),
        "tags": _div_stats(tag_counts),
    }
    ans = diversity.get("answer") or {}
    ans.update({
        "nonempty_task_runs": int(answer_task_runs_nonempty),
        "nonempty_task_run_rate": 0.0 if len(task_runs) == 0 else (float(answer_task_runs_nonempty) / float(len(task_runs))),
        "extracted_task_runs": int(answer_task_runs_extracted),
        "extracted_task_run_rate": 0.0 if len(task_runs) == 0 else (float(answer_task_runs_extracted) / float(len(task_runs))),
        "extracted_rate_among_nonempty": 0.0 if answer_task_runs_nonempty == 0 else (float(answer_task_runs_extracted) / float(answer_task_runs_nonempty)),
        "source_counts": dict(sorted(answer_source_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
    })
    diversity["answer"] = ans

    word_counts: Dict[str, int] = {}
    for w in out_words:
        word_counts[w] = word_counts.get(w, 0) + 1
    prompt_word_counts: Dict[str, int] = {}
    for w in prompt_words:
        prompt_word_counts[w] = prompt_word_counts.get(w, 0) + 1
    prompt_2gram_total = int(sum(prompt_2grams.values()))
    prompt_3gram_total = int(sum(prompt_3grams.values()))
    prompt_char3_total = int(sum(prompt_char3.values()))
    out_2gram_total = int(sum(out_2grams.values()))
    out_3gram_total = int(sum(out_3grams.values()))
    out_char3_total = int(sum(out_char3.values()))
    tokens = {
        "prompt_chars": _len_stats(prompt_len_chars),
        "prompt_words": _len_stats(prompt_len_words),
        "output_chars": _len_stats(output_len_chars),
        "output_words": _len_stats(output_len_words),
        "input_tokens": _num_stats(input_tokens),
        "output_tokens": _num_stats(output_tokens),
        "wall_ms": _num_stats(wall_ms),
        "ms_per_output_token": _num_stats(ms_per_output_token),
        "output_tok_per_s": _num_stats(output_tok_per_s),
        "total_tok_per_s": _num_stats(total_tok_per_s),
        "input_tokens_present_task_runs": int(input_tokens_present),
        "input_tokens_present_task_run_rate": 0.0 if len(task_runs) == 0 else (float(input_tokens_present) / float(len(task_runs))),
        "output_tokens_present_task_runs": int(output_tokens_present),
        "output_tokens_present_task_run_rate": 0.0 if len(task_runs) == 0 else (float(output_tokens_present) / float(len(task_runs))),
        "wall_ms_present_task_runs": int(wall_ms_present),
        "wall_ms_present_task_run_rate": 0.0 if len(task_runs) == 0 else (float(wall_ms_present) / float(len(task_runs))),
        "prompt_words_total": len(prompt_words),
        "prompt_words_unique": len(prompt_word_counts),
        "prompt_distinct_1": _distinct_ratio(prompt_word_counts),
        "prompt_top_word_frac": 0.0 if len(prompt_words) == 0 else (float(max(prompt_word_counts.values())) / float(len(prompt_words))),
        "prompt_word_entropy_bits": lib.shannon_entropy(prompt_word_counts),
        "prompt_word_top": lib.top_counts(prompt_word_counts),
        "prompt_2gram_total": prompt_2gram_total,
        "prompt_2gram_unique": len(prompt_2grams),
        "prompt_distinct_2": _distinct_ratio(prompt_2grams),
        "prompt_2gram_entropy_bits": lib.shannon_entropy(prompt_2grams),
        "prompt_2gram_top": lib.top_counts(prompt_2grams),
        "prompt_3gram_total": prompt_3gram_total,
        "prompt_3gram_unique": len(prompt_3grams),
        "prompt_distinct_3": _distinct_ratio(prompt_3grams),
        "prompt_3gram_entropy_bits": lib.shannon_entropy(prompt_3grams),
        "prompt_3gram_top": lib.top_counts(prompt_3grams),
        "prompt_char_3gram_total": prompt_char3_total,
        "prompt_char_3gram_unique": len(prompt_char3),
        "prompt_char_distinct_3": _distinct_ratio(prompt_char3),
        "prompt_char_3gram_entropy_bits": lib.shannon_entropy(prompt_char3),
        "prompt_char_3gram_top": lib.top_counts(prompt_char3),
        "output_words_total": len(out_words),
        "output_words_unique": len(word_counts),
        "output_distinct_1": _distinct_ratio(word_counts),
        "output_top_word_frac": 0.0 if len(out_words) == 0 else (float(max(word_counts.values())) / float(len(out_words))),
        "output_word_entropy_bits": lib.shannon_entropy(word_counts),
        "output_word_top": lib.top_counts(word_counts),
        "output_2gram_total": out_2gram_total,
        "output_2gram_unique": len(out_2grams),
        "output_distinct_2": _distinct_ratio(out_2grams),
        "output_2gram_entropy_bits": lib.shannon_entropy(out_2grams),
        "output_2gram_top": lib.top_counts(out_2grams),
        "output_3gram_total": out_3gram_total,
        "output_3gram_unique": len(out_3grams),
        "output_distinct_3": _distinct_ratio(out_3grams),
        "output_3gram_entropy_bits": lib.shannon_entropy(out_3grams),
        "output_3gram_top": lib.top_counts(out_3grams),
        "output_char_3gram_total": out_char3_total,
        "output_char_3gram_unique": len(out_char3),
        "output_char_distinct_3": _distinct_ratio(out_char3),
        "output_char_3gram_entropy_bits": lib.shannon_entropy(out_char3),
        "output_char_3gram_top": lib.top_counts(out_char3),
    }

    duplicates = {
        "output_exact_dup_rate": _dup_rate(outputs_exact),
        "output_norm_dup_rate": _dup_rate(outputs_norm),
        "prompt_norm_dup_rate": _dup_rate(prompts_norm),
        "answer_dup_rate": _dup_rate(answers_nonempty),
    }

    task_template_dup_rates: List[float] = []
    for outs in task_template_outputs_norm.values():
        if len(outs) >= 2:
            task_template_dup_rates.append(_dup_rate(outs))
    duplicates.update({
        "task_template_groups_ge2": sum(1 for outs in task_template_outputs_norm.values() if len(outs) >= 2),
        "task_template_output_norm_dup_rate_mean": 0.0 if len(task_template_dup_rates) == 0 else (sum(task_template_dup_rates) / float(len(task_template_dup_rates))),
        "task_template_output_norm_dup_rate_max": 0.0 if len(task_template_dup_rates) == 0 else max(task_template_dup_rates),
        "task_template_output_norm_dup_rate_top": _task_template_dup_rate_top(task_template_outputs_norm, k=20),
    })

    pair_summary: Dict[str, Any] = {}
    for pair_key, counts in model_pair_label_counts.items():
        pair_summary[pair_key] = {
            "count": sum(counts.values()),
            "label_counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "label_entropy_bits": lib.shannon_entropy(counts),
        }

    wins_a = label_counts.get("a", 0)
    wins_b = label_counts.get("b", 0)
    decided = wins_a + wins_b
    ties = label_counts.get("tie", 0)
    invalid = label_counts.get("invalid", 0)
    imbalance_ab = 0.0 if decided == 0 else (abs(float(wins_a - wins_b)) / float(decided))
    balance_ab = 1.0 - imbalance_ab

    model_pair_top: List[Dict[str, Any]] = []
    for pair_key, js in pair_summary.items():
        counts = js.get("label_counts") or {}
        wins_a_p = int(counts.get("a", 0))
        wins_b_p = int(counts.get("b", 0))
        decided_p = wins_a_p + wins_b_p
        imb_p = 0.0 if decided_p == 0 else (abs(float(wins_a_p - wins_b_p)) / float(decided_p))
        bal_p = 1.0 - imb_p
        model_pair_top.append({
            "pair_key": pair_key,
            "count": js.get("count", 0),
            "label_entropy_bits": js.get("label_entropy_bits", 0.0),
            "label_counts": counts,
            "decided_count_ab": decided_p,
            "label_balance_ab": bal_p,
            "label_imbalance_ab": imb_p,
        })
    model_pair_top.sort(key=lambda x: (-int(x.get("count", 0)), str(x.get("pair_key", ""))))
    model_pair_top = model_pair_top[:20]

    tmpl_summ: List[Dict[str, Any]] = []
    for tmpl, counts in tmpl_label_counts.items():
        stats = _judge_slice_stats(counts, tmpl_item_labels.get(tmpl, {}), tmpl_item_labels_decided_ab.get(tmpl, {}))
        stats["prompt_template_id"] = tmpl
        tmpl_summ.append(stats)
    tmpl_summ.sort(key=lambda x: (-int(x.get("count", 0) or 0), str(x.get("prompt_template_id", ""))))

    fam_summ: List[Dict[str, Any]] = []
    for fam, counts in fam_label_counts.items():
        stats = _judge_slice_stats(counts, fam_item_labels.get(fam, {}), fam_item_labels_decided_ab.get(fam, {}))
        stats["task_family"] = fam
        fam_summ.append(stats)
    fam_summ.sort(key=lambda x: (-int(x.get("count", 0) or 0), str(x.get("task_family", ""))))

    fam_tmpl_summ: List[Dict[str, Any]] = []
    for fam_tmpl, counts in pair_label_counts.items():
        stats = _judge_slice_stats(counts, pair_item_labels.get(fam_tmpl, {}), pair_item_labels_decided_ab.get(fam_tmpl, {}))
        stats["task_family_template_pair"] = fam_tmpl
        fam_tmpl_summ.append(stats)
    fam_tmpl_summ.sort(key=lambda x: (-int(x.get("count", 0) or 0), str(x.get("task_family_template_pair", ""))))

    judge_slices = {
        "by_prompt_template_id": {
            "count_top": tmpl_summ[:20],
            "imbalance_ab_top": _judge_slice_top(tmpl_summ, "prompt_template_id", "label_imbalance_ab", k=10),
            "low_balance_ab_top": _judge_slice_low(tmpl_summ, "prompt_template_id", "label_balance_ab", k=10),
            "disagreement_top": _judge_slice_top(tmpl_summ, "prompt_template_id", "disagreement_rate", k=10),
        },
        "by_task_family": {
            "count_top": fam_summ[:20],
            "imbalance_ab_top": _judge_slice_top(fam_summ, "task_family", "label_imbalance_ab", k=10),
            "low_balance_ab_top": _judge_slice_low(fam_summ, "task_family", "label_balance_ab", k=10),
            "disagreement_top": _judge_slice_top(fam_summ, "task_family", "disagreement_rate", k=10),
        },
        "by_task_family_template_pair": {
            "count_top": fam_tmpl_summ[:20],
            "imbalance_ab_top": _judge_slice_top(fam_tmpl_summ, "task_family_template_pair", "label_imbalance_ab", k=10),
            "low_balance_ab_top": _judge_slice_low(fam_tmpl_summ, "task_family_template_pair", "label_balance_ab", k=10),
            "disagreement_top": _judge_slice_top(fam_tmpl_summ, "task_family_template_pair", "disagreement_rate", k=10),
        },
    }
    judge_out_budget_target = 64.0
    judge_out_budget_le_target = sum(1 for x in judge_out_tokens if x <= judge_out_budget_target)

    judge = {
        "label_counts": dict(sorted(label_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "label_entropy_bits": lib.shannon_entropy(label_counts),
        "pair_item_count": len(item_labels),
        "item_disagreement_top": item_disagreement_top,
        "disagreement_rate": disagreement_rate,
        "disagreement_rate_decided_ab": disagreement_rate_decided_ab,
        "decided_count_ab": decided,
        "decided_rate_ab": _safe_div(float(decided), float(len(judge_pairs))),
        "tie_rate": _safe_div(float(ties), float(len(judge_pairs))),
        "invalid_rate": _safe_div(float(invalid), float(len(judge_pairs))),
        "label_balance_ab": balance_ab,
        "label_imbalance_ab": imbalance_ab,
        "parse_valid_true": parse_valid_true,
        "parse_valid_false": parse_valid_false,
        "parse_valid_rate": _safe_div(float(parse_valid_true), float(parse_valid_true + parse_valid_false)),
        "judge_in_tokens": _num_stats(judge_in_tokens),
        "judge_out_tokens": _num_stats(judge_out_tokens),
        "judge_latency_ms": _num_stats(judge_latency_ms),
        "judge_out_budget_target": judge_out_budget_target,
        "judge_out_budget_le_target": judge_out_budget_le_target,
        "judge_out_budget_le_target_rate": _safe_div(float(judge_out_budget_le_target), float(len(judge_out_tokens))),
        "task_family_nonempty_judge_pairs": int(judge_task_family_present),
        "task_family_nonempty_judge_pair_rate": 0.0 if len(judge_pairs) == 0 else (float(judge_task_family_present) / float(len(judge_pairs))),
        "prompt_template_id_nonempty_judge_pairs": int(judge_prompt_template_present),
        "prompt_template_id_nonempty_judge_pair_rate": 0.0 if len(judge_pairs) == 0 else (float(judge_prompt_template_present) / float(len(judge_pairs))),
        "task_family_template_pair_nonempty_judge_pairs": int(judge_family_template_pair_present),
        "task_family_template_pair_nonempty_judge_pair_rate": 0.0 if len(judge_pairs) == 0 else (float(judge_family_template_pair_present) / float(len(judge_pairs))),
        "judge_id_unique": len([k for k in judge_id_counts.keys() if k != ""]),
        "judge_id_top": lib.top_counts(judge_id_counts),
        "model_pair_count": len(pair_summary),
        "model_pair_summary": pair_summary,
        "model_pair_top": model_pair_top,
        "slices": judge_slices,
    }

    reuse = {
        "buffer_id_nonempty_task_runs": int(buffer_id_present),
        "buffer_id_nonempty_task_run_rate": 0.0 if len(task_runs) == 0 else (float(buffer_id_present) / float(len(task_runs))),
        "buffer_item_id_nonempty_task_runs": int(buffer_item_id_present),
        "buffer_item_id_nonempty_task_run_rate": 0.0 if len(task_runs) == 0 else (float(buffer_item_id_present) / float(len(task_runs))),
        "buffer_id_unique": len(buffer_ids),
        "buffer_id_hhi": _hhi(buffer_ids),
        "buffer_id_entropy_bits": lib.shannon_entropy(buffer_ids),
        "buffer_id_top": lib.top_counts(buffer_ids),
        "buffer_item_id_unique": len(buffer_items),
        "buffer_item_id_reused_unique": reuse_count,
        "buffer_item_reuse_rate_unique": 0.0 if len(buffer_items) == 0 else (float(reuse_count) / float(len(buffer_items))),
        "buffer_item_reuse_events": reuse_events,
        "buffer_item_reuse_event_rate": 0.0 if len(task_runs) == 0 else (float(reuse_events) / float(len(task_runs))),
        "buffer_item_hhi": _hhi(buffer_items),
        "buffer_item_entropy_bits": lib.shannon_entropy(buffer_items),
        "buffer_item_top": lib.top_counts(buffer_items),
    }

    useful_novelty = {
        "flagged_task_runs": novelty_flagged,
        "flagged_task_run_rate": 0.0 if len(task_runs) == 0 else (float(novelty_flagged) / float(len(task_runs))),
        "flag_counts": dict(sorted(novelty_flag_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "flagged_rate_by_prompt_template_id_top": _rate_top(template_task_total, template_task_flagged, "prompt_template_id", k=10),
        "flagged_rate_by_task_family_top": _rate_top(family_task_total, family_task_flagged, "task_family", k=10),
        "flagged_rate_by_family_template_top": _rate_top(pair_task_total, pair_task_flagged, "task_family_template_pair", k=10),
        "flagged_rate_by_model_id_top": _rate_top(model_task_total, model_task_flagged, "model_id", k=10),
    }

    duplicates.update({
        "output_norm_dup_rate_by_prompt_template_id_top": _dup_rate_top(template_out_total, template_out_uniq, "prompt_template_id", k=10),
        "output_norm_dup_rate_by_family_template_top": _dup_rate_top(pair_out_total, pair_out_uniq, "task_family_template_pair", k=10),
        "output_norm_dup_rate_by_model_id_top": _dup_rate_top(model_out_total, model_out_uniq, "model_id", k=10),
    })

    return(MetricsReport(
        totals=totals,
        diversity=diversity,
        tokens=tokens,
        duplicates=duplicates,
        judge=judge,
        reuse=reuse,
        useful_novelty=useful_novelty,
        runs=_runs_block(task_runs),
    ))


def _md_list_top(items: Sequence[Tuple[str, int]], k: int = 10) -> str:
    lines: List[str] = []
    for key, c in items[:k]:
        lines.append(f"- `{key}`: {c}")
    return("\n".join(lines))

def _md_model_pair_top(items: Sequence[Dict[str, Any]], k: int = 10) -> str:
    lines: List[str] = []
    for js in list(items)[:k]:
        pair = str(js.get("pair_key", ""))
        count = int(js.get("count", 0))
        decided_ab = int(js.get("decided_count_ab", 0))
        bal = float(js.get("label_balance_ab", 0.0))
        imb = float(js.get("label_imbalance_ab", 0.0))
        counts = js.get("label_counts") or {}
        lines.append(f"- `{pair}`: count={count} decided_ab={decided_ab} balance_ab={bal:.6f} imbalance_ab={imb:.6f} labels={counts}")
    return("\n".join(lines))

def _md_item_disagreement_top(items: Sequence[Dict[str, Any]], k: int = 10) -> str:
    lines: List[str] = []
    for js in list(items)[:k]:
        item_id = str(js.get("item_id", ""))
        count = int(js.get("count", 0))
        judges = int(js.get("judge_id_unique", 0))
        dis = float(js.get("disagreement_rate", 0.0))
        dis_ab = float(js.get("disagreement_rate_decided_ab", 0.0))
        decided_ab = int(js.get("decided_count_ab", 0))
        counts = js.get("label_counts") or {}
        lines.append(f"- `{item_id}`: count={count} judges={judges} disagree={dis:.6f} disagree_ab={dis_ab:.6f} decided_ab={decided_ab} labels={counts}")
    return("\n".join(lines))

def _md_judge_slice_top(items: Sequence[Dict[str, Any]], key_name: str, k: int = 10) -> str:
    lines: List[str] = []
    for js in list(items)[:k]:
        key = str(js.get(key_name, ""))
        if key == "":
            continue
        count = int(js.get("count", 0) or 0)
        bal = float(js.get("label_balance_ab", 0.0) or 0.0)
        imb = float(js.get("label_imbalance_ab", 0.0) or 0.0)
        dis = float(js.get("disagreement_rate", 0.0) or 0.0)
        dis_ab = float(js.get("disagreement_rate_decided_ab", 0.0) or 0.0)
        decided = float(js.get("decided_rate_ab", 0.0) or 0.0)
        counts = js.get("label_counts") or {}
        lines.append(f"- `{key}`: count={count} balance_ab={bal:.6f} imbalance_ab={imb:.6f} disagree={dis:.6f} disagree_ab={dis_ab:.6f} decided_rate_ab={decided:.6f} labels={counts}")
    return("\n".join(lines))


def to_markdown(report: MetricsReport) -> str:
    parts: List[str] = []
    parts.append("# Entropy Buffer Metrics\n")
    parts.append("## Totals\n")
    for k, v in report.totals.items():
        parts.append(f"- `{k}`: {v}")
    parts.append("\n## Runs\n")
    parts.append(f"- `run_id_unique`: {int(report.runs.get('run_id_unique', 0) or 0)}")
    parts.append("\n### low_pair_entropy_norm_by_run_id_top\n")
    for js in (report.runs.get("low_pair_entropy_norm_by_run_id_top") or [])[:10]:
        parts.append(f"- `{js.get('run_id')}`: entropy_norm={float(js.get('task_family_template_pair_entropy_norm', 0.0)):.6f} count={int(js.get('count', 0))}")
    parts.append("\n### output_norm_dup_rate_by_run_id_top\n")
    for js in (report.runs.get("output_norm_dup_rate_by_run_id_top") or [])[:10]:
        parts.append(f"- `{js.get('run_id')}`: dup_rate={float(js.get('output_norm_dup_rate', 0.0)):.6f} count={int(js.get('count', 0))}")
    parts.append("\n### flagged_task_run_rate_by_run_id_top\n")
    for js in (report.runs.get("flagged_task_run_rate_by_run_id_top") or [])[:10]:
        parts.append(f"- `{js.get('run_id')}`: flagged_rate={float(js.get('flagged_task_run_rate', 0.0)):.6f} count={int(js.get('count', 0))}")
    parts.append("\n## Diversity\n")
    for field, js in report.diversity.items():
        parts.append(f"### {field}\n")
        parts.append(f"- `unique`: {js.get('unique')}")
        parts.append(f"- `entropy_bits`: {js.get('entropy_bits'):.6f}")
        parts.append(f"- `entropy_norm`: {js.get('entropy_norm'):.6f}")
        parts.append(f"- `effective_num`: {js.get('effective_num'):.6f}")
        top = js.get("top") or []
        parts.append(_md_list_top(top))
    parts.append("")
    parts.append("\n## Tokens\n")
    for k in ("prompt_chars", "prompt_words", "output_chars", "output_words", "input_tokens", "output_tokens", "wall_ms", "ms_per_output_token", "output_tok_per_s", "total_tok_per_s"):
        stats = report.tokens.get(k) or {}
        parts.append(f"### {k}\n")
        for sk in ("count", "min", "max", "mean", "p50", "p90"):
            v = stats.get(sk)
            if isinstance(v, float):
                parts.append(f"- `{sk}`: {v:.6f}")
            else:
                parts.append(f"- `{sk}`: {v}")
        parts.append("")
    for field in (
        "input_tokens_present_task_runs",
        "input_tokens_present_task_run_rate",
        "output_tokens_present_task_runs",
        "output_tokens_present_task_run_rate",
        "wall_ms_present_task_runs",
        "wall_ms_present_task_run_rate",
        "prompt_words_total",
        "prompt_words_unique",
        "prompt_distinct_1",
        "prompt_top_word_frac",
        "prompt_word_entropy_bits",
        "prompt_2gram_total",
        "prompt_2gram_unique",
        "prompt_distinct_2",
        "prompt_2gram_entropy_bits",
        "prompt_3gram_total",
        "prompt_3gram_unique",
        "prompt_distinct_3",
        "prompt_3gram_entropy_bits",
        "prompt_char_3gram_total",
        "prompt_char_3gram_unique",
        "prompt_char_distinct_3",
        "prompt_char_3gram_entropy_bits",
        "output_words_total",
        "output_words_unique",
        "output_distinct_1",
        "output_top_word_frac",
        "output_word_entropy_bits",
        "output_2gram_total",
        "output_2gram_unique",
        "output_distinct_2",
        "output_2gram_entropy_bits",
        "output_3gram_total",
        "output_3gram_unique",
        "output_distinct_3",
        "output_3gram_entropy_bits",
        "output_char_3gram_total",
        "output_char_3gram_unique",
        "output_char_distinct_3",
        "output_char_3gram_entropy_bits",
    ):
        v = report.tokens.get(field)
        if isinstance(v, float):
            parts.append(f"- `{field}`: {v:.6f}")
        else:
            parts.append(f"- `{field}`: {v}")
    parts.append("\n### prompt_word_top\n")
    parts.append(_md_list_top(report.tokens.get("prompt_word_top", [])))
    parts.append("\n### prompt_2gram_top\n")
    parts.append(_md_list_top(report.tokens.get("prompt_2gram_top", [])))
    parts.append("\n### prompt_3gram_top\n")
    parts.append(_md_list_top(report.tokens.get("prompt_3gram_top", [])))
    parts.append("\n### prompt_char_3gram_top\n")
    parts.append(_md_list_top(report.tokens.get("prompt_char_3gram_top", [])))
    parts.append("\n### output_word_top\n")
    parts.append(_md_list_top(report.tokens.get("output_word_top", [])))
    parts.append("\n### output_2gram_top\n")
    parts.append(_md_list_top(report.tokens.get("output_2gram_top", [])))
    parts.append("\n### output_3gram_top\n")
    parts.append(_md_list_top(report.tokens.get("output_3gram_top", [])))
    parts.append("\n### output_char_3gram_top\n")
    parts.append(_md_list_top(report.tokens.get("output_char_3gram_top", [])))
    parts.append("\n## Duplicates\n")
    for k, v in report.duplicates.items():
        if isinstance(v, list):
            continue
        if isinstance(v, float):
            parts.append(f"- `{k}`: {v:.6f}")
        else:
            parts.append(f"- `{k}`: {v}")
    parts.append("\n### output_norm_dup_rate_by_prompt_template_id_top\n")
    for js in report.duplicates.get("output_norm_dup_rate_by_prompt_template_id_top", [])[:10]:
        parts.append(f"- `{js.get('prompt_template_id')}`: dup_rate={float(js.get('dup_rate', 0.0)):.6f} count={int(js.get('count', 0))} unique={int(js.get('unique', 0))}")
    parts.append("\n### output_norm_dup_rate_by_family_template_top\n")
    for js in report.duplicates.get("output_norm_dup_rate_by_family_template_top", [])[:10]:
        parts.append(f"- `{js.get('task_family_template_pair')}`: dup_rate={float(js.get('dup_rate', 0.0)):.6f} count={int(js.get('count', 0))} unique={int(js.get('unique', 0))}")
    parts.append("\n### task_template_output_norm_dup_rate_top\n")
    for js in report.duplicates.get("task_template_output_norm_dup_rate_top", [])[:10]:
        parts.append(f"- `{js.get('task_id')}` `{js.get('prompt_template_id')}`: dup_rate={float(js.get('dup_rate', 0.0)):.6f} count={int(js.get('count', 0))} unique={int(js.get('unique', 0))}")
    parts.append("\n### output_norm_dup_rate_by_model_id_top\n")
    for js in report.duplicates.get("output_norm_dup_rate_by_model_id_top", [])[:10]:
        parts.append(f"- `{js.get('model_id')}`: dup_rate={float(js.get('dup_rate', 0.0)):.6f} count={int(js.get('count', 0))} unique={int(js.get('unique', 0))}")
    parts.append("\n## Judge\n")
    parts.append(f"- `label_entropy_bits`: {report.judge.get('label_entropy_bits'):.6f}")
    parts.append(f"- `pair_item_count`: {report.judge.get('pair_item_count')}")
    parts.append(f"- `disagreement_rate`: {report.judge.get('disagreement_rate'):.6f}")
    parts.append(f"- `disagreement_rate_decided_ab`: {report.judge.get('disagreement_rate_decided_ab'):.6f}")
    parts.append(f"- `decided_rate_ab`: {report.judge.get('decided_rate_ab'):.6f}")
    parts.append(f"- `tie_rate`: {report.judge.get('tie_rate'):.6f}")
    parts.append(f"- `invalid_rate`: {report.judge.get('invalid_rate'):.6f}")
    parts.append(f"- `label_balance_ab`: {report.judge.get('label_balance_ab'):.6f}")
    parts.append(f"- `task_family_nonempty_judge_pair_rate`: {float(report.judge.get('task_family_nonempty_judge_pair_rate', 0.0) or 0.0):.6f}")
    parts.append(f"- `prompt_template_id_nonempty_judge_pair_rate`: {float(report.judge.get('prompt_template_id_nonempty_judge_pair_rate', 0.0) or 0.0):.6f}")
    parts.append(f"- `task_family_template_pair_nonempty_judge_pair_rate`: {float(report.judge.get('task_family_template_pair_nonempty_judge_pair_rate', 0.0) or 0.0):.6f}")
    parts.append(f"- `parse_valid_true`: {int(report.judge.get('parse_valid_true', 0) or 0)}")
    parts.append(f"- `parse_valid_false`: {int(report.judge.get('parse_valid_false', 0) or 0)}")
    parts.append(f"- `parse_valid_rate`: {float(report.judge.get('parse_valid_rate', 0.0) or 0.0):.6f}")
    parts.append(f"- `judge_out_budget_target`: {float(report.judge.get('judge_out_budget_target', 0.0) or 0.0):.6f}")
    parts.append(f"- `judge_out_budget_le_target`: {int(report.judge.get('judge_out_budget_le_target', 0) or 0)}")
    parts.append(f"- `judge_out_budget_le_target_rate`: {float(report.judge.get('judge_out_budget_le_target_rate', 0.0) or 0.0):.6f}")
    parts.append("\n### judge_in_tokens\n")
    for sk in ("count", "min", "max", "mean", "p50", "p90"):
        v = (report.judge.get("judge_in_tokens") or {}).get(sk)
        if isinstance(v, float):
            parts.append(f"- `{sk}`: {v:.6f}")
        else:
            parts.append(f"- `{sk}`: {v}")
    parts.append("\n### judge_out_tokens\n")
    for sk in ("count", "min", "max", "mean", "p50", "p90"):
        v = (report.judge.get("judge_out_tokens") or {}).get(sk)
        if isinstance(v, float):
            parts.append(f"- `{sk}`: {v:.6f}")
        else:
            parts.append(f"- `{sk}`: {v}")
    parts.append("\n### judge_latency_ms\n")
    for sk in ("count", "min", "max", "mean", "p50", "p90"):
        v = (report.judge.get("judge_latency_ms") or {}).get(sk)
        if isinstance(v, float):
            parts.append(f"- `{sk}`: {v:.6f}")
        else:
            parts.append(f"- `{sk}`: {v}")
    parts.append("\n### label_counts\n")
    for k, v in report.judge.get("label_counts", {}).items():
        parts.append(f"- `{k}`: {v}")
    parts.append("\n### judge_id_top\n")
    parts.append(_md_list_top(report.judge.get("judge_id_top", [])))
    parts.append("\n### model_pair_top\n")
    parts.append(_md_model_pair_top(report.judge.get("model_pair_top", [])))
    parts.append("\n### item_disagreement_top\n")
    parts.append(_md_item_disagreement_top(report.judge.get("item_disagreement_top", [])))
    slices = report.judge.get("slices") or {}
    by_tmpl = (slices.get("by_prompt_template_id") or {})
    by_fam = (slices.get("by_task_family") or {})
    by_pair = (slices.get("by_task_family_template_pair") or {})
    parts.append("\n### slices.by_prompt_template_id.imbalance_ab_top\n")
    parts.append(_md_judge_slice_top(by_tmpl.get("imbalance_ab_top", []), "prompt_template_id"))
    parts.append("\n### slices.by_prompt_template_id.disagreement_top\n")
    parts.append(_md_judge_slice_top(by_tmpl.get("disagreement_top", []), "prompt_template_id"))
    parts.append("\n### slices.by_task_family_template_pair.imbalance_ab_top\n")
    parts.append(_md_judge_slice_top(by_pair.get("imbalance_ab_top", []), "task_family_template_pair"))
    parts.append("\n### slices.by_task_family_template_pair.disagreement_top\n")
    parts.append(_md_judge_slice_top(by_pair.get("disagreement_top", []), "task_family_template_pair"))
    parts.append("\n## Buffer reuse\n")
    for k in ("buffer_id_nonempty_task_run_rate", "buffer_item_id_nonempty_task_run_rate", "buffer_id_unique", "buffer_id_hhi", "buffer_id_entropy_bits", "buffer_item_id_unique", "buffer_item_id_reused_unique", "buffer_item_reuse_rate_unique", "buffer_item_reuse_events", "buffer_item_reuse_event_rate", "buffer_item_hhi", "buffer_item_entropy_bits"):
        v = report.reuse.get(k)
        if isinstance(v, float):
            parts.append(f"- `{k}`: {v:.6f}")
        else:
            parts.append(f"- `{k}`: {v}")
    parts.append("\n### buffer_id_top\n")
    parts.append(_md_list_top(report.reuse.get("buffer_id_top", [])))
    parts.append("\n### buffer_item_top\n")
    parts.append(_md_list_top(report.reuse.get("buffer_item_top", [])))
    parts.append("\n## Useful novelty flags\n")
    parts.append(f"- `flagged_task_run_rate`: {report.useful_novelty.get('flagged_task_run_rate'):.6f}")
    parts.append("\n### flag_counts\n")
    for k, v in report.useful_novelty.get("flag_counts", {}).items():
        parts.append(f"- `{k}`: {v}")
    parts.append("\n### flagged_rate_by_prompt_template_id_top\n")
    for js in report.useful_novelty.get("flagged_rate_by_prompt_template_id_top", [])[:10]:
        parts.append(f"- `{js.get('prompt_template_id')}`: flagged_rate={float(js.get('flagged_rate', 0.0)):.6f} count={int(js.get('count', 0))} flagged={int(js.get('flagged', 0))}")
    parts.append("\n### flagged_rate_by_task_family_top\n")
    for js in report.useful_novelty.get("flagged_rate_by_task_family_top", [])[:10]:
        parts.append(f"- `{js.get('task_family')}`: flagged_rate={float(js.get('flagged_rate', 0.0)):.6f} count={int(js.get('count', 0))} flagged={int(js.get('flagged', 0))}")
    parts.append("\n### flagged_rate_by_family_template_top\n")
    for js in report.useful_novelty.get("flagged_rate_by_family_template_top", [])[:10]:
        parts.append(f"- `{js.get('task_family_template_pair')}`: flagged_rate={float(js.get('flagged_rate', 0.0)):.6f} count={int(js.get('count', 0))} flagged={int(js.get('flagged', 0))}")
    parts.append("\n### flagged_rate_by_model_id_top\n")
    for js in report.useful_novelty.get("flagged_rate_by_model_id_top", [])[:10]:
        parts.append(f"- `{js.get('model_id')}`: flagged_rate={float(js.get('flagged_rate', 0.0)):.6f} count={int(js.get('count', 0))} flagged={int(js.get('flagged', 0))}")
    parts.append("")
    return("\n".join(parts))


def _write_text(path: str, text: str) -> None:
    f = open(path, "w", encoding="utf-8")
    try:
        f.write(text)
    finally:
        f.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Summarize entropy-buffer metrics from mixed JSONL task+judge logs.")
    p.add_argument("--in-jsonl", action="append", default=[], help="Input JSONL path (repeatable).")
    p.add_argument("--out-json", type=str, default="", help="Write JSON report to this path.")
    p.add_argument("--out-md", type=str, default="", help="Write Markdown report to this path.")
    p.add_argument("--json", action="store_true", help="Print JSON report to stdout.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if len(args.in_jsonl) == 0:
        raise SystemExit("--in-jsonl is required (repeatable)")

    records = lib.load_jsonl(args.in_jsonl)
    report = summarize(records)
    js = {
        "totals": report.totals,
        "runs": report.runs,
        "diversity": report.diversity,
        "tokens": report.tokens,
        "duplicates": report.duplicates,
        "judge": report.judge,
        "reuse": report.reuse,
        "useful_novelty": report.useful_novelty,
    }

    if args.out_json != "":
        _write_text(args.out_json, json.dumps(js, indent=2, sort_keys=True) + "\n")
    if args.out_md != "":
        _write_text(args.out_md, to_markdown(report))
    if args.json:
        sys.stdout.write(json.dumps(js, indent=2, sort_keys=True) + "\n")
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
