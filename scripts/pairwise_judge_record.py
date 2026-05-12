#!/usr/bin/env python3
"""Wrap a raw DSv4 judge decision into a compact JSONL record envelope.

This script is offline-only: it does not call any model API. It is intended to
be used by harnesses (or local post-processing) to turn DSv4 judge text into
validated JSONL records for the judge-ELO loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

try:
    from scripts import judge_elo_schema as schema
except ModuleNotFoundError:
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from scripts import judge_elo_schema as schema


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _one_line(s: str) -> str:
    return " ".join(str(s).replace("\r", " ").replace("\n", " ").split())


def _as_int_opt(v: Optional[str], field: str) -> Optional[int]:
    if v is None:
        return None
    try:
        out = int(v)
    except ValueError:
        raise SystemExit(f"{field} must be an integer")
    if out < 0:
        raise SystemExit(f"{field} must be >= 0")
    return out


def build_record(
    record_schema: str,
    pair_id: str,
    model_a: str,
    model_b: str,
    judge_model: str,
    decision_text: str,
    tokens: Optional[Dict[str, int]],
    latency_ms: Optional[Dict[str, int]],
    strict: bool,
) -> Dict[str, Any]:
    if str(record_schema) not in (schema.SCHEMA_RECORD_V1, schema.SCHEMA_RECORD_V2):
        raise ValueError(f"record_schema must be {schema.SCHEMA_RECORD_V1!r} or {schema.SCHEMA_RECORD_V2!r}")
    if str(record_schema) == schema.SCHEMA_RECORD_V2:
        if tokens is None:
            raise ValueError("record_schema v2 requires tokens")
        if latency_ms is None:
            raise ValueError("record_schema v2 requires latency_ms")

    obj, perr = schema.parse_json_object_loose(decision_text)
    if obj is None:
        rec: Dict[str, Any] = {
            "schema": str(record_schema),
            "pair_id": pair_id,
            "model_a": model_a,
            "model_b": model_b,
            "judge_model": judge_model,
            "parse_valid": False,
            "raw": _one_line(decision_text)[:512],
            "parse_error": _one_line(perr)[:128],
        }
        if tokens is not None:
            rec["tokens"] = tokens
        if latency_ms is not None:
            rec["latency_ms"] = latency_ms
        return rec

    errs = schema.validate_decision(obj)
    if len(errs) == 0 and strict:
        errs.extend(schema.validate_decision_strict_extra(obj))
    if len(errs) != 0:
        rec2: Dict[str, Any] = {
            "schema": str(record_schema),
            "pair_id": pair_id,
            "model_a": model_a,
            "model_b": model_b,
            "judge_model": judge_model,
            "parse_valid": False,
            "raw": _one_line(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))[:512],
            "parse_error": _one_line("; ".join(errs))[:128],
        }
        if tokens is not None:
            rec2["tokens"] = tokens
        if latency_ms is not None:
            rec2["latency_ms"] = latency_ms
        return rec2

    rec3: Dict[str, Any] = {
        "schema": str(record_schema),
        "pair_id": pair_id,
        "model_a": model_a,
        "model_b": model_b,
        "judge_model": judge_model,
        "parse_valid": True,
    }
    for k in ("winner", "margin", "score_a", "score_b", "reason", "train_hint", "tags"):
        rec3[k] = obj.get(k)
    if tokens is not None:
        rec3["tokens"] = tokens
    if latency_ms is not None:
        rec3["latency_ms"] = latency_ms
    return rec3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record-schema", choices=["v1", "v2"], default="v1", help="record schema version (default v1)")
    ap.add_argument("--pair-id", required=True)
    ap.add_argument("--model-a", required=True)
    ap.add_argument("--model-b", required=True)
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--decision", required=True, help="path to raw judge decision text (possibly with extra text)")
    ap.add_argument("--strict", action="store_true", help="enforce strict margin/score and compact tag constraints")
    ap.add_argument("--tokens-a-out")
    ap.add_argument("--tokens-b-out")
    ap.add_argument("--tokens-judge-in")
    ap.add_argument("--tokens-judge-out")
    ap.add_argument("--latency-a-ms")
    ap.add_argument("--latency-b-ms")
    ap.add_argument("--latency-judge-ms")
    args = ap.parse_args()

    decision_text = _read_text(args.decision)

    tokens: Optional[Dict[str, int]] = None
    latency_ms: Optional[Dict[str, int]] = None

    tokens_obj: Dict[str, int] = {}
    t_a = _as_int_opt(args.tokens_a_out, "tokens_a_out")
    t_b = _as_int_opt(args.tokens_b_out, "tokens_b_out")
    t_ji = _as_int_opt(args.tokens_judge_in, "tokens_judge_in")
    t_jo = _as_int_opt(args.tokens_judge_out, "tokens_judge_out")
    if t_a is not None:
        tokens_obj["a_out"] = int(t_a)
    if t_b is not None:
        tokens_obj["b_out"] = int(t_b)
    if t_ji is not None:
        tokens_obj["judge_in"] = int(t_ji)
    if t_jo is not None:
        tokens_obj["judge_out"] = int(t_jo)
    if len(tokens_obj) != 0:
        tokens = tokens_obj

    latency_obj: Dict[str, int] = {}
    l_a = _as_int_opt(args.latency_a_ms, "latency_a_ms")
    l_b = _as_int_opt(args.latency_b_ms, "latency_b_ms")
    l_j = _as_int_opt(args.latency_judge_ms, "latency_judge_ms")
    if l_a is not None:
        latency_obj["a"] = int(l_a)
    if l_b is not None:
        latency_obj["b"] = int(l_b)
    if l_j is not None:
        latency_obj["judge"] = int(l_j)
    if len(latency_obj) != 0:
        latency_ms = latency_obj

    record_schema = (schema.SCHEMA_RECORD_V2 if str(args.record_schema) == "v2" else schema.SCHEMA_RECORD_V1)

    try:
        rec = build_record(
            record_schema=record_schema,
            pair_id=str(args.pair_id),
            model_a=str(args.model_a),
            model_b=str(args.model_b),
            judge_model=str(args.judge_model),
            decision_text=decision_text,
            tokens=tokens,
            latency_ms=latency_ms,
            strict=bool(args.strict),
        )
    except ValueError as e:
        raise SystemExit(str(e))
    print(json.dumps(rec, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
