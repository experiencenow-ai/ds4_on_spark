#!/usr/bin/env python3
"""Entropy-buffer metrics helpers for mixed JSONL task+judge logs."""

from __future__ import annotations

import json
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_WS_RE = re.compile(r"\s+")
_ANSWER_NUMERIC_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*$")
_ANSWER_STANDALONE_RE = re.compile(r"(?i)^\s*[\(\[]?([A-Z])[\)\].]?\s*$")
_ANSWER_MARKED_RE = re.compile(r"(?i)\b(?:final\s+answer|answer|correct\s+answer)\s*[:=]\s*[\(\[]?([A-Z])[\)\].]?\b")
_ANSWER_IS_LETTER_RE = re.compile(r"(?i)\b(?:final\s+answer|answer|correct\s+answer)\s+is\s+[\(\[]?([A-Z])[\)\].]?\b")
_ANSWER_IS_NUMERIC_RE = re.compile(r"(?i)\b(?:final\s+answer|answer|correct\s+answer)\s+is\s+(-?\d+(?:\.\d+)?)\b")
_ANSWER_LETTER_ONLY_RE = re.compile(r"^[A-Za-z]$")


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
    answer_source: str
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
    parse_valid = obj.get("parse_valid", None)
    if parse_valid is False:
        return("invalid")
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
    if _ANSWER_NUMERIC_RE.match(text) is not None:
        return(text.strip())
    m = _ANSWER_STANDALONE_RE.match(text)
    if m is not None:
        return(m.group(1).upper())
    m = _ANSWER_MARKED_RE.search(text)
    if m is not None:
        return(m.group(1).upper())
    m = _ANSWER_IS_LETTER_RE.search(text)
    if m is not None:
        return(m.group(1).upper())
    m = _ANSWER_IS_NUMERIC_RE.search(text)
    if m is not None:
        return(m.group(1))
    return("")

def answer_letter(answer: str) -> str:
    s = str(answer).strip()
    if _ANSWER_LETTER_ONLY_RE.match(s) is None:
        return("")
    return(s.upper())


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
        if "a_model_id" in obj or "b_model_id" in obj or "judge_id" in obj or "model_a" in obj or "model_b" in obj or "pair_id" in obj:
            rtype = "judge_pair"
        elif "prompt" in obj and ("output" in obj or "completion" in obj or "response" in obj):
            rtype = "task_run"
        else:
            rtype = "unknown"

    run_id = _get_str(obj, "run_id", "run", "run_name", "variant")
    judge_id = _get_str(obj, "judge_id", "judge", "rater_id", "judge_model")
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

    answer = _get_str(obj, "answer", "final_answer", "expected_answer", "gold_answer")
    answer_source = "missing"
    if answer != "":
        answer_source = "field"
    elif output != "":
        extracted = extract_answer(output)
        if extracted != "":
            answer = extracted
            answer_source = "extract"

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
        answer_source=answer_source,
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

def get_list(obj: Dict[str, Any], *names: str) -> List[str]:
    for name in names:
        if name in obj and obj[name] is not None:
            v = obj[name]
            if isinstance(v, list):
                out: List[str] = []
                for x in v:
                    s = str(x).strip()
                    if s != "":
                        out.append(s)
                return(out)
            if isinstance(v, str) and v.strip() != "":
                return([x.strip() for x in v.split(",") if x.strip() != ""])
    return([])

def text_sha1(s: str) -> str:
    return(hashlib.sha1(s.encode("utf-8")).hexdigest())

def useful_novelty_flags(output: str, prompt: str) -> List[str]:
    flags: List[str] = []
    norm = normalize_text(output)
    if norm == "":
        return(["empty_output"])
    if extract_answer(output) != "":
        return([])
    if norm.startswith("{") and norm.endswith("}"):
        return([])
    if norm.startswith("[") and norm.endswith("]"):
        return([])
    ws = words(norm)
    if len(ws) == 0:
        return(["no_words"])
    if len(norm) >= 4096:
        flags.append("very_long_output_ge_4096_chars")
    if len(ws) <= 2 and len(norm) <= 16:
        flags.append("very_short_output_le_2_words")
    if "as an ai" in norm or "as a language model" in norm:
        flags.append("ai_disclaimer")
    if "i can't" in norm or "i cannot" in norm or "unable to" in norm:
        flags.append("refusal_like")
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
    if len(ws) >= 12 and prompt != "":
        pws = words(prompt)
        if len(pws) >= 8:
            pset = set(pws)
            overlap = sum(1 for w in ws if w in pset)
            if (float(overlap) / float(len(ws))) >= 0.90:
                flags.append("echo_prompt_overlap_ge_0.90")
    lines = [normalize_text(x) for x in output.splitlines() if x.strip() != ""]
    if len(lines) >= 12:
        lcounts: Dict[str, int] = {}
        for ln in lines:
            lcounts[ln] = lcounts.get(ln, 0) + 1
        top = max(lcounts.values())
        if top >= 6:
            flags.append("line_repetition_ge_6")
        if len(lcounts) <= 4:
            flags.append("few_unique_lines_le_4")
    return(flags)


def get_useful_novelty_flags(obj: Dict[str, Any], output: str, prompt: str) -> List[str]:
    v = obj.get("useful_novelty_flags", None)
    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            s = str(x).strip()
            if s != "":
                out.append(s)
        return(out)
    if isinstance(v, str) and v.strip() != "":
        return([x.strip() for x in v.split(",") if x.strip() != ""])
    flagged = obj.get("useful_novelty_flagged", None)
    if flagged is False:
        return([])
    return(useful_novelty_flags(output, prompt))


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return(None)
    if isinstance(v, bool):
        return(None)
    if isinstance(v, (int, float)):
        x = float(v)
        if math.isfinite(x):
            return(x)
        return(None)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return(None)
        try:
            x = float(s)
        except ValueError:
            return(None)
        if math.isfinite(x):
            return(x)
        return(None)
    return(None)


def _get_float(obj: Dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        if name in obj:
            x = _to_float(obj.get(name))
            if x is not None:
                return(x)
    return(None)


def _get_int(obj: Dict[str, Any], *names: str) -> Optional[int]:
    x = _get_float(obj, *names)
    if x is None:
        return(None)
    return(int(x))


def get_float(obj: Dict[str, Any], *names: str) -> Optional[float]:
    return(_get_float(obj, *names))


def get_int(obj: Dict[str, Any], *names: str) -> Optional[int]:
    return(_get_int(obj, *names))
