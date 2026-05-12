#!/usr/bin/env python3
"""Compact DSv4 pairwise judge schema + validation helpers (offline).

This module intentionally avoids dependencies so it can run in constrained
environments (Spark nodes, CI, offline). It validates both:
- the DSv4 decision object (winner/margin/scores/reason/train_hint/tags), and
- the JSONL "record envelope" used by this repo's offline ELO updater.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_RECORD_V1 = "ds4_pairwise_judge_record_v1"

WINNERS = ("A", "B", "tie")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _words(s: str) -> int:
    return len([w for w in s.strip().split() if w != ""])

def _has_newline(s: str) -> bool:
    return ("\n" in s) or ("\r" in s)


def _as_obj(v: Any, field: str, errs: List[str]) -> Optional[Dict[str, Any]]:
    if v is None:
        return None
    if not isinstance(v, dict):
        errs.append(f"{field} must be an object")
        return None
    return v


def _as_str(v: Any, field: str, errs: List[str]) -> str:
    if not isinstance(v, str):
        errs.append(f"{field} must be a string")
        return ""
    return v


def _as_bool(v: Any, field: str, errs: List[str]) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    errs.append(f"{field} must be a boolean")
    return None


def _as_int(v: Any, field: str, errs: List[str]) -> Optional[int]:
    if _is_int(v):
        return int(v)
    errs.append(f"{field} must be an integer")
    return None


def _finite(v: float) -> bool:
    return not (math.isnan(v) or math.isinf(v))


@dataclass(frozen=True)
class JudgeDecision:
    winner: str
    margin: int
    score_a: int
    score_b: int
    reason: str
    train_hint: str
    tags: Tuple[str, ...]


def validate_decision(obj: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    winner = _as_str(obj.get("winner"), "winner", errs)
    if winner != "" and winner not in WINNERS:
        errs.append("winner must be one of: A, B, tie")

    margin = _as_int(obj.get("margin"), "margin", errs)
    if margin is not None and (margin < 0 or margin > 3):
        errs.append("margin must be in [0,3]")

    score_a = _as_int(obj.get("score_a"), "score_a", errs)
    if score_a is not None and (score_a < 0 or score_a > 10):
        errs.append("score_a must be in [0,10]")

    score_b = _as_int(obj.get("score_b"), "score_b", errs)
    if score_b is not None and (score_b < 0 or score_b > 10):
        errs.append("score_b must be in [0,10]")

    reason = _as_str(obj.get("reason"), "reason", errs)
    if reason.strip() == "":
        errs.append("reason must be non-empty")
    if reason != "" and _words(reason) > 18:
        errs.append("reason must be <= 18 words")
    if reason != "" and len(reason) > 200:
        errs.append("reason must be <= 200 chars")
    if reason != "" and _has_newline(reason):
        errs.append("reason must be a single line (no newlines)")

    train_hint = _as_str(obj.get("train_hint"), "train_hint", errs)
    if train_hint != "" and _words(train_hint) > 18:
        errs.append("train_hint must be <= 18 words")
    if train_hint != "" and len(train_hint) > 200:
        errs.append("train_hint must be <= 200 chars")
    if train_hint != "" and _has_newline(train_hint):
        errs.append("train_hint must be a single line (no newlines)")

    tags_v = obj.get("tags")
    if not isinstance(tags_v, list):
        errs.append("tags must be an array")
    else:
        if len(tags_v) > 8:
            errs.append("tags must have at most 8 entries")
        for i, tag in enumerate(tags_v):
            if not isinstance(tag, str):
                errs.append(f"tags[{i}] must be a string")
                continue
            if tag.strip() == "":
                errs.append(f"tags[{i}] must be non-empty")
            if _has_newline(tag):
                errs.append(f"tags[{i}] must be a single line (no newlines)")
            if len(tag) > 24:
                errs.append(f"tags[{i}] must be <= 24 chars")

    if winner == "tie":
        if margin is not None and margin != 0:
            errs.append("tie requires margin=0")
        if score_a is not None and score_b is not None and score_a != score_b:
            errs.append("tie requires score_a==score_b")
    if winner == "A":
        if score_a is not None and score_b is not None and score_a < score_b:
            errs.append("winner=A requires score_a>=score_b")
    if winner == "B":
        if score_a is not None and score_b is not None and score_b < score_a:
            errs.append("winner=B requires score_b>=score_a")

    return errs


def validate_record(obj: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    if "schema" not in obj:
        errs.append("schema is required")
    else:
        schema_v = _as_str(obj.get("schema"), "schema", errs)
        if schema_v != "" and schema_v != SCHEMA_RECORD_V1:
            errs.append(f"schema must be {SCHEMA_RECORD_V1!r}")

    for field in ("pair_id", "model_a", "model_b"):
        s = _as_str(obj.get(field), field, errs)
        if s == "":
            errs.append(f"{field} is required")

    parse_valid = _as_bool(obj.get("parse_valid"), "parse_valid", errs)
    if parse_valid is None:
        return errs

    if parse_valid:
        errs.extend(validate_decision(obj))
    else:
        # When invalid, encourage preserving the raw judge output for debugging.
        raw = obj.get("raw")
        if raw is not None and not isinstance(raw, str):
            errs.append("raw must be a string when present")
        if isinstance(raw, str) and len(raw) > 512:
            errs.append("raw must be <= 512 chars")
        if isinstance(raw, str) and _has_newline(raw):
            errs.append("raw must be a single line (no newlines)")
        parse_error = obj.get("parse_error")
        if parse_error is not None and not isinstance(parse_error, str):
            errs.append("parse_error must be a string when present")
        if isinstance(parse_error, str) and len(parse_error) > 128:
            errs.append("parse_error must be <= 128 chars")
        if isinstance(parse_error, str) and _has_newline(parse_error):
            errs.append("parse_error must be a single line (no newlines)")
        if raw is None and parse_error is None:
            errs.append("parse_invalid records must include raw and/or parse_error")

    tokens = _as_obj(obj.get("tokens"), "tokens", errs)
    if tokens is not None:
        for k in ("a_out", "b_out", "judge_in", "judge_out"):
            if k not in tokens:
                continue
            v = _as_int(tokens.get(k), f"tokens.{k}", errs)
            if v is not None and v < 0:
                errs.append(f"tokens.{k} must be >= 0")

    latency_ms = _as_obj(obj.get("latency_ms"), "latency_ms", errs)
    if latency_ms is not None:
        for k in ("a", "b", "judge"):
            if k not in latency_ms:
                continue
            v = _as_int(latency_ms.get(k), f"latency_ms.{k}", errs)
            if v is not None and v < 0:
                errs.append(f"latency_ms.{k} must be >= 0")

    return errs


def validate_record_strict(obj: Dict[str, Any]) -> List[str]:
    """Strict validation for records intended to feed baseline-quality joins.

    Compared to validate_record(), this additionally requires token/latency
    accounting to be present (so the baseline runtime loop can compute
    quality-adjusted tok/s without mixing judge quality and speed signals).
    """
    errs = validate_record(obj)

    tokens = obj.get("tokens")
    if not isinstance(tokens, dict):
        errs.append("tokens is required and must be an object")
    else:
        for k in ("a_out", "b_out", "judge_in", "judge_out"):
            if k not in tokens:
                errs.append(f"tokens.{k} is required")
                continue
            v = tokens.get(k)
            if not _is_int(v):
                errs.append(f"tokens.{k} must be an integer")
                continue
            if int(v) < 0:
                errs.append(f"tokens.{k} must be >= 0")

    latency_ms = obj.get("latency_ms")
    if not isinstance(latency_ms, dict):
        errs.append("latency_ms is required and must be an object")
    else:
        for k in ("a", "b", "judge"):
            if k not in latency_ms:
                errs.append(f"latency_ms.{k} is required")
                continue
            v = latency_ms.get(k)
            if not _is_int(v):
                errs.append(f"latency_ms.{k} must be an integer")
                continue
            if int(v) < 0:
                errs.append(f"latency_ms.{k} must be >= 0")

    parse_valid = obj.get("parse_valid")
    if parse_valid is False:
        raw = obj.get("raw")
        parse_error = obj.get("parse_error")
        if raw is None and parse_error is None:
            errs.append("parse_invalid records should include raw and/or parse_error")
        if isinstance(raw, str) and len(raw) > 512:
            errs.append("raw must be <= 512 chars")
        if isinstance(parse_error, str) and len(parse_error) > 128:
            errs.append("parse_error must be <= 128 chars")

    return errs


def parse_json_object_loose(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Parse a JSON object even if the model wrapped it with extra text."""
    s = text.strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj, ""
        return None, "top-level JSON value must be an object"
    except json.JSONDecodeError:
        pass

    # Many judge models occasionally wrap the JSON in extra prose. Prefer the
    # first parseable object rather than greedy-matching the last '}'.
    dec = json.JSONDecoder()
    i = 0
    while True:
        start = text.find("{", i)
        if start < 0:
            break
        try:
            obj2, _end = dec.raw_decode(text, start)
            if isinstance(obj2, dict):
                return obj2, ""
            return None, "top-level JSON value must be an object"
        except json.JSONDecodeError:
            i = start + 1
            continue

    return None, "missing JSON object braces"


def iter_jsonl(path: str) -> Iterable[Tuple[int, Dict[str, Any]]]:
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            s = line.strip()
            if s == "" or s.startswith("#"):
                continue
            obj = json.loads(s)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{lineno}: JSONL line must be an object")
            yield lineno, obj
