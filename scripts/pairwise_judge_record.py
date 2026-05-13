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


def _parse_int_list_arg(v: str, field: str, n: int) -> Optional[list[int]]:
    s = str(v or "").strip()
    if s == "":
        return None
    try:
        if s.startswith("["):
            obj = json.loads(s)
            if not isinstance(obj, list):
                raise ValueError("must be a JSON list")
            parts = obj
        else:
            parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    except Exception as e:
        raise SystemExit(f"{field} must be a JSON list or comma-separated integers: {e}") from e
    if len(parts) != int(n):
        raise SystemExit(f"{field} must have length {int(n)}")
    out: list[int] = []
    for i, raw in enumerate(parts):
        try:
            iv = int(raw)
        except Exception as e:
            raise SystemExit(f"{field}[{i}] must be an integer") from e
        if iv < 0:
            raise SystemExit(f"{field}[{i}] must be >= 0")
        out.append(int(iv))
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
    if str(record_schema) not in (schema.SCHEMA_RECORD_V1, schema.SCHEMA_RECORD_V2, schema.SCHEMA_RECORD_V3, schema.SCHEMA_RECORD_V4, schema.SCHEMA_RECORD_V5):
        raise ValueError(
            f"record_schema must be {schema.SCHEMA_RECORD_V1!r}, {schema.SCHEMA_RECORD_V2!r}, {schema.SCHEMA_RECORD_V3!r}, {schema.SCHEMA_RECORD_V4!r}, or {schema.SCHEMA_RECORD_V5!r}"
        )
    schema_v2 = str(record_schema) == schema.SCHEMA_RECORD_V2
    schema_v3 = str(record_schema) == schema.SCHEMA_RECORD_V3
    schema_v4 = str(record_schema) == schema.SCHEMA_RECORD_V4
    schema_v5 = str(record_schema) == schema.SCHEMA_RECORD_V5
    strict_effective = bool(strict) or schema_v3 or schema_v4 or schema_v5
    if schema_v2 or schema_v3 or schema_v4 or schema_v5:
        if tokens is None:
            raise ValueError("record_schema v2/v3/v4/v5 requires tokens")
        if latency_ms is None:
            raise ValueError("record_schema v2/v3/v4/v5 requires latency_ms")
        missing: list[str] = []
        for k in ("a_out", "b_out", "judge_in", "judge_out"):
            if not isinstance(tokens.get(k), int) or isinstance(tokens.get(k), bool):
                missing.append(f"tokens.{k}")
        for k in ("a", "b", "judge"):
            if not isinstance(latency_ms.get(k), int) or isinstance(latency_ms.get(k), bool):
                missing.append(f"latency_ms.{k}")
        if len(missing) != 0:
            raise ValueError("record_schema v2/v3/v4/v5 requires full budget accounting: missing " + ", ".join(missing))

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
        if schema_v5:
            if tokens is not None and latency_ms is not None:
                rec["tk"] = [int(tokens["a_out"]), int(tokens["b_out"]), int(tokens["judge_in"]), int(tokens["judge_out"])]
                rec["lt"] = [int(latency_ms["a"]), int(latency_ms["b"]), int(latency_ms["judge"])]
        else:
            if tokens is not None:
                rec["tokens"] = tokens
            if latency_ms is not None:
                rec["latency_ms"] = latency_ms
        if schema_v2 or schema_v3 or schema_v4 or schema_v5:
            errs = schema.validate_record(rec)
            if len(errs) != 0:
                raise ValueError("record_schema v2/v3/v4/v5 produced an invalid record: " + "; ".join(errs))
        return rec

    canon, cerrs = schema.canonicalize_decision_obj(obj)
    if canon is None:
        rec_bad: Dict[str, Any] = {
            "schema": str(record_schema),
            "pair_id": pair_id,
            "model_a": model_a,
            "model_b": model_b,
            "judge_model": judge_model,
            "parse_valid": False,
            "raw": _one_line(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))[:512],
            "parse_error": _one_line("; ".join(cerrs))[:128],
        }
        if schema_v5:
            if tokens is not None and latency_ms is not None:
                rec_bad["tk"] = [int(tokens["a_out"]), int(tokens["b_out"]), int(tokens["judge_in"]), int(tokens["judge_out"])]
                rec_bad["lt"] = [int(latency_ms["a"]), int(latency_ms["b"]), int(latency_ms["judge"])]
        else:
            if tokens is not None:
                rec_bad["tokens"] = tokens
            if latency_ms is not None:
                rec_bad["latency_ms"] = latency_ms
        if schema_v2 or schema_v3 or schema_v4 or schema_v5:
            errs_bad = schema.validate_record(rec_bad)
            if len(errs_bad) != 0:
                raise ValueError("record_schema v2/v3/v4/v5 produced an invalid record: " + "; ".join(errs_bad))
        return rec_bad

    errs = list(cerrs)
    errs.extend(schema.validate_decision(canon))
    if len(errs) == 0 and strict_effective:
        errs.extend(schema.validate_decision_strict_extra(canon))
    if len(errs) != 0:
        rec2: Dict[str, Any] = {
            "schema": str(record_schema),
            "pair_id": pair_id,
            "model_a": model_a,
            "model_b": model_b,
            "judge_model": judge_model,
            "parse_valid": False,
            "raw": _one_line(json.dumps(canon, separators=(",", ":"), ensure_ascii=False))[:512],
            "parse_error": _one_line("; ".join(errs))[:128],
        }
        if schema_v5:
            if tokens is not None and latency_ms is not None:
                rec2["tk"] = [int(tokens["a_out"]), int(tokens["b_out"]), int(tokens["judge_in"]), int(tokens["judge_out"])]
                rec2["lt"] = [int(latency_ms["a"]), int(latency_ms["b"]), int(latency_ms["judge"])]
        else:
            if tokens is not None:
                rec2["tokens"] = tokens
            if latency_ms is not None:
                rec2["latency_ms"] = latency_ms
        if schema_v2 or schema_v3 or schema_v4 or schema_v5:
            errs2 = schema.validate_record(rec2)
            if len(errs2) != 0:
                raise ValueError("record_schema v2/v3/v4/v5 produced an invalid record: " + "; ".join(errs2))
        return rec2

    if schema_v5:
        rec5: Dict[str, Any] = {
            "schema": str(record_schema),
            "pair_id": pair_id,
            "model_a": model_a,
            "model_b": model_b,
            "judge_model": judge_model,
            "parse_valid": True,
            "w": canon.get("winner"),
            "m": canon.get("margin"),
            "sa": canon.get("score_a"),
            "sb": canon.get("score_b"),
            "r": canon.get("reason"),
            "h": canon.get("train_hint"),
            "t": canon.get("tags"),
        }
        if tokens is not None:
            rec5["tk"] = [int(tokens["a_out"]), int(tokens["b_out"]), int(tokens["judge_in"]), int(tokens["judge_out"])]
        if latency_ms is not None:
            rec5["lt"] = [int(latency_ms["a"]), int(latency_ms["b"]), int(latency_ms["judge"])]
        errs5 = schema.validate_record(rec5)
        if len(errs5) != 0:
            raise ValueError("record_schema v5 produced an invalid record: " + "; ".join(errs5))
        return rec5

    if schema_v4:
        # v4 stores compact decision keys (w/m/sa/sb/r/h/t) to minimize JSONL size.
        rec4: Dict[str, Any] = {
            "schema": str(record_schema),
            "pair_id": pair_id,
            "model_a": model_a,
            "model_b": model_b,
            "judge_model": judge_model,
            "parse_valid": True,
            "w": canon.get("winner"),
            "m": canon.get("margin"),
            "sa": canon.get("score_a"),
            "sb": canon.get("score_b"),
            "r": canon.get("reason"),
            "h": canon.get("train_hint"),
            "t": canon.get("tags"),
        }
        if tokens is not None:
            rec4["tokens"] = tokens
        if latency_ms is not None:
            rec4["latency_ms"] = latency_ms
        errs4 = schema.validate_record(rec4)
        if len(errs4) != 0:
            raise ValueError("record_schema v4 produced an invalid record: " + "; ".join(errs4))
        return rec4

    rec3: Dict[str, Any] = {
        "schema": str(record_schema),
        "pair_id": pair_id,
        "model_a": model_a,
        "model_b": model_b,
        "judge_model": judge_model,
        "parse_valid": True,
    }
    for k in ("winner", "margin", "score_a", "score_b", "reason", "train_hint", "tags"):
        rec3[k] = canon.get(k)
    if tokens is not None:
        rec3["tokens"] = tokens
    if latency_ms is not None:
        rec3["latency_ms"] = latency_ms
    if schema_v2 or schema_v3:
        errs3 = schema.validate_record(rec3)
        if len(errs3) != 0:
            raise ValueError("record_schema v2 produced an invalid record: " + "; ".join(errs3))
    return rec3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record-schema", choices=["v1", "v2", "v3", "v4", "v5"], default="v1", help="record schema version (default v1)")
    ap.add_argument("--pair-id", required=True)
    ap.add_argument("--model-a", required=True)
    ap.add_argument("--model-b", required=True)
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--decision", required=True, help="path to raw judge decision text (possibly with extra text)")
    ap.add_argument("--strict", action="store_true", help="enforce strict margin/score and compact tag constraints (implied by record schema v3)")
    ap.add_argument("--tk", default="", help="compact token counts: JSON list or comma list [a_out,b_out,judge_in,judge_out]")
    ap.add_argument("--lt", default="", help="compact latency ms: JSON list or comma list [a_ms,b_ms,judge_ms]")
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
    latency_obj: Dict[str, int] = {}

    tok_args_present = any(
        v is not None
        and str(v).strip() != ""
        for v in (args.tokens_a_out, args.tokens_b_out, args.tokens_judge_in, args.tokens_judge_out)
    )
    lat_args_present = any(
        v is not None and str(v).strip() != "" for v in (args.latency_a_ms, args.latency_b_ms, args.latency_judge_ms)
    )
    if str(args.tk).strip() != "" and tok_args_present:
        raise SystemExit("do not mix --tk with --tokens-* flags")
    if str(args.lt).strip() != "" and lat_args_present:
        raise SystemExit("do not mix --lt with --latency-* flags")

    tk = _parse_int_list_arg(str(args.tk), "tk", 4)
    lt = _parse_int_list_arg(str(args.lt), "lt", 3)
    t_a = None
    t_b = None
    t_ji = None
    t_jo = None
    l_a = None
    l_b = None
    l_j = None
    if tk is not None:
        t_a, t_b, t_ji, t_jo = int(tk[0]), int(tk[1]), int(tk[2]), int(tk[3])
    else:
        t_a = _as_int_opt(args.tokens_a_out, "tokens_a_out")
        t_b = _as_int_opt(args.tokens_b_out, "tokens_b_out")
        t_ji = _as_int_opt(args.tokens_judge_in, "tokens_judge_in")
        t_jo = _as_int_opt(args.tokens_judge_out, "tokens_judge_out")
    if lt is not None:
        l_a, l_b, l_j = int(lt[0]), int(lt[1]), int(lt[2])
    else:
        l_a = _as_int_opt(args.latency_a_ms, "latency_a_ms")
        l_b = _as_int_opt(args.latency_b_ms, "latency_b_ms")
        l_j = _as_int_opt(args.latency_judge_ms, "latency_judge_ms")

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

    if l_a is not None:
        latency_obj["a"] = int(l_a)
    if l_b is not None:
        latency_obj["b"] = int(l_b)
    if l_j is not None:
        latency_obj["judge"] = int(l_j)
    if len(latency_obj) != 0:
        latency_ms = latency_obj

    if str(args.record_schema) == "v2":
        record_schema = schema.SCHEMA_RECORD_V2
    elif str(args.record_schema) == "v3":
        record_schema = schema.SCHEMA_RECORD_V3
    elif str(args.record_schema) == "v4":
        record_schema = schema.SCHEMA_RECORD_V4
    elif str(args.record_schema) == "v5":
        record_schema = schema.SCHEMA_RECORD_V5
    else:
        record_schema = schema.SCHEMA_RECORD_V1
    if record_schema in (schema.SCHEMA_RECORD_V2, schema.SCHEMA_RECORD_V3, schema.SCHEMA_RECORD_V4, schema.SCHEMA_RECORD_V5):
        missing_fields: list[str] = []
        for k in ("a_out", "b_out", "judge_in", "judge_out"):
            if k not in tokens_obj:
                missing_fields.append(f"tokens_{k}")
        for k in ("a", "b", "judge"):
            if k not in latency_obj:
                missing_fields.append(f"latency_{k}_ms")
        if len(missing_fields) != 0:
            raise SystemExit("record_schema v2/v3/v4/v5 requires: " + ", ".join(missing_fields))

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
