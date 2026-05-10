#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _as_dict(obj: object) -> Optional[Dict[str, object]]:
    if isinstance(obj, dict):
        return(obj)  # type: ignore[return-value]
    return(None)


def _deep_candidates_container(obj: Dict[str, object]) -> Optional[Dict[str, object]]:
    for k in ("route", "routing", "router", "moe", "moe_route", "dispatch"):
        inner = _as_dict(obj.get(k))
        if inner is not None:
            return(inner)
    return(None)


def _get_any(obj: Dict[str, object], keys: Iterable[str]) -> Optional[object]:
    for k in keys:
        if k in obj:
            return(obj.get(k))
    return(None)


def _extract_time(obj: Dict[str, object]) -> Tuple[Optional[float], Optional[float]]:
    t_raw = _get_any(obj, ("t_ms", "ts_ms", "timestamp_ms", "time_ms"))
    if t_raw is not None:
        if not isinstance(t_raw, (int, float)):
            raise ValueError("time field must be a number")
        return(float(t_raw), None)

    t_us_raw = _get_any(obj, ("t_us", "ts_us", "timestamp_us", "time_us"))
    if t_us_raw is not None:
        if not isinstance(t_us_raw, (int, float)):
            raise ValueError("time_us field must be a number")
        return(float(t_us_raw) / 1000.0, None)

    dt_raw = _get_any(obj, ("dt_ms", "delta_ms"))
    if dt_raw is not None:
        if not isinstance(dt_raw, (int, float)):
            raise ValueError("dt_ms field must be a number")
        return(None, float(dt_raw))

    dt_us_raw = _get_any(obj, ("dt_us", "delta_us"))
    if dt_us_raw is not None:
        if not isinstance(dt_us_raw, (int, float)):
            raise ValueError("dt_us field must be a number")
        return(None, float(dt_us_raw) / 1000.0)

    return(None, None)


def _extract_cls(obj: Dict[str, object]) -> Optional[str]:
    cls_raw = _get_any(obj, ("cls", "latency_class", "lat_class"))
    if isinstance(cls_raw, str):
        v = cls_raw.strip().lower()
        if v in ("interactive", "hi"):
            return("interactive")
        if v in ("batch", "lo"):
            return("batch")
        return(None)

    is_interactive = _get_any(obj, ("is_interactive", "interactive"))
    if isinstance(is_interactive, bool):
        return("interactive" if is_interactive else "batch")

    return(None)


def _extract_int_list(value: object) -> Optional[List[int]]:
    if not isinstance(value, list):
        return(None)
    out: List[int] = []
    for v in value:
        if not isinstance(v, int):
            return(None)
        if v < 0:
            return(None)
        out.append(int(v))
    if len(out) == 0:
        return(None)
    if len(set(out)) != len(out):
        return(None)
    return(out)


def _extract_float_list(value: object) -> Optional[List[float]]:
    if not isinstance(value, list):
        return(None)
    out: List[float] = []
    for v in value:
        if not isinstance(v, (int, float)):
            return(None)
        out.append(float(v))
    if len(out) == 0:
        return(None)
    return(out)


def _extract_layer_record(obj_in: object) -> Optional[Dict[str, object]]:
    obj = _as_dict(obj_in)
    if obj is None:
        return(None)

    container = _deep_candidates_container(obj) or obj
    cand_raw = _get_any(container, ("candidates", "experts", "expert_ids", "top_experts"))
    candidates = _extract_int_list(cand_raw)
    if candidates is None:
        return(None)

    out: Dict[str, object] = {"candidates": candidates}

    scores_raw = _get_any(container, ("scores", "router_scores", "probs"))
    scores = _extract_float_list(scores_raw)
    if scores is not None:
        if len(scores) == len(candidates):
            out["scores"] = scores

    k = _get_any(container, ("k", "chosen_k"))
    if isinstance(k, int) and k > 0:
        out["k"] = int(k)

    cost_scale = _get_any(container, ("cost_scale", "cost", "work_scale"))
    if isinstance(cost_scale, (int, float)) and float(cost_scale) > 0.0:
        out["cost_scale"] = float(cost_scale)

    return(out)


def _extract_layers(obj: Dict[str, object]) -> Optional[List[Dict[str, object]]]:
    layers_raw = _get_any(obj, ("layers", "moe_layers", "router_layers", "route_layers"))
    if not isinstance(layers_raw, list):
        return(None)
    out: List[Dict[str, object]] = []
    for layer in layers_raw:
        rec = _extract_layer_record(layer)
        if rec is None:
            return(None)
        out.append(rec)
    if len(out) == 0:
        return(None)
    return(out)


