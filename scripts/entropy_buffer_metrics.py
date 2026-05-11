#!/usr/bin/env python3
"""Summarize entropy-buffer diversity/degeneracy metrics from mixed JSONL logs."""

from __future__ import annotations

import argparse
import json
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


def _useful_novelty_flags(output: str) -> List[str]:
    flags: List[str] = []
    norm = lib.normalize_text(output)
    if norm == "":
        return(["empty_output"])
    ws = lib.words(norm)
    if len(ws) == 0:
        return(["no_words"])
    if len(ws) >= 8:
        counts: Dict[str, int] = {}
        for w in ws:
            counts[w] = counts.get(w, 0) + 1
        top = max(counts.values())
        if float(top) / float(len(ws)) >= 0.65:
            flags.append("word_repetition_ge_0.65")
        uniq_frac = float(len(counts)) / float(len(ws))
        if uniq_frac <= 0.25:
            flags.append("word_unique_frac_le_0.25")
    if len(norm) >= 200 and "http" in norm and norm.count("http") >= 3:
        flags.append("many_urls")
    return(flags)


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
    model_counts: Dict[str, int] = {}
    answers: Dict[str, int] = {}
    buffer_ids: Dict[str, int] = {}
    buffer_items: Dict[str, int] = {}

    outputs_exact: List[str] = []
    outputs_norm: List[str] = []
    prompts_norm: List[str] = []

    out_words: List[str] = []
    out_2grams: Dict[str, int] = {}
    out_3grams: Dict[str, int] = {}

    novelty_flag_counts: Dict[str, int] = {}
    novelty_flagged = 0

    for c in task_runs:
        _inc(task_id_counts, c.task_id)
        _inc(task_family_counts, c.task_family)
        _inc(template_counts, c.prompt_template_id)
        _inc(model_counts, c.model_id)
        _inc(answers, c.answer)
        _inc(buffer_ids, c.buffer_id)
        _inc(buffer_items, c.buffer_item_id)

        if c.output != "":
            outputs_exact.append(c.output)
            outputs_norm.append(lib.normalize_text(c.output))
            ws = lib.words(c.output)
            out_words.extend(ws)
            for ng in lib.word_ngrams(ws, 2):
                out_2grams[ng] = out_2grams.get(ng, 0) + 1
            for ng in lib.word_ngrams(ws, 3):
                out_3grams[ng] = out_3grams.get(ng, 0) + 1
            flags = _useful_novelty_flags(c.output)
            if len(flags) != 0:
                novelty_flagged += 1
                for f in flags:
                    novelty_flag_counts[f] = novelty_flag_counts.get(f, 0) + 1
        if c.prompt != "":
            prompts_norm.append(lib.normalize_text(c.prompt))

    label_counts: Dict[str, int] = {}
    item_labels: Dict[str, List[str]] = {}
    for c in judge_pairs:
        _inc(label_counts, c.label)
        item = c.item_id
        if item == "":
            item = "|".join([c.task_id, c.prompt_template_id, f"a={c.a_model_id}", f"b={c.b_model_id}"])
        item_labels.setdefault(item, []).append(c.label)

    item_disagreements: List[float] = []
    for labs in item_labels.values():
        if len(labs) >= 2:
            item_disagreements.append(_majority_disagreement(labs))
    disagreement_rate = 0.0 if len(item_disagreements) == 0 else (sum(item_disagreements) / float(len(item_disagreements)))

    reuse_count = sum(1 for v in buffer_items.values() if v >= 2)
    totals = {
        "records_total": len(canon),
        "task_run_records": len(task_runs),
        "judge_pair_records": len(judge_pairs),
        "unknown_records": unknown,
    }

    diversity = {
        "task_id": {
            "unique": len(task_id_counts),
            "entropy_bits": lib.shannon_entropy(task_id_counts),
            "top": lib.top_counts(task_id_counts),
        },
        "task_family": {
            "unique": len(task_family_counts),
            "entropy_bits": lib.shannon_entropy(task_family_counts),
            "top": lib.top_counts(task_family_counts),
        },
        "prompt_template_id": {
            "unique": len(template_counts),
            "entropy_bits": lib.shannon_entropy(template_counts),
            "top": lib.top_counts(template_counts),
        },
        "model_id": {
            "unique": len(model_counts),
            "entropy_bits": lib.shannon_entropy(model_counts),
            "top": lib.top_counts(model_counts),
        },
        "answer": {
            "unique": len(answers),
            "entropy_bits": lib.shannon_entropy(answers),
            "top": lib.top_counts(answers),
        },
    }

    word_counts: Dict[str, int] = {}
    for w in out_words:
        word_counts[w] = word_counts.get(w, 0) + 1
    tokens = {
        "output_words_total": len(out_words),
        "output_words_unique": len(word_counts),
        "output_word_entropy_bits": lib.shannon_entropy(word_counts),
        "output_word_top": lib.top_counts(word_counts),
        "output_2gram_entropy_bits": lib.shannon_entropy(out_2grams),
        "output_2gram_top": lib.top_counts(out_2grams),
        "output_3gram_entropy_bits": lib.shannon_entropy(out_3grams),
        "output_3gram_top": lib.top_counts(out_3grams),
    }

    duplicates = {
        "output_exact_dup_rate": _dup_rate(outputs_exact),
        "output_norm_dup_rate": _dup_rate(outputs_norm),
        "prompt_norm_dup_rate": _dup_rate(prompts_norm),
    }

    judge = {
        "label_counts": dict(sorted(label_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "label_entropy_bits": lib.shannon_entropy(label_counts),
        "pair_item_count": len(item_labels),
        "disagreement_rate": disagreement_rate,
    }

    reuse = {
        "buffer_id_unique": len(buffer_ids),
        "buffer_item_id_unique": len(buffer_items),
        "buffer_item_id_reused_unique": reuse_count,
        "buffer_item_reuse_rate_unique": 0.0 if len(buffer_items) == 0 else (float(reuse_count) / float(len(buffer_items))),
        "buffer_item_top": lib.top_counts(buffer_items),
    }

    useful_novelty = {
        "flagged_task_runs": novelty_flagged,
        "flagged_task_run_rate": 0.0 if len(task_runs) == 0 else (float(novelty_flagged) / float(len(task_runs))),
        "flag_counts": dict(sorted(novelty_flag_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
    }

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
        top = js.get("top") or []
        parts.append(_md_list_top(top))
        parts.append("")
    parts.append("\n## Duplicates\n")
    for k, v in report.duplicates.items():
        parts.append(f"- `{k}`: {v:.6f}")
    parts.append("\n## Judge\n")
    parts.append(f"- `label_entropy_bits`: {report.judge.get('label_entropy_bits'):.6f}")
    parts.append(f"- `pair_item_count`: {report.judge.get('pair_item_count')}")
    parts.append(f"- `disagreement_rate`: {report.judge.get('disagreement_rate'):.6f}")
    parts.append("\n### label_counts\n")
    for k, v in report.judge.get("label_counts", {}).items():
        parts.append(f"- `{k}`: {v}")
    parts.append("\n## Buffer reuse\n")
    for k in ("buffer_id_unique", "buffer_item_id_unique", "buffer_item_id_reused_unique", "buffer_item_reuse_rate_unique"):
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
