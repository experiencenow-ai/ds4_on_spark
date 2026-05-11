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


def _inc(counts: Dict[str, int], key: str) -> None:
    if key == "":
        return
    counts[key] = counts.get(key, 0) + 1


def _dup_rate(values: Sequence[str]) -> float:
    if len(values) == 0:
        return(0.0)
    uniq = len(set(values))
    return(float(len(values) - uniq) / float(len(values)))


def _majority_disagreement(labels: Sequence[str]) -> float:
    if len(labels) == 0:
        return(0.0)
    counts: Dict[str, int] = {}
    for lab in labels:
        _inc(counts, lab)
    maxc = max(counts.values())
    return(1.0 - (float(maxc) / float(len(labels))))


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

    answers_nonempty: List[str] = []

    novelty_flag_counts: Dict[str, int] = {}
    novelty_flagged = 0
    template_task_total: Dict[str, int] = {}
    template_task_flagged: Dict[str, int] = {}
    family_task_total: Dict[str, int] = {}
    family_task_flagged: Dict[str, int] = {}
    pair_task_total: Dict[str, int] = {}
    pair_task_flagged: Dict[str, int] = {}

    template_out_total: Dict[str, int] = {}
    template_out_uniq: Dict[str, int] = {}
    template_out_seen: Dict[str, set] = {}
    pair_out_total: Dict[str, int] = {}
    pair_out_uniq: Dict[str, int] = {}
    pair_out_seen: Dict[str, set] = {}

    for c in task_runs:
        tmpl = c.prompt_template_id
        fam = c.task_family
        pair_k = "" if (fam == "" or tmpl == "") else f"{fam}|{tmpl}"
        if tmpl != "":
            template_task_total[tmpl] = template_task_total.get(tmpl, 0) + 1
        if fam != "":
            family_task_total[fam] = family_task_total.get(fam, 0) + 1
        if pair_k != "":
            pair_task_total[pair_k] = pair_task_total.get(pair_k, 0) + 1

        _inc(task_id_counts, c.task_id)
        _inc(task_family_counts, c.task_family)
        _inc(template_counts, c.prompt_template_id)
        if c.task_family != "" and c.prompt_template_id != "":
            _inc(family_template_counts, f"{c.task_family}|{c.prompt_template_id}")
        _inc(model_counts, c.model_id)
        _inc(answers, c.answer)
        if c.answer != "":
            answers_nonempty.append(c.answer)
        for tag in lib.get_list(c.raw, "tags", "tag"):
            _inc(tag_counts, tag)
        _inc(buffer_ids, c.buffer_id)
        _inc(buffer_items, c.buffer_item_id)

        itok = lib.get_int(c.raw, "input_tokens", "prompt_tokens", "input_token_count")
        otok = lib.get_int(c.raw, "output_tokens", "completion_tokens", "output_token_count")
        wms = lib.get_float(c.raw, "wall_ms", "latency_ms", "duration_ms", "elapsed_ms")
        if itok is not None:
            input_tokens.append(float(itok))
        if otok is not None:
            output_tokens.append(float(otok))
        if wms is not None:
            wall_ms.append(float(wms))
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
    for c in judge_pairs:
        _inc(label_counts, c.label)
        _inc(judge_id_counts, c.judge_id)
        if c.a_model_id != "" or c.b_model_id != "":
            pair_key = f"{c.a_model_id}|{c.b_model_id}"
            model_pair_label_counts.setdefault(pair_key, {})
            _inc(model_pair_label_counts[pair_key], c.label)
        item = c.item_id
        if item == "":
            item = lib.make_item_id(c.task_id, c.prompt_template_id, c.a_model_id, c.b_model_id)
        item_labels.setdefault(item, []).append(c.label)
        if item != "" and c.judge_id != "":
            item_judge_ids.setdefault(item, {})
            item_judge_ids[item][c.judge_id] = item_judge_ids[item].get(c.judge_id, 0) + 1
        if c.label in ("a", "b"):
            item_labels_decided_ab.setdefault(item, []).append(c.label)

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
        "model_id": _div_stats(model_counts),
        "answer": _div_stats(answers),
        "tags": _div_stats(tag_counts),
    }

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
        "judge_id_unique": len([k for k in judge_id_counts.keys() if k != ""]),
        "judge_id_top": lib.top_counts(judge_id_counts),
        "model_pair_count": len(pair_summary),
        "model_pair_summary": pair_summary,
        "model_pair_top": model_pair_top,
    }

    reuse = {
        "buffer_id_unique": len(buffer_ids),
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
    }

    duplicates.update({
        "output_norm_dup_rate_by_prompt_template_id_top": _dup_rate_top(template_out_total, template_out_uniq, "prompt_template_id", k=10),
        "output_norm_dup_rate_by_family_template_top": _dup_rate_top(pair_out_total, pair_out_uniq, "task_family_template_pair", k=10),
    })

    return(MetricsReport(
        totals=totals,
        diversity=diversity,
        tokens=tokens,
        duplicates=duplicates,
        judge=judge,
        reuse=reuse,
        useful_novelty=useful_novelty,
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


def to_markdown(report: MetricsReport) -> str:
    parts: List[str] = []
    parts.append("# Entropy Buffer Metrics\n")
    parts.append("## Totals\n")
    for k, v in report.totals.items():
        parts.append(f"- `{k}`: {v}")
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
    parts.append("\n## Judge\n")
    parts.append(f"- `label_entropy_bits`: {report.judge.get('label_entropy_bits'):.6f}")
    parts.append(f"- `pair_item_count`: {report.judge.get('pair_item_count')}")
    parts.append(f"- `disagreement_rate`: {report.judge.get('disagreement_rate'):.6f}")
    parts.append(f"- `disagreement_rate_decided_ab`: {report.judge.get('disagreement_rate_decided_ab'):.6f}")
    parts.append(f"- `decided_rate_ab`: {report.judge.get('decided_rate_ab'):.6f}")
    parts.append(f"- `tie_rate`: {report.judge.get('tie_rate'):.6f}")
    parts.append(f"- `invalid_rate`: {report.judge.get('invalid_rate'):.6f}")
    parts.append(f"- `label_balance_ab`: {report.judge.get('label_balance_ab'):.6f}")
    parts.append("\n### label_counts\n")
    for k, v in report.judge.get("label_counts", {}).items():
        parts.append(f"- `{k}`: {v}")
    parts.append("\n### judge_id_top\n")
    parts.append(_md_list_top(report.judge.get("judge_id_top", [])))
    parts.append("\n### model_pair_top\n")
    parts.append(_md_model_pair_top(report.judge.get("model_pair_top", [])))
    parts.append("\n### item_disagreement_top\n")
    parts.append(_md_item_disagreement_top(report.judge.get("item_disagreement_top", [])))
    parts.append("\n## Buffer reuse\n")
    for k in ("buffer_id_unique", "buffer_item_id_unique", "buffer_item_id_reused_unique", "buffer_item_reuse_rate_unique", "buffer_item_reuse_events", "buffer_item_reuse_event_rate", "buffer_item_hhi", "buffer_item_entropy_bits"):
        v = report.reuse.get(k)
        if isinstance(v, float):
            parts.append(f"- `{k}`: {v:.6f}")
        else:
            parts.append(f"- `{k}`: {v}")
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
