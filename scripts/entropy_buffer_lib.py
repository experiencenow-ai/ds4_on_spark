#!/usr/bin/env python3
"""Entropy-buffer metrics helpers for mixed JSONL task+judge logs."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_WS_RE = re.compile(r"\\s+")
_ANSWER_LETTER_RE = re.compile(r"(?i)\\b(?:answer\\s*[:=]\\s*)?([A-D])\\b")


@dataclass
class CanonicalRecord:
    raw: Dict[str, Any]
    rtype: str
    run_id: str
    judge_id: str
    item_id: str
    task_id: str
    task_family: str
    prompt_template_id: str
    model_id: str
    a_model_id: str
    b_model_id: str
    label: str
    prompt: str
    output: str
    answer: str
    buffer_id: str
    buffer_item_id: str


def _get_str(obj: Dict[str, Any], *names: str) -> str:
    for name in names:
        if name in obj and obj[name] is not None:
            v = obj[name]
            if isinstance(v, str):
                s = v.strip()
            else:
                s = str(v).strip()
            if s != "":
                return(s)
    return("")


def _norm_ws(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS_RE.sub(" ", s.strip())
    return(s)


def normalize_text(s: str) -> str:
    return(_norm_ws(s).lower())


def words(text: str) -> List[str]:
    return([m.group(0).lower() for m in _WORD_RE.finditer(text)])


def word_ngrams(ws: Sequence[str], n: int) -> Iterator[str]:
    if n <= 0:
        return(iter(()))
    if len(ws) < n:
        return(iter(()))
    return((" ".join(ws[i:i + n]) for i in range(0, len(ws) - n + 1)))


def shannon_entropy(counts: Dict[str, int]) -> float:
    total = float(sum(counts.values()))
    if total <= 0.0:
        return(0.0)
    h = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = float(c) / total
        h -= (p * math.log(p, 2))
    return(h)


def top_counts(counts: Dict[str, int], k: int = 10) -> List[Tuple[str, int]]:
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return(items[:k])


def _extract_label(obj: Dict[str, Any]) -> str:
    label = _get_str(obj, "label", "judge_label", "winner", "result")
    label = label.lower()
    if label in ("a", "b", "tie", "invalid"):
        return(label)
    if label in ("left", "model_a", "first", "0"):
        return("a")
    if label in ("right", "model_b", "second", "1"):
        return("b")
    if label in ("draw",):
        return("tie")
    return(label)


def extract_answer(text: str) -> str:
    m = _ANSWER_LETTER_RE.search(text)
    if m is None:
        return("")
    return(m.group(1).upper())


def make_item_id(task_id: str, prompt_template_id: str, a_model_id: str, b_model_id: str) -> str:
    parts = [task_id, prompt_template_id]
    if a_model_id != "" or b_model_id != "":
        parts.append(f"a={a_model_id}")
        parts.append(f"b={b_model_id}")
    parts = [p for p in parts if p != ""]
    return("|".join(parts))


def canonicalize_record(obj: Dict[str, Any]) -> CanonicalRecord:
    rtype = _get_str(obj, "type", "record_type")
    rtype = rtype.lower()
    if rtype == "":
        if "a_model_id" in obj or "b_model_id" in obj or "judge_id" in obj:
            rtype = "judge_pair"
        elif "prompt" in obj and ("output" in obj or "completion" in obj or "response" in obj):
            rtype = "task_run"
        else:
            rtype = "unknown"

    run_id = _get_str(obj, "run_id", "run", "run_name", "variant")
    judge_id = _get_str(obj, "judge_id", "judge", "rater_id")
    item_id = _get_str(obj, "item_id", "pair_id", "comparison_id", "id")

    task_id = _get_str(obj, "task_id", "task", "task_name")
    task_family = _get_str(obj, "task_family", "family", "suite", "category")
    prompt_template_id = _get_str(obj, "prompt_template_id", "template_id", "prompt_template", "template")

    model_id = _get_str(obj, "model_id", "model", "target", "candidate_model_id")
    a_model_id = _get_str(obj, "a_model_id", "model_a_id", "left_model_id", "a_model", "model_a")
    b_model_id = _get_str(obj, "b_model_id", "model_b_id", "right_model_id", "b_model", "model_b")

    label = _extract_label(obj) if rtype == "judge_pair" else ""

    prompt = _get_str(obj, "prompt", "input_prompt", "prompt_text", "input")
    output = _get_str(obj, "output", "completion", "response", "assistant", "text")

    answer = _get_str(obj, "answer", "final_answer")
    if answer == "" and output != "":
        answer = extract_answer(output)

    buffer_id = _get_str(obj, "buffer_id", "entropy_buffer_id")
    buffer_item_id = _get_str(obj, "buffer_item_id", "entropy_buffer_item_id", "buffer_key")

    return(CanonicalRecord(
        raw=dict(obj),
        rtype=rtype,
        run_id=run_id,
        judge_id=judge_id,
        item_id=item_id,
        task_id=task_id,
        task_family=task_family,
        prompt_template_id=prompt_template_id,
        model_id=model_id,
        a_model_id=a_model_id,
        b_model_id=b_model_id,
        label=label,
        prompt=prompt,
        output=output,
        answer=answer,
        buffer_id=buffer_id,
        buffer_item_id=buffer_item_id,
    ))


def iter_jsonl(path: str) -> Iterator[Dict[str, Any]]:
    f = open(path, "r", encoding="utf-8")
    try:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if s == "":
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {e}") from e
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: JSON record must be an object")
            yield(obj)
    finally:
        f.close()


def load_jsonl(paths: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in paths:
        out.extend(list(iter_jsonl(path)))
    return(out)


def get_str(obj: Dict[str, Any], *names: str) -> str:
    return(_get_str(obj, *names))
