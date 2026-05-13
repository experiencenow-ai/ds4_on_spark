#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _as_dict(obj: object) -> Optional[Dict[str, object]]:
    if isinstance(obj, dict):
        return(obj)  # type: ignore[return-value]
    return(None)

_INT_RE = re.compile(r"^[+-]?[0-9]+$")
_INTLIKE_FLOAT_RE = re.compile(r"^[+-]?[0-9]+(?:\.0+)?$")


def _coerce_float(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        v = float(value)
        if math.isfinite(v) is False:
            return(None)
        return(float(v))
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return(None)
        try:
            v = float(s)
        except ValueError:
            return(None)
        if math.isfinite(v) is False:
            return(None)
        return(float(v))
    return(None)

def _coerce_int(value: object) -> Optional[int]:
    if isinstance(value, int):
        return(int(value))
    if isinstance(value, float):
        v = float(value)
        if float(int(v)) == v:
            return(int(v))
        return(None)
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return(None)
        if _INT_RE.match(s) is not None:
            try:
                return(int(s))
            except ValueError:
                return(None)
        if _INTLIKE_FLOAT_RE.match(s) is not None:
            try:
                v = float(s)
            except ValueError:
                return(None)
            if math.isfinite(v) is False:
                return(None)
            if float(int(v)) == v:
                return(int(v))
            return(None)
    return(None)

def _coerce_nonneg_int(value: object) -> Optional[int]:
    v = _coerce_int(value)
    if v is None:
        return(None)
    if int(v) < 0:
        return(None)
    return(int(v))

def _coerce_pos_int(value: object) -> Optional[int]:
    v = _coerce_int(value)
    if v is None:
        return(None)
    if int(v) <= 0:
        return(None)
    return(int(v))


def _deep_candidates_container(obj: Dict[str, object]) -> Optional[Dict[str, object]]:
    for k in ("route", "routing", "router", "moe", "moe_route", "dispatch"):
        inner = _as_dict(obj.get(k))
        if inner is not None:
            return(inner)
    return(None)


def _deep_mtp_container(obj: Dict[str, object]) -> Optional[Dict[str, object]]:
    for k in ("mtp", "mtp_stats"):
        inner = _as_dict(obj.get(k))
        if inner is not None:
            return(inner)
    return(None)


def _deep_dflash_container(obj: Dict[str, object]) -> Optional[Dict[str, object]]:
    for k in ("dflash", "dflash_stats", "flash", "flash_stats", "spec_decode", "speculative", "speculative_decode", "spec"):
        inner = _as_dict(obj.get(k))
        if inner is not None:
            return(inner)
    return(None)


def _get_any(obj: Dict[str, object], keys: Iterable[str]) -> Optional[object]:
    for k in keys:
        if k in obj:
            return(obj.get(k))
    return(None)


def _iter_json_values_from_line(line: str, allow_substrings: bool) -> Iterable[object]:
    line = line.strip()
    if line == "":
        return

    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        obj = None

    if obj is not None:
        if isinstance(obj, list):
            for item in obj:
                yield(item)
            return
        yield(obj)
        return

    if allow_substrings is False:
        return

    decoder = json.JSONDecoder()
    i = 0
    while True:
        start = line.find("{", i)
        if start < 0:
            return
        try:
            obj, end = decoder.raw_decode(line[start:])
        except json.JSONDecodeError:
            i = start + 1
            continue
        yield(obj)
        i = start + max(1, int(end))


def _extract_time(obj: Dict[str, object]) -> Tuple[Optional[float], Optional[float]]:
    t_raw = _get_any(obj, ("t_ms", "ts_ms", "timestamp_ms", "time_ms"))
    if t_raw is not None:
        t_ms = _coerce_float(t_raw)
        if t_ms is None:
            raise ValueError("time field must be a number")
        return(float(t_ms), None)

    t_us_raw = _get_any(obj, ("t_us", "ts_us", "timestamp_us", "time_us"))
    if t_us_raw is not None:
        t_us = _coerce_float(t_us_raw)
        if t_us is None:
            raise ValueError("time_us field must be a number")
        return(float(t_us) / 1000.0, None)

    t_ns_raw = _get_any(obj, ("t_ns", "ts_ns", "timestamp_ns", "time_ns"))
    if t_ns_raw is not None:
        t_ns = _coerce_float(t_ns_raw)
        if t_ns is None:
            raise ValueError("time_ns field must be a number")
        return(float(t_ns) / 1_000_000.0, None)

    dt_raw = _get_any(obj, ("dt_ms", "delta_ms"))
    if dt_raw is not None:
        dt_ms = _coerce_float(dt_raw)
        if dt_ms is None:
            raise ValueError("dt_ms field must be a number")
        return(None, float(dt_ms))

    dt_us_raw = _get_any(obj, ("dt_us", "delta_us"))
    if dt_us_raw is not None:
        dt_us = _coerce_float(dt_us_raw)
        if dt_us is None:
            raise ValueError("dt_us field must be a number")
        return(None, float(dt_us) / 1000.0)

    dt_ns_raw = _get_any(obj, ("dt_ns", "delta_ns"))
    if dt_ns_raw is not None:
        dt_ns = _coerce_float(dt_ns_raw)
        if dt_ns is None:
            raise ValueError("dt_ns field must be a number")
        return(None, float(dt_ns) / 1_000_000.0)

    return(None, None)


def _extract_cls(obj: Dict[str, object]) -> Optional[str]:
    cls_raw = _get_any(obj, ("cls", "latency_class", "lat_class", "cls_id", "latency_class_id", "lat_class_id", "qos", "priority"))
    if isinstance(cls_raw, str):
        v = cls_raw.strip().lower()
        if v in ("interactive", "hi", "high"):
            return("interactive")
        if v in ("batch", "lo", "low"):
            return("batch")
        if v in ("0", "+0"):
            return("interactive")
        if v in ("1", "+1"):
            return("batch")
        return(None)

    vi = _coerce_int(cls_raw)
    if vi is not None:
        if int(vi) == 0:
            return("interactive")
        if int(vi) == 1:
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
        vi = _coerce_nonneg_int(v)
        if vi is None:
            return(None)
        out.append(int(vi))
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


def _extract_candidates(container: Dict[str, object]) -> Optional[List[int]]:
    cand_raw = _get_any(
        container,
        (
            "candidates",
            "experts",
            "expert_ids",
            "top_experts",
            "chosen_experts",
            "selected_experts",
            "topk_experts",
        ),
    )
    candidates = _extract_int_list(cand_raw)
    if candidates is not None:
        return(candidates)

    expert_raw = _get_any(container, ("expert", "expert_id", "chosen_expert", "selected_expert", "top_expert"))
    ei = _coerce_nonneg_int(expert_raw)
    if ei is not None:
        return([int(ei)])
    return(None)


def _extract_layer_record(obj_in: object) -> Optional[Dict[str, object]]:
    obj = _as_dict(obj_in)
    if obj is None:
        return(None)

    container = _deep_candidates_container(obj) or obj
    candidates = _extract_candidates(container)
    if candidates is None:
        return(None)

    out: Dict[str, object] = {"candidates": candidates}

    scores_raw = _get_any(container, ("scores", "router_scores", "probs"))
    scores = _extract_float_list(scores_raw)
    if scores is not None:
        if len(scores) == len(candidates):
            out["scores"] = scores

    k = _get_any(container, ("k", "chosen_k"))
    ki = _coerce_pos_int(k)
    if ki is not None:
        out["k"] = int(ki)

    cost_scale_raw = _get_any(container, ("cost_scale", "cost", "work_scale"))
    cost_scale = _coerce_float(cost_scale_raw)
    if cost_scale is not None and float(cost_scale) > 0.0:
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


def extract_route_record(obj_in: object, route_type: str = "", default_cls: str = "") -> Optional[Dict[str, object]]:
    obj = _as_dict(obj_in)
    if obj is None:
        return(None)

    if route_type != "":
        t = obj.get("type")
        if not isinstance(t, str) or t.strip().lower() != route_type.strip().lower():
            return(None)

    out: Dict[str, object] = {}

    token_index = _get_any(obj, ("token_index", "token_idx", "idx", "i"))
    ti = _coerce_nonneg_int(token_index)
    if ti is not None:
        out["token_index"] = int(ti)

    layer_index = _get_any(obj, ("layer_index", "layer_idx", "moe_layer", "moe_layer_index", "layer", "layer_id"))
    li = _coerce_nonneg_int(layer_index)
    if li is not None:
        out["layer_index"] = int(li)

    t_ms, dt_ms = _extract_time(obj)
    if t_ms is not None:
        out["t_ms"] = float(t_ms)
    elif dt_ms is not None:
        out["dt_ms"] = float(dt_ms)
    else:
        return(None)

    cls = _extract_cls(obj)
    if cls is None and default_cls.strip() != "":
        d = default_cls.strip().lower()
        if d not in ("interactive", "batch"):
            raise ValueError("default_cls must be 'interactive' or 'batch'")
        cls = d
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
                ei = _coerce_nonneg_int(e)
                if ei is None:
                    return(None)
                if ei in seen:
                    continue
                seen.add(int(ei))
                union_candidates.append(int(ei))
        if len(union_candidates) == 0:
            return(None)
        out["candidates"] = union_candidates
    else:
        candidates = _extract_candidates(container)
        if candidates is None:
            return(None)
        out["candidates"] = candidates

        scores_raw = _get_any(container, ("scores", "router_scores", "probs"))
        scores = _extract_float_list(scores_raw)
        if scores is not None:
            if len(scores) == len(candidates):
                out["scores"] = scores

        k = _get_any(container, ("k", "chosen_k"))
        ki = _coerce_pos_int(k)
        if ki is not None:
            out["k"] = int(ki)

    # MTP (DeepSeek) stats:
    # - Prefer explicit mtp_* keys when available.
    # - Allow generic accept_len/accepted/rejected only inside a nested mtp container or inside the route container
    #   when mtp-specific counters are also present. This avoids mixing speculative-decoding comparator stats into MTP.
    mtp_accept_len = _get_any(obj, ("mtp_accept_len", "mtp_len"))
    if mtp_accept_len is None and container is not obj:
        mtp_accept_len = _get_any(container, ("mtp_accept_len", "mtp_len"))

    accepted_mtp = _get_any(obj, ("accepted_mtp", "mtp_accepted"))
    if accepted_mtp is None and container is not obj:
        accepted_mtp = _get_any(container, ("accepted_mtp", "mtp_accepted"))

    rejected_mtp = _get_any(obj, ("rejected_mtp", "mtp_rejected"))
    if rejected_mtp is None and container is not obj:
        rejected_mtp = _get_any(container, ("rejected_mtp", "mtp_rejected"))

    mtp = _deep_mtp_container(obj)
    if mtp is None and container is not obj:
        mtp = _deep_mtp_container(container)

    dflash = _deep_dflash_container(obj)
    if dflash is None and container is not obj:
        dflash = _deep_dflash_container(container)

    if mtp_accept_len is None and mtp is not None:
        mtp_accept_len = _get_any(mtp, ("mtp_accept_len", "accept_len", "mtp_len"))
    if mtp_accept_len is None and isinstance(container, dict):
        if "accept_len" in container and (accepted_mtp is not None or rejected_mtp is not None or ("mtp_accepted" in container) or ("mtp_rejected" in container)):
            mtp_accept_len = container.get("accept_len")
    if mtp_accept_len is None and dflash is not None:
        mtp_accept_len = _get_any(dflash, ("mtp_accept_len", "mtp_len"))
    al = _coerce_pos_int(mtp_accept_len)
    if al is not None:
        out["mtp_accept_len"] = int(al)

    if accepted_mtp is None and mtp is not None:
        accepted_mtp = _get_any(mtp, ("accepted_mtp", "mtp_accepted", "accepted"))
    if accepted_mtp is None and dflash is not None:
        accepted_mtp = _get_any(dflash, ("accepted_mtp", "mtp_accepted"))
    am = _coerce_nonneg_int(accepted_mtp)
    if am is not None:
        out["accepted_mtp"] = int(am)

    if rejected_mtp is None and mtp is not None:
        rejected_mtp = _get_any(mtp, ("rejected_mtp", "mtp_rejected", "rejected"))
    if rejected_mtp is None and dflash is not None:
        rejected_mtp = _get_any(dflash, ("rejected_mtp", "mtp_rejected"))
    rm = _coerce_nonneg_int(rejected_mtp)
    if rm is not None:
        out["rejected_mtp"] = int(rm)

    # Speculative-decoding comparator stats (kept separate from MTP).
    dflash_has_mtp_keys = False
    if dflash is not None:
        for k in ("mtp_accept_len", "mtp_len", "accepted_mtp", "mtp_accepted", "rejected_mtp", "mtp_rejected"):
            if k in dflash:
                dflash_has_mtp_keys = True
                break

    dflash_accept_len = _get_any(obj, ("dflash_accept_len", "spec_accept_len"))
    if dflash_accept_len is None and container is not obj:
        dflash_accept_len = _get_any(container, ("dflash_accept_len", "spec_accept_len"))
    if dflash_accept_len is None and dflash is not None and dflash_has_mtp_keys is False:
        dflash_accept_len = _get_any(dflash, ("dflash_accept_len", "spec_accept_len", "accept_len"))
    dal = _coerce_pos_int(dflash_accept_len)
    if dal is not None:
        out["dflash_accept_len"] = int(dal)

    accepted_dflash = _get_any(obj, ("accepted_dflash", "dflash_accepted", "spec_accepted"))
    if accepted_dflash is None and container is not obj:
        accepted_dflash = _get_any(container, ("accepted_dflash", "dflash_accepted", "spec_accepted"))
    if accepted_dflash is None and dflash is not None and dflash_has_mtp_keys is False:
        accepted_dflash = _get_any(dflash, ("accepted_dflash", "dflash_accepted", "spec_accepted", "accepted"))
    ad = _coerce_nonneg_int(accepted_dflash)
    if ad is not None:
        out["accepted_dflash"] = int(ad)

    rejected_dflash = _get_any(obj, ("rejected_dflash", "dflash_rejected", "spec_rejected"))
    if rejected_dflash is None and container is not obj:
        rejected_dflash = _get_any(container, ("rejected_dflash", "dflash_rejected", "spec_rejected"))
    if rejected_dflash is None and dflash is not None and dflash_has_mtp_keys is False:
        rejected_dflash = _get_any(dflash, ("rejected_dflash", "dflash_rejected", "spec_rejected", "rejected"))
    rd = _coerce_nonneg_int(rejected_dflash)
    if rd is not None:
        out["rejected_dflash"] = int(rd)

    cost_scale_raw = _get_any(obj, ("cost_scale", "cost", "work_scale"))
    cost_scale = _coerce_float(cost_scale_raw)
    if cost_scale is not None and float(cost_scale) > 0.0:
        out["cost_scale"] = float(cost_scale)

    decode_ms_raw = _get_any(obj, ("decode_ms", "latency_ms", "dt_decode_ms"))
    decode_ms = _coerce_float(decode_ms_raw)
    if decode_ms is not None and float(decode_ms) >= 0.0:
        out["decode_ms"] = float(decode_ms)

    kv_tokens = _get_any(obj, ("kv_tokens", "kv_len", "kv_cache_tokens"))
    kv = _coerce_nonneg_int(kv_tokens)
    if kv is not None:
        out["kv_tokens"] = int(kv)

    expert_batch_size = _get_any(obj, ("expert_batch_size", "batch_size", "expert_bs"))
    bs = _coerce_nonneg_int(expert_batch_size)
    if bs is not None:
        out["expert_batch_size"] = int(bs)

    return(out)


def pack_layers_by_token_index(
    routes: Sequence[Dict[str, object]],
    require_layer_index: bool = False,
    time_policy: str = "strict",
    time_tol_ms: float = 0.0,
    strict: bool = True,
) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    by_token: Dict[int, List[Dict[str, object]]] = {}
    order: List[int] = []

    policy = str(time_policy).strip().lower()
    if policy == "":
        policy = "strict"
    if policy not in ("strict", "first", "min", "max"):
        raise ValueError("time_policy must be one of: strict, first, min, max")
    tol_ms = float(time_tol_ms)
    if tol_ms < 0.0:
        raise ValueError("time_tol_ms must be >= 0")

    for r in routes:
        ti_raw = r.get("token_index")
        if not isinstance(ti_raw, int) or ti_raw < 0:
            if strict:
                raise ValueError("pack_layers_by_token_index requires integer token_index on every route record")
            continue
        ti = int(ti_raw)
        if ti not in by_token:
            by_token[ti] = []
            order.append(ti)
        by_token[ti].append(r)

    for ti in order:
        group = by_token.get(ti, [])
        if len(group) == 0:
            continue

        first = group[0]
        cls = first.get("cls")
        if not isinstance(cls, str):
            if strict:
                raise ValueError(f"token_index={ti}: missing cls")
            continue

        have_t_ms = "t_ms" in first and first.get("t_ms") is not None
        have_dt_ms = "dt_ms" in first and first.get("dt_ms") is not None
        if have_t_ms and have_dt_ms:
            if strict:
                raise ValueError(f"token_index={ti}: record has both t_ms and dt_ms")
            have_dt_ms = False
        if have_t_ms is False and have_dt_ms is False:
            if strict:
                raise ValueError(f"token_index={ti}: missing t_ms/dt_ms")
            continue

        t_ms_vals: List[float] = [float(first.get("t_ms", 0.0))] if have_t_ms else []
        dt_ms_vals: List[float] = [float(first.get("dt_ms", 0.0))] if have_dt_ms else []

        cost_scale = first.get("cost_scale")
        decode_ms = first.get("decode_ms")
        kv_tokens = first.get("kv_tokens")
        expert_batch_size = first.get("expert_batch_size")

        mtp_accept_len = first.get("mtp_accept_len")
        accepted_mtp = first.get("accepted_mtp")
        rejected_mtp = first.get("rejected_mtp")

        dflash_accept_len = first.get("dflash_accept_len")
        accepted_dflash = first.get("accepted_dflash")
        rejected_dflash = first.get("rejected_dflash")

        for r in group[1:]:
            if r.get("cls") != cls:
                if strict:
                    raise ValueError(f"token_index={ti}: cls mismatch within pack group")
                continue

            if have_t_ms:
                if "t_ms" not in r or r.get("t_ms") is None:
                    if strict:
                        raise ValueError(f"token_index={ti}: mixed t_ms/dt_ms within pack group")
                    continue
                tv = float(r.get("t_ms"))
                if abs(tv - float(t_ms_vals[0])) > tol_ms:
                    if policy == "strict":
                        if strict:
                            raise ValueError(f"token_index={ti}: t_ms mismatch within pack group")
                        continue
                t_ms_vals.append(float(tv))
            else:
                if "dt_ms" not in r or r.get("dt_ms") is None:
                    if strict:
                        raise ValueError(f"token_index={ti}: mixed t_ms/dt_ms within pack group")
                    continue
                dv = float(r.get("dt_ms"))
                if abs(dv - float(dt_ms_vals[0])) > tol_ms:
                    if policy == "strict":
                        if strict:
                            raise ValueError(f"token_index={ti}: dt_ms mismatch within pack group")
                        continue
                dt_ms_vals.append(float(dv))

            # Only allow metadata fields to differ if they are consistently absent.
            for k, first_val in (
                ("cost_scale", cost_scale),
                ("decode_ms", decode_ms),
                ("kv_tokens", kv_tokens),
                ("expert_batch_size", expert_batch_size),
                ("mtp_accept_len", mtp_accept_len),
                ("accepted_mtp", accepted_mtp),
                ("rejected_mtp", rejected_mtp),
                ("dflash_accept_len", dflash_accept_len),
                ("accepted_dflash", accepted_dflash),
                ("rejected_dflash", rejected_dflash),
            ):
                if first_val is None:
                    continue
                if k in r and r.get(k) is not None and r.get(k) != first_val:
                    if strict:
                        raise ValueError(f"token_index={ti}: {k} mismatch within pack group")
                    continue

        layer_recs: List[Tuple[Optional[int], int, Dict[str, object]]] = []
        for idx, r in enumerate(group):
            if "layers" in r:
                if strict:
                    raise ValueError(f"token_index={ti}: per-layer pack expects one-layer records, found layers[]")
                continue
            cands = r.get("candidates")
            if not isinstance(cands, list) or len(cands) == 0:
                if strict:
                    raise ValueError(f"token_index={ti}: missing candidates")
                continue
            layer: Dict[str, object] = {"candidates": cands}
            if "scores" in r and r.get("scores") is not None:
                layer["scores"] = r.get("scores")
            if "k" in r and r.get("k") is not None:
                layer["k"] = r.get("k")
            if "cost_scale" in r and r.get("cost_scale") is not None:
                layer["cost_scale"] = r.get("cost_scale")

            li_raw = r.get("layer_index")
            li = int(li_raw) if isinstance(li_raw, int) and li_raw >= 0 else None
            if require_layer_index and li is None:
                if strict:
                    raise ValueError(f"token_index={ti}: missing layer_index for per-layer pack")
                continue
            if li is not None:
                layer["layer_index"] = int(li)
            layer_recs.append((li, idx, layer))

        if len(layer_recs) == 0:
            continue

        if any(li is not None for li, _, _ in layer_recs):
            if require_layer_index is False:
                # If some records have layer_index but others don't, fail fast in strict mode.
                if strict and any(li is None for li, _, _ in layer_recs):
                    raise ValueError(f"token_index={ti}: mixed presence of layer_index within pack group")
            layer_recs.sort(key=lambda t: (t[0] if t[0] is not None else 1 << 30, t[1]))
        else:
            layer_recs.sort(key=lambda t: t[1])

        layers: List[Dict[str, object]] = [lr for _, _, lr in layer_recs]

        union_seen = set()
        union: List[int] = []
        for layer in layers:
            lc = layer.get("candidates")
            if not isinstance(lc, list):
                continue
            for e in lc:
                if not isinstance(e, int) or int(e) < 0:
                    continue
                ei = int(e)
                if ei in union_seen:
                    continue
                union_seen.add(ei)
                union.append(ei)

        rec_out: Dict[str, object] = {"token_index": int(ti), "cls": cls, "candidates": union, "layers": layers}
        if have_t_ms:
            if policy == "min":
                rec_out["t_ms"] = float(min(t_ms_vals))
            elif policy == "max":
                rec_out["t_ms"] = float(max(t_ms_vals))
            else:
                rec_out["t_ms"] = float(t_ms_vals[0])
        else:
            if policy == "min":
                rec_out["dt_ms"] = float(min(dt_ms_vals))
            elif policy == "max":
                rec_out["dt_ms"] = float(max(dt_ms_vals))
            else:
                rec_out["dt_ms"] = float(dt_ms_vals[0])

        for k, v in (
            ("cost_scale", cost_scale),
            ("decode_ms", decode_ms),
            ("kv_tokens", kv_tokens),
            ("expert_batch_size", expert_batch_size),
            ("mtp_accept_len", mtp_accept_len),
            ("accepted_mtp", accepted_mtp),
            ("rejected_mtp", rejected_mtp),
            ("dflash_accept_len", dflash_accept_len),
            ("accepted_dflash", accepted_dflash),
            ("rejected_dflash", rejected_dflash),
        ):
            if v is not None:
                rec_out[k] = v

        out.append(rec_out)

    return(out)


def extract_jsonl_lines(
    lines: Iterable[str],
    route_type: str = "",
    non_route_policy: str = "skip",
    default_cls: str = "",
    allow_substrings: bool = True,
) -> List[Dict[str, object]]:
    if non_route_policy not in ("skip", "error"):
        raise ValueError("non_route_policy must be one of: skip, error")
    out: List[Dict[str, object]] = []
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if line == "":
            continue
        found = False
        for obj in _iter_json_values_from_line(line, bool(allow_substrings)):
            rec = extract_route_record(obj, route_type=route_type, default_cls=default_cls)
            if rec is None:
                continue
            out.append(rec)
            found = True
        if found is False and non_route_policy == "error":
            raise ValueError(f"line {lineno}: could not extract route record")
    return(out)


def infer_meta_from_extracted_routes(routes: Sequence[Dict[str, object]]) -> Dict[str, object]:
    inferred: Dict[str, object] = {}
    max_expert: Optional[int] = None
    mtp_draft_len: Optional[int] = None
    dflash_draft_len: Optional[int] = None

    for r in routes:
        cands = r.get("candidates")
        if isinstance(cands, list):
            for e in cands:
                if not isinstance(e, int) or e < 0:
                    continue
                max_expert = int(e) if max_expert is None else max(max_expert, int(e))

        accepted_mtp = r.get("accepted_mtp")
        rejected_mtp = r.get("rejected_mtp")
        if isinstance(accepted_mtp, int) and isinstance(rejected_mtp, int) and accepted_mtp >= 0 and rejected_mtp >= 0:
            dl = int(accepted_mtp + rejected_mtp)
            if dl > 0:
                if mtp_draft_len is None:
                    mtp_draft_len = dl
                elif int(mtp_draft_len) != dl:
                    mtp_draft_len = 0

        accepted_dflash = r.get("accepted_dflash")
        rejected_dflash = r.get("rejected_dflash")
        if isinstance(accepted_dflash, int) and isinstance(rejected_dflash, int) and accepted_dflash >= 0 and rejected_dflash >= 0:
            dl = int(accepted_dflash + rejected_dflash)
            if dl > 0:
                if dflash_draft_len is None:
                    dflash_draft_len = dl
                elif int(dflash_draft_len) != dl:
                    dflash_draft_len = 0

    if max_expert is not None:
        inferred["num_experts"] = int(max_expert) + 1
    if mtp_draft_len is not None and int(mtp_draft_len) > 0:
        inferred["mtp_draft_len"] = int(mtp_draft_len)
    if dflash_draft_len is not None and int(dflash_draft_len) > 0:
        inferred["dflash_draft_len"] = int(dflash_draft_len)

    return(inferred)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Extract scheduler-simulator route records from loosely shaped/mixed JSONL logs (optionally skipping non-JSON lines).")
    p.add_argument("--in-jsonl", type=str, default="-", help="Input JSONL path ('-' for stdin).")
    p.add_argument("--out-jsonl", type=str, default="-", help="Output JSONL path ('-' for stdout).")
    p.add_argument("--route-type", type=str, default="", help="Only extract records with obj.type == route-type (empty = auto).")
    p.add_argument("--non-route", type=str, default="skip", help="What to do for non-route input: skip (default; also skips non-JSON lines) or error.")
    p.add_argument("--default-cls", type=str, default="", help="Optional: when records omit cls/latency class, force all extracted records to this value (interactive or batch).")
    p.add_argument("--extract-substrings", type=int, default=1, help="When set, scan non-JSON log lines for embedded JSON objects and try extracting route records from them (default: 1).")
    p.add_argument("--pack-layers-by-token-index", type=int, default=0, help="When set, pack per-layer route records sharing token_index into a single multi-layer trace record with layers[]. Requires token_index on every record; prefers layer_index ordering when present.")
    p.add_argument("--pack-require-layer-index", type=int, default=0, help="When used with --pack-layers-by-token-index, require every record to include layer_index so layer ordering is explicit (default: 0).")
    p.add_argument("--pack-time-policy", type=str, default="strict", help="When used with --pack-layers-by-token-index, how to handle mismatched t_ms/dt_ms within a token group: strict (default), first, min, max.")
    p.add_argument("--pack-time-tol-ms", type=float, default=0.0, help="When used with --pack-layers-by-token-index, treat abs(t_ms mismatch) <= tol as equal (default: 0).")
    args = p.parse_args(argv)

    f_in = sys.stdin if args.in_jsonl == "-" else open(args.in_jsonl, "r", encoding="utf-8")
    try:
        recs = extract_jsonl_lines(
            f_in,
            route_type=args.route_type.strip(),
            non_route_policy=args.non_route.strip().lower(),
            default_cls=args.default_cls,
            allow_substrings=(int(args.extract_substrings) != 0),
        )
    finally:
        if f_in is not sys.stdin:
            f_in.close()

    meta: Dict[str, object] = {"extracted_routes": len(recs)}
    if args.route_type.strip() != "":
        meta["route_type"] = args.route_type.strip()
    inferred = infer_meta_from_extracted_routes(recs)
    if len(inferred) != 0:
        for k, v in inferred.items():
            if k not in meta:
                meta[k] = v
        meta["inferred"] = inferred

    packed: Optional[List[Dict[str, object]]] = None
    if int(args.pack_layers_by_token_index) != 0:
        packed = pack_layers_by_token_index(
            recs,
            require_layer_index=(int(args.pack_require_layer_index) != 0),
            time_policy=args.pack_time_policy,
            time_tol_ms=float(args.pack_time_tol_ms),
            strict=True,
        )
        meta["packed_layers_by_token_index"] = True
        meta["packed_routes"] = len(packed)

    f_out = sys.stdout if args.out_jsonl == "-" else open(args.out_jsonl, "w", encoding="utf-8")
    try:
        f_out.write(json.dumps({"type": "meta", "meta": meta}, separators=(",", ":")) + "\n")
        for rec in (packed if packed is not None else recs):
            f_out.write(json.dumps(rec, separators=(",", ":")) + "\n")
    finally:
        if f_out is not sys.stdout:
            f_out.close()

    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