def extract_route_record(obj_in: object, route_type: str = "") -> Optional[Dict[str, object]]:
    obj = _as_dict(obj_in)
    if obj is None:
        return(None)

    if route_type != "":
        t = obj.get("type")
        if not isinstance(t, str) or t.strip().lower() != route_type.strip().lower():
            return(None)

    out: Dict[str, object] = {}

    token_index = _get_any(obj, ("token_index", "token_idx", "idx", "i"))
    if isinstance(token_index, int) and token_index >= 0:
        out["token_index"] = int(token_index)

    t_ms, dt_ms = _extract_time(obj)
    if t_ms is not None:
        out["t_ms"] = float(t_ms)
    elif dt_ms is not None:
        out["dt_ms"] = float(dt_ms)
    else:
        return(None)

    cls = _extract_cls(obj)
    if cls is None:
        return(None)
    out["cls"] = cls

    container = _deep_candidates_container(obj) or obj
    layers = _extract_layers(container)
    if layers is not None:
        out["layers"] = layers
        seen = set()
        union_candidates: List[int] = []
        for layer in layers:
            layer_cands = layer.get("candidates")
            if not isinstance(layer_cands, list):
                return(None)
            for e in layer_cands:
                if not isinstance(e, int) or e < 0:
                    return(None)
                if e in seen:
                    continue
                seen.add(e)
                union_candidates.append(int(e))
        if len(union_candidates) == 0:
            return(None)
        out["candidates"] = union_candidates
    else:
        cand_raw = _get_any(container, ("candidates", "experts", "expert_ids", "top_experts"))
        candidates = _extract_int_list(cand_raw)
        if candidates is None:
            return(None)
        out["candidates"] = candidates

        scores_raw = _get_any(container, ("scores", "router_scores", "probs"))
        scores = _extract_float_list(scores_raw)
        if scores is not None:
            if len(scores) == len(candidates):
                out["scores"] = scores

        k = _get_any(container, ("k", "chosen_k"))
        if isinstance(k, int) and k > 0:
            out["k"] = int(k)

    mtp_accept_len = _get_any(obj, ("mtp_accept_len", "accept_len", "mtp_len"))
    if isinstance(mtp_accept_len, int) and mtp_accept_len > 0:
        out["mtp_accept_len"] = int(mtp_accept_len)

    accepted_mtp = _get_any(obj, ("accepted_mtp", "mtp_accepted"))
    if isinstance(accepted_mtp, int) and accepted_mtp >= 0:
        out["accepted_mtp"] = int(accepted_mtp)

    rejected_mtp = _get_any(obj, ("rejected_mtp", "mtp_rejected"))
    if isinstance(rejected_mtp, int) and rejected_mtp >= 0:
        out["rejected_mtp"] = int(rejected_mtp)

    cost_scale = _get_any(obj, ("cost_scale", "cost", "work_scale"))
    if isinstance(cost_scale, (int, float)) and float(cost_scale) > 0.0:
        out["cost_scale"] = float(cost_scale)

    decode_ms = _get_any(obj, ("decode_ms", "latency_ms", "dt_decode_ms"))
    if isinstance(decode_ms, (int, float)) and float(decode_ms) >= 0.0:
        out["decode_ms"] = float(decode_ms)

    kv_tokens = _get_any(obj, ("kv_tokens", "kv_len", "kv_cache_tokens"))
    if isinstance(kv_tokens, int) and kv_tokens >= 0:
        out["kv_tokens"] = int(kv_tokens)

    expert_batch_size = _get_any(obj, ("expert_batch_size", "batch_size", "expert_bs"))
    if isinstance(expert_batch_size, int) and expert_batch_size >= 0:
        out["expert_batch_size"] = int(expert_batch_size)

    return(out)


def extract_jsonl_lines(lines: Iterable[str], route_type: str = "", non_route_policy: str = "skip") -> List[Dict[str, object]]:
    if non_route_policy not in ("skip", "error"):
        raise ValueError("non_route_policy must be one of: skip, error")
    out: List[Dict[str, object]] = []
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if line == "":
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            if non_route_policy == "error":
                raise ValueError(f"line {lineno}: invalid JSON")
            continue
        rec = extract_route_record(obj, route_type=route_type)
        if rec is None:
            if non_route_policy == "error":
                raise ValueError(f"line {lineno}: could not extract route record")
            continue
        out.append(rec)
    return(out)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Extract scheduler-simulator route records from loosely shaped/mixed JSONL logs (optionally skipping non-JSON lines).")
    p.add_argument("--in-jsonl", type=str, default="-", help="Input JSONL path ('-' for stdin).")
    p.add_argument("--out-jsonl", type=str, default="-", help="Output JSONL path ('-' for stdout).")
    p.add_argument("--route-type", type=str, default="", help="Only extract records with obj.type == route-type (empty = auto).")
    p.add_argument("--non-route", type=str, default="skip", help="What to do for non-route input: skip (default; also skips non-JSON lines) or error.")
    args = p.parse_args(argv)

    f_in = sys.stdin if args.in_jsonl == "-" else open(args.in_jsonl, "r", encoding="utf-8")
    try:
        recs = extract_jsonl_lines(f_in, route_type=args.route_type.strip(), non_route_policy=args.non_route.strip().lower())
    finally:
        if f_in is not sys.stdin:
            f_in.close()

    meta: Dict[str, object] = {"extracted_routes": len(recs)}
    if args.route_type.strip() != "":
        meta["route_type"] = args.route_type.strip()

    f_out = sys.stdout if args.out_jsonl == "-" else open(args.out_jsonl, "w", encoding="utf-8")
    try:
        f_out.write(json.dumps({"type": "meta", "meta": meta}, separators=(",", ":")) + "\n")
        for rec in recs:
            f_out.write(json.dumps(rec, separators=(",", ":")) + "\n")
    finally:
        if f_out is not sys.stdout:
            f_out.close()

    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
