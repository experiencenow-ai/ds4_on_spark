#!/usr/bin/env python3
"""Canonicalize mixed entropy-buffer JSONL logs into a stable schema.

This tool normalizes loosely-shaped task-run and judge-pair records into:

- type="task_run": standard fields + optional token/latency instrumentation
- type="judge_pair": standard fields + optional judge token/latency instrumentation

It is deterministic and intended as a bridge between baseline runtime logs,
judge ELO envelopes, and the entropy-buffer metrics/recommender tooling.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

try:
    from scripts import entropy_buffer_lib as lib
except ModuleNotFoundError:
    import entropy_buffer_lib as lib


def _get_bool(obj: Dict[str, Any], name: str) -> Optional[bool]:
    if name not in obj:
        return(None)
    v = obj.get(name)
    if isinstance(v, bool):
        return(v)
    if isinstance(v, (int, float)):
        if v == 0:
            return(False)
        if v == 1:
            return(True)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "t", "yes", "y", "1"):
            return(True)
        if s in ("false", "f", "no", "n", "0"):
            return(False)
    return(None)


def _task_run_instrumentation(raw: Dict[str, Any]) -> Dict[str, Any]:
    itok = lib.get_int(raw, "input_tokens", "prompt_tokens", "input_token_count", "tokens_in")
    otok = lib.get_int(raw, "output_tokens", "completion_tokens", "output_token_count", "tokens_out")
    wms = lib.get_float(raw, "wall_ms", "latency_ms", "duration_ms", "elapsed_ms")
    toks = raw.get("tokens", None)
    if itok is None and isinstance(toks, dict):
        itok = lib.get_int(toks, "in", "input", "prompt", "prompt_tokens", "tokens_in")
    if otok is None and isinstance(toks, dict):
        otok = lib.get_int(toks, "out", "output", "completion", "completion_tokens", "tokens_out")
    lats = raw.get("latency_ms", None)
    if wms is None and isinstance(lats, dict):
        wms = lib.get_float(lats, "total", "wall", "elapsed", "duration", "run", "task")

    out: Dict[str, Any] = {}
    if itok is not None:
        out["input_tokens"] = int(itok)
    if otok is not None:
        out["output_tokens"] = int(otok)
    if wms is not None:
        out["wall_ms"] = float(wms)
    return(out)


def _judge_instrumentation(raw: Dict[str, Any]) -> Dict[str, Any]:
    toks = raw.get("tokens", None)
    lats = raw.get("latency_ms", None)
    out: Dict[str, Any] = {}
    if isinstance(toks, dict):
        jin = lib.get_int(toks, "judge_in", "in", "input", "prompt")
        jout = lib.get_int(toks, "judge_out", "out", "output", "completion")
        if jin is not None:
            out.setdefault("tokens", {})["judge_in"] = int(jin)
        if jout is not None:
            out.setdefault("tokens", {})["judge_out"] = int(jout)
    if isinstance(lats, dict):
        jlat = lib.get_float(lats, "judge", "total", "wall", "elapsed", "duration")
        if jlat is not None:
            out.setdefault("latency_ms", {})["judge"] = float(jlat)
    return(out)


def canonicalize_records(records: Sequence[Dict[str, Any]], drop_unknown: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for obj in records:
        c = lib.canonicalize_record(obj)
        if drop_unknown and c.rtype == "unknown":
            continue

        if c.rtype == "task_run":
            rec: Dict[str, Any] = {
                "type": "task_run",
                "run_id": c.run_id,
                "task_id": c.task_id,
                "task_family": c.task_family,
                "prompt_template_id": c.prompt_template_id,
                "model_id": c.model_id,
                "prompt": c.prompt,
                "output": c.output,
                "answer": c.answer,
                "answer_source": c.answer_source,
                "buffer_id": c.buffer_id,
                "buffer_item_id": c.buffer_item_id,
            }
            tags = lib.get_list(c.raw, "tags", "tag")
            if len(tags) != 0:
                rec["tags"] = tags
            rec.update(_task_run_instrumentation(c.raw))
            out.append(rec)
            continue

        if c.rtype == "judge_pair":
            item_id = c.item_id
            if item_id == "":
                item_id = lib.make_item_id(c.task_id, c.prompt_template_id, c.a_model_id, c.b_model_id)
            rec = {
                "type": "judge_pair",
                "judge_id": c.judge_id,
                "item_id": item_id,
                "task_id": c.task_id,
                "task_family": c.task_family,
                "prompt_template_id": c.prompt_template_id,
                "a_model_id": c.a_model_id,
                "b_model_id": c.b_model_id,
                "label": c.label,
                "buffer_id": c.buffer_id,
            }
            parse_valid = _get_bool(c.raw, "parse_valid")
            if parse_valid is not None:
                rec["parse_valid"] = bool(parse_valid)
            tags = lib.get_list(c.raw, "tags", "tag")
            if len(tags) != 0:
                rec["tags"] = tags
            rec.update(_judge_instrumentation(c.raw))
            out.append(rec)
            continue

        out.append({
            "type": "unknown",
            "raw": dict(obj),
        })
    return(out)


def iter_canonical_jsonl(paths: Sequence[str], drop_unknown: bool = False) -> Iterator[Dict[str, Any]]:
    for obj in lib.load_jsonl(paths):
        for rec in canonicalize_records([obj], drop_unknown=drop_unknown):
            yield(rec)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Canonicalize mixed entropy-buffer JSONL logs.")
    p.add_argument("--in-jsonl", action="append", default=[], help="Input JSONL (repeatable).")
    p.add_argument("--out-jsonl", default="", help="Write canonical JSONL to this path (default: stdout).")
    p.add_argument("--drop-unknown", action="store_true", help="Drop unrecognized records.")
    args = p.parse_args(list(argv) if argv is not None else None)

    if len(args.in_jsonl) == 0:
        raise SystemExit("error: at least one --in-jsonl is required")

    out_f = sys.stdout
    close_out = False
    if args.out_jsonl != "":
        out_f = open(args.out_jsonl, "w", encoding="utf-8")
        close_out = True

    try:
        for rec in iter_canonical_jsonl(args.in_jsonl, drop_unknown=bool(args.drop_unknown)):
            out_f.write(json.dumps(rec, sort_keys=True) + "\n")
    finally:
        if close_out:
            out_f.close()
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())

