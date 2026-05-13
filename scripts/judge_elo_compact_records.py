#!/usr/bin/env python3
"""Convert judge-ELO JSONL records into compact record schemas (offline).

This script does not call any paid API. It is intended to help harnesses (or
post-processing) compact older verbose record schemas (v1/v2/v3) into the
space-efficient record schemas (v4/v5) without changing semantics.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from scripts import judge_elo_schema as schema
except ModuleNotFoundError:
    # Allow running as a script from repo root.
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from scripts import judge_elo_schema as schema


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _as_nonneg_int(v: Any, label: str) -> int:
    if not _is_int(v):
        raise ValueError(f"{label} must be an integer")
    if int(v) < 0:
        raise ValueError(f"{label} must be >= 0")
    return int(v)


def _extract_tokens4(obj: Dict[str, Any]) -> Optional[List[int]]:
    tk = obj.get("tk")
    if isinstance(tk, list):
        if len(tk) != 4:
            raise ValueError("tk must be [a_out,b_out,judge_in,judge_out]")
        return [
            _as_nonneg_int(tk[0], "tk[0]"),
            _as_nonneg_int(tk[1], "tk[1]"),
            _as_nonneg_int(tk[2], "tk[2]"),
            _as_nonneg_int(tk[3], "tk[3]"),
        ]
    tokens = obj.get("tokens")
    if not isinstance(tokens, dict):
        return None
    return [
        _as_nonneg_int(tokens.get("a_out"), "tokens.a_out"),
        _as_nonneg_int(tokens.get("b_out"), "tokens.b_out"),
        _as_nonneg_int(tokens.get("judge_in"), "tokens.judge_in"),
        _as_nonneg_int(tokens.get("judge_out"), "tokens.judge_out"),
    ]


def _extract_latency3(obj: Dict[str, Any]) -> Optional[List[int]]:
    lt = obj.get("lt")
    if isinstance(lt, list):
        if len(lt) != 3:
            raise ValueError("lt must be [a_ms,b_ms,judge_ms]")
        return [
            _as_nonneg_int(lt[0], "lt[0]"),
            _as_nonneg_int(lt[1], "lt[1]"),
            _as_nonneg_int(lt[2], "lt[2]"),
        ]
    latency_ms = obj.get("latency_ms")
    if not isinstance(latency_ms, dict):
        return None
    return [
        _as_nonneg_int(latency_ms.get("a"), "latency_ms.a"),
        _as_nonneg_int(latency_ms.get("b"), "latency_ms.b"),
        _as_nonneg_int(latency_ms.get("judge"), "latency_ms.judge"),
    ]


def _extract_decision_canon(obj: Dict[str, Any]) -> Dict[str, Any]:
    parse_valid = obj.get("parse_valid")
    if parse_valid is not True:
        raise ValueError("decision requested but parse_valid is not true")

    has_v1 = any(k in obj for k in schema.DECISION_FIELDS)
    has_v2 = any(k in obj for k in schema.DECISION_FIELDS_V2)
    if has_v1 and has_v2:
        raise ValueError("record mixes v1 and v2 decision keys")
    if not has_v1 and not has_v2:
        raise ValueError("record missing decision keys")

    if has_v2:
        view: Dict[str, Any] = {}
        for k in schema.DECISION_FIELDS_V2:
            view[k] = obj.get(k)
    else:
        view = {}
        for k in schema.DECISION_FIELDS:
            view[k] = obj.get(k)

    canon, cerrs = schema.canonicalize_decision_obj(view)
    if canon is None:
        raise ValueError("; ".join(cerrs))
    errs = list(cerrs)
    errs.extend(schema.validate_decision(canon))
    errs.extend(schema.validate_decision_strict_extra(canon))
    if len(errs) != 0:
        raise ValueError("; ".join(errs))
    return canon


def _compact_record_v5(obj: Dict[str, Any]) -> Dict[str, Any]:
    tk = _extract_tokens4(obj)
    lt = _extract_latency3(obj)
    if tk is None or lt is None:
        raise ValueError("missing tokens/latency budgets (need tokens+latency_ms or tk+lt)")

    out: Dict[str, Any] = {
        "schema": schema.SCHEMA_RECORD_V5,
        "pair_id": str(obj.get("pair_id", "")),
        "model_a": str(obj.get("model_a", "")),
        "model_b": str(obj.get("model_b", "")),
        "judge_model": str(obj.get("judge_model", "")),
        "parse_valid": bool(obj.get("parse_valid", False)),
        "tk": tk,
        "lt": lt,
    }
    for opt in ("task_id", "sample_id"):
        v = obj.get(opt)
        if isinstance(v, str) and v != "":
            out[opt] = v

    if out["parse_valid"] is True:
        canon = _extract_decision_canon(obj)
        out["w"] = canon.get("winner")
        out["m"] = canon.get("margin")
        out["sa"] = canon.get("score_a")
        out["sb"] = canon.get("score_b")
        out["r"] = canon.get("reason")
        out["h"] = canon.get("train_hint")
        out["t"] = canon.get("tags")
    else:
        raw = obj.get("raw")
        parse_error = obj.get("parse_error")
        if isinstance(raw, str) and raw != "":
            out["raw"] = raw[:512]
        if isinstance(parse_error, str) and parse_error != "":
            out["parse_error"] = parse_error[:128]

    errs = schema.validate_record(out)
    if len(errs) != 0:
        raise ValueError("v5 output failed validation: " + "; ".join(errs))
    return out


def iter_compacted_records(paths: Sequence[str], skip_invalid: bool) -> Iterable[Tuple[str, int, Dict[str, Any]]]:
    for path in paths:
        for lineno, obj in schema.iter_jsonl(path):
            errs = schema.validate_record(obj)
            if len(errs) != 0:
                if skip_invalid:
                    continue
                raise ValueError(f"{path}:{lineno}: invalid record: " + "; ".join(errs))
            try:
                out = _compact_record_v5(obj)
            except Exception as e:
                if skip_invalid:
                    continue
                raise ValueError(f"{path}:{lineno}: {e}") from e
            yield path, lineno, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True, help="input JSONL path (repeatable)")
    ap.add_argument("--out", required=True, help="output JSONL path (record_v5)")
    ap.add_argument("--skip-invalid", action="store_true", help="skip invalid/uncompactable inputs instead of failing")
    ap.add_argument("--quiet", action="store_true", help="suppress stderr counters")
    args = ap.parse_args()

    count_in = 0
    count_out = 0
    count_skipped = 0
    with open(str(args.out), "w", encoding="utf-8") as f:
        for _path, _lineno, obj in iter_compacted_records([str(p) for p in args.inputs], skip_invalid=bool(args.skip_invalid)):
            count_out += 1
            f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))
            f.write("\n")

    if bool(args.skip_invalid):
        for path in args.inputs:
            for _lineno, _obj in schema.iter_jsonl(str(path)):
                count_in += 1
        count_skipped = (count_in - count_out)

    if not bool(args.quiet):
        _print_err(f"records_out={count_out}")
        if count_skipped != 0:
            _print_err(f"records_skipped={count_skipped}")


if __name__ == "__main__":
    main()
