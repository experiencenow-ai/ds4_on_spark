#!/usr/bin/env python3
"""Validate judge ELO JSONL records against the compact schema."""

from __future__ import annotations

import argparse
import sys
from typing import List

try:
    from scripts import judge_elo_schema as schema
except ModuleNotFoundError:
    # Allow running as a script from repo root.
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from scripts import judge_elo_schema as schema


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def validate_paths(paths: List[str]) -> int:
    bad = 0
    for path in paths:
        for lineno, obj in schema.iter_jsonl(path):
            errs = schema.validate_record(obj)
            if len(errs) == 0:
                continue
            bad += 1
            for e in errs:
                _print_err(f"{path}:{lineno}: {e}")
    if bad == 0:
        return 0
    _print_err(f"invalid_records={bad}")
    return 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True, help="input JSONL path (repeatable)")
    ap.add_argument("--strict", action="store_true", help="require tokens and latency_ms accounting fields")
    args = ap.parse_args()
    if args.strict:
        bad = 0
        for path in args.inputs:
            for lineno, obj in schema.iter_jsonl(path):
                errs = schema.validate_record_strict(obj)
                if len(errs) == 0:
                    continue
                bad += 1
                for e in errs:
                    _print_err(f"{path}:{lineno}: {e}")
        if bad == 0:
            raise SystemExit(0)
        _print_err(f"invalid_records={bad}")
        raise SystemExit(2)
    raise SystemExit(validate_paths(args.inputs))


if __name__ == "__main__":
    main()
