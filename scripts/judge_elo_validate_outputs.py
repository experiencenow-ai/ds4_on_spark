#!/usr/bin/env python3
"""Validate scripts/judge_elo_update.py output directory (offline)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List, Tuple

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


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_dir(out_dir: str) -> int:
    bad = 0
    paths: List[Tuple[str, Any, str]] = [
        ("meta.json", schema.validate_meta, "meta"),
        ("budget.json", schema.validate_budget, "budget"),
        ("quality_map.json", schema.validate_quality_map, "quality_map"),
        ("leaderboard.json", schema.validate_leaderboard, "leaderboard"),
    ]
    for rel, fn, label in paths:
        path = os.path.join(out_dir, rel)
        if not os.path.exists(path):
            bad += 1
            _print_err(f"{path}: missing")
            continue
        obj = _read_json(path)
        errs = fn(obj)
        if len(errs) == 0:
            continue
        bad += 1
        for e in errs:
            _print_err(f"{path}: {e}")
    if bad == 0:
        return 0
    _print_err(f"invalid_outputs={bad}")
    return 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, help="output directory from scripts/judge_elo_update.py")
    args = ap.parse_args()
    raise SystemExit(validate_dir(str(args.out_dir)))


if __name__ == "__main__":
    main()

