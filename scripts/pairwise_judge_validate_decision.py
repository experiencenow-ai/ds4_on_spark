#!/usr/bin/env python3
"""Validate and canonicalize a raw DSv4 pairwise judge decision object (offline).

This script does not call any paid API. It is intended for harnesses and local
debugging when the judge model output may contain extra text around a JSON
object.

Exit codes:
- 0: parsed + schema-valid decision
- 2: parse/validation error
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional, Tuple

try:
    from scripts import judge_elo_schema as schema
except ModuleNotFoundError:
    # Allow running as a script from repo root.
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from scripts import judge_elo_schema as schema


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_and_validate_decision_text(text: str, strict: bool) -> Tuple[Optional[Dict[str, Any]], str]:
    obj, perr = schema.parse_json_object_loose(text)
    if obj is None:
        return None, str(perr)
    errs = schema.validate_decision(obj)
    if len(errs) != 0:
        return None, "; ".join(errs)
    if strict:
        extra = schema.validate_decision_strict_extra(obj)
        if len(extra) != 0:
            return None, "; ".join(extra)
    return obj, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="input_path", required=True, help="path to raw judge decision output text")
    ap.add_argument("--pretty", action="store_true", help="pretty-print JSON (default: minified)")
    ap.add_argument("--strict", action="store_true", help="enforce strict margin/score and compact tag constraints")
    args = ap.parse_args()

    text = _read_text(str(args.input_path))
    obj, err = parse_and_validate_decision_text(text, strict=bool(args.strict))
    if obj is None:
        _print_err(f"{str(args.input_path)}: {err}")
        raise SystemExit(2)

    if bool(args.pretty):
        print(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
