#!/usr/bin/env python3
"""Annotate or filter entropy-buffer JSONL records using useful-novelty heuristics."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

try:
    from scripts import entropy_buffer_lib as lib
except ModuleNotFoundError:
    import entropy_buffer_lib as lib


def annotate_records(records: Sequence[Dict[str, Any]], drop_flagged_task_runs: bool = False, preserve_existing: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for obj in records:
        c = lib.canonicalize_record(obj)
        if c.rtype != "task_run":
            out.append(obj)
            continue

        if preserve_existing and ("useful_novelty_flags" in obj or "useful_novelty_flagged" in obj):
            if drop_flagged_task_runs and bool(obj.get("useful_novelty_flagged", False)) is True:
                continue
            out.append(obj)
            continue

        flags = lib.useful_novelty_flags(c.output, c.prompt)
        flagged = (len(flags) != 0)
        if drop_flagged_task_runs and flagged:
            continue
        mutated = dict(obj)
        mutated["useful_novelty_flags"] = list(flags)
        mutated["useful_novelty_flagged"] = bool(flagged)
        mutated["useful_novelty_flag_count"] = int(len(flags))
        out.append(mutated)
    return(out)


def _write_jsonl(records: Sequence[Dict[str, Any]], path: str) -> None:
    if path == "" or path == "-":
        f = sys.stdout
    else:
        f = open(path, "w", encoding="utf-8")
    try:
        for obj in records:
            f.write(json.dumps(obj, sort_keys=True) + "\n")
    finally:
        if f is not sys.stdout:
            f.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Annotate or filter entropy-buffer JSONL using useful-novelty heuristics.")
    p.add_argument("--in-jsonl", action="append", default=[], help="Input JSONL path (repeatable).")
    p.add_argument("--out-jsonl", default="-", help="Write annotated JSONL to this path ('-' for stdout).")
    p.add_argument("--drop-flagged-task-runs", action="store_true", help="Drop task_run records flagged by useful-novelty heuristics.")
    p.add_argument("--preserve-existing", action="store_true", help="If record already has useful-novelty fields, do not overwrite.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if len(args.in_jsonl) == 0:
        raise SystemExit("--in-jsonl is required (repeatable)")

    records = lib.load_jsonl(args.in_jsonl)
    annotated = annotate_records(records, drop_flagged_task_runs=bool(args.drop_flagged_task_runs), preserve_existing=bool(args.preserve_existing))
    _write_jsonl(annotated, str(args.out_jsonl))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())

