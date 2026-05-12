#!/usr/bin/env python3
"""Offline deterministic Elo updater over compact DSv4 judge records."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from scripts import judge_elo_schema as schema
except ModuleNotFoundError:
    # Allow running as a script from repo root.
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from scripts import judge_elo_schema as schema


@dataclass
class EloRow:
    model: str
    elo: float
    games: int
    wins: int
    losses: int
    ties: int
    quality_score: float
    quality_source: str


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _pctl(sorted_vals: List[int], q: float) -> int:
    if len(sorted_vals) == 0:
        return 0
    if q <= 0.0:
        return int(sorted_vals[0])
    if q >= 1.0:
        return int(sorted_vals[-1])
    i = int(math.floor(q * float(len(sorted_vals) - 1)))
    if i < 0:
        i = 0
    if i >= len(sorted_vals):
        i = len(sorted_vals) - 1
    return int(sorted_vals[i])


def _int_stats(vals: List[int]) -> Dict[str, float]:
    if len(vals) == 0:
        return {"count": 0.0}
    s = sorted(int(v) for v in vals)
    total = float(sum(s))
    return {
        "count": float(len(s)),
        "min": float(s[0]),
        "p50": float(_pctl(s, 0.50)),
        "p90": float(_pctl(s, 0.90)),
        "max": float(s[-1]),
        "mean": (total / float(len(s))),
    }


def _expected(ra: float, rb: float, scale: float) -> float:
    return 1.0 / (1.0 + (10.0 ** ((rb - ra) / scale)))


def _k_eff(k: float, margin: int) -> float:
    # Margin 0 is a near-tie: downweight updates. Margin 3 is decisive: full K.
    # Weight in {0.25, 0.50, 0.75, 1.00}.
    w = (float(margin) + 1.0) / 4.0
    return k * w


def _outcome(winner: str) -> float:
    if winner == "A":
        return 1.0
    if winner == "B":
        return 0.0
    return 0.5


def _quality_minmax(elos: Dict[str, float], min_quality: float = 0.0, max_quality: float = 100.0) -> Dict[str, float]:
    if len(elos) == 0:
        return {}
    lo = min(elos.values())
    hi = max(elos.values())
    if hi <= lo:
        return {m: 50.0 for m in elos}
    out: Dict[str, float] = {}
    for m, r in elos.items():
        frac = (r - lo) / (hi - lo)
        out[m] = (min_quality + ((max_quality - min_quality) * frac))
    return out


def _quality_logistic(elos: Dict[str, float], base_elo: float, scale: float) -> Dict[str, float]:
    if len(elos) == 0:
        return {}
    out: Dict[str, float] = {}
    for m, r in elos.items():
        rr = float(r)
        p = 1.0 / (1.0 + (10.0 ** ((base_elo - rr) / scale)))
        out[m] = (100.0 * p)
    return out


def _apply_match(ratings: Dict[str, float], a: str, b: str, winner: str, margin: int, k: float, scale: float) -> float:
    ra = ratings.get(a, 1000.0)
    rb = ratings.get(b, 1000.0)
    ea = _expected(ra, rb, scale)
    sa = _outcome(winner)
    delta = _k_eff(k, margin) * (sa - ea)
    ratings[a] = ra + delta
    ratings[b] = rb - delta
    return delta


def iter_valid_matches(paths: Sequence[str], sort_by_pair_id: bool) -> Iterable[Tuple[str, str, str, int]]:
    rows: List[Tuple[str, str, str, str, int]] = []
    for path in paths:
        for _, obj in schema.iter_jsonl(path):
            if not obj.get("parse_valid", False):
                continue
            errs = schema.validate_record(obj)
            if len(errs) != 0:
                continue
            rows.append((str(obj["pair_id"]), str(obj["model_a"]), str(obj["model_b"]), str(obj["winner"]), int(obj["margin"])))
    if sort_by_pair_id:
        # When multiple inputs are merged, a stable ordering avoids nondeterminism.
        # pair_id is required by the schema and should be stable across runs.
        # Sort only by pair_id; Python's sort is stable, so ties preserve input order.
        rows.sort(key=lambda t: t[0])
    for r in rows:
        yield (r[1], r[2], r[3], r[4])


def compute_elo(paths: Sequence[str], k: float, scale: float, sort_by_pair_id: bool) -> Tuple[Dict[str, float], Dict[str, Dict[str, int]]]:
    ratings: Dict[str, float] = {}
    stats: Dict[str, Dict[str, int]] = {}
    for a, b, winner, margin in iter_valid_matches(paths, sort_by_pair_id):
        _apply_match(ratings, a, b, winner, margin, k, scale)
        for m in (a, b):
            if m not in stats:
                stats[m] = {"games": 0, "wins": 0, "losses": 0, "ties": 0}
        stats[a]["games"] += 1
        stats[b]["games"] += 1
        if winner == "A":
            stats[a]["wins"] += 1
            stats[b]["losses"] += 1
        elif winner == "B":
            stats[b]["wins"] += 1
            stats[a]["losses"] += 1
        else:
            stats[a]["ties"] += 1
            stats[b]["ties"] += 1
    return ratings, stats


def compute_meta(paths: Sequence[str], k: float, scale: float, sort_by_pair_id: bool) -> Dict[str, Any]:
    total = 0
    parse_ok = 0
    parse_bad = 0
    used = 0
    skipped_invalid_schema = 0
    models: Dict[str, int] = {}
    for path in paths:
        for _, obj in schema.iter_jsonl(path):
            total += 1
            if bool(obj.get("parse_valid", False)):
                parse_ok += 1
                errs = schema.validate_record(obj)
                if len(errs) == 0:
                    used += 1
                    ma = str(obj.get("model_a", ""))
                    mb = str(obj.get("model_b", ""))
                    if ma != "":
                        models[ma] = models.get(ma, 0) + 1
                    if mb != "":
                        models[mb] = models.get(mb, 0) + 1
                else:
                    skipped_invalid_schema += 1
            else:
                parse_bad += 1
    return {
        "schema": "ds4_judge_elo_meta_v1",
        "inputs": [str(p) for p in paths],
        "k": float(k),
        "scale": float(scale),
        "sort_by_pair_id": bool(sort_by_pair_id),
        "records": int(total),
        "parse_valid_true": int(parse_ok),
        "parse_valid_false": int(parse_bad),
        "matches_used": int(used),
        "matches_skipped_invalid_schema": int(skipped_invalid_schema),
        "unique_models": int(len(models)),
    }


def compute_budget(paths: Sequence[str], judge_out_target: int = 64) -> Dict[str, Any]:
    total = 0
    parse_ok = 0
    parse_bad = 0
    tokens: Dict[str, List[int]] = {"a_out": [], "b_out": [], "judge_in": [], "judge_out": []}
    latency: Dict[str, List[int]] = {"a": [], "b": [], "judge": []}
    tokens_missing: Dict[str, int] = {k: 0 for k in tokens}
    latency_missing: Dict[str, int] = {k: 0 for k in latency}
    parse_ok_with_judge_out = 0
    parse_ok_judge_out_le_target = 0
    for path in paths:
        for _, obj in schema.iter_jsonl(path):
            total += 1
            parse_valid = bool(obj.get("parse_valid", False))
            if parse_valid:
                parse_ok += 1
            else:
                parse_bad += 1

            t = obj.get("tokens")
            for k in tokens:
                v = None
                if isinstance(t, dict):
                    v = t.get(k)
                if isinstance(v, int) and not isinstance(v, bool) and int(v) >= 0:
                    tokens[k].append(int(v))
                    if parse_valid and k == "judge_out":
                        parse_ok_with_judge_out += 1
                        if int(v) <= judge_out_target:
                            parse_ok_judge_out_le_target += 1
                else:
                    tokens_missing[k] += 1

            l = obj.get("latency_ms")
            for k in latency:
                v = None
                if isinstance(l, dict):
                    v = l.get(k)
                if isinstance(v, int) and not isinstance(v, bool) and int(v) >= 0:
                    latency[k].append(int(v))
                else:
                    latency_missing[k] += 1

    judge_out_vals = tokens.get("judge_out", [])
    judge_out_le_target = 0
    for v in judge_out_vals:
        if int(v) <= judge_out_target:
            judge_out_le_target += 1

    tokens_out: Dict[str, Any] = {}
    for k, vals in tokens.items():
        st = _int_stats(vals)
        st["missing"] = float(tokens_missing.get(k, 0))
        st["present_fraction"] = (float(len(vals)) / float(total)) if total != 0 else 0.0
        tokens_out[k] = st

    latency_out: Dict[str, Any] = {}
    for k, vals in latency.items():
        st = _int_stats(vals)
        st["missing"] = float(latency_missing.get(k, 0))
        st["present_fraction"] = (float(len(vals)) / float(total)) if total != 0 else 0.0
        latency_out[k] = st

    out: Dict[str, Any] = {
        "schema": "ds4_judge_elo_budget_v1",
        "records": int(total),
        "parse_valid_true": int(parse_ok),
        "parse_valid_false": int(parse_bad),
        "tokens": tokens_out,
        "latency_ms": latency_out,
        "judge_out_budget": {
            "target_tokens": int(judge_out_target),
            "count_with_tokens": int(len(judge_out_vals)),
            "count_le_target": int(judge_out_le_target),
            "fraction_le_target": (float(judge_out_le_target) / float(len(judge_out_vals))) if len(judge_out_vals) != 0 else 0.0,
            "count_with_tokens_parse_valid_true": int(parse_ok_with_judge_out),
            "count_le_target_parse_valid_true": int(parse_ok_judge_out_le_target),
            "fraction_le_target_parse_valid_true": (float(parse_ok_judge_out_le_target) / float(parse_ok_with_judge_out)) if parse_ok_with_judge_out != 0 else 0.0,
        },
    }
    return out


def write_outputs(out_dir: str, rows: Sequence[EloRow]) -> None:
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "leaderboard.json"), "w", encoding="utf-8") as f:
        json.dump([r.__dict__ for r in rows], f, indent=2, sort_keys=True)
        f.write("\n")

    with open(os.path.join(out_dir, "leaderboard.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["model", "elo", "games", "wins", "losses", "ties", "quality_score", "quality_source"])
        w.writeheader()
        for r in rows:
            w.writerow({
                "model": r.model,
                "elo": f"{r.elo:.3f}",
                "games": r.games,
                "wins": r.wins,
                "losses": r.losses,
                "ties": r.ties,
                "quality_score": f"{r.quality_score:.3f}",
                "quality_source": r.quality_source,
            })

    with open(os.path.join(out_dir, "leaderboard.md"), "w", encoding="utf-8") as f:
        f.write("| model | elo | games | W | L | T | quality_score | source |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
        for r in rows:
            f.write(f"| {r.model} | {r.elo:.1f} | {r.games} | {r.wins} | {r.losses} | {r.ties} | {r.quality_score:.1f} | {r.quality_source} |\n")

    with open(os.path.join(out_dir, "quality_map.json"), "w", encoding="utf-8") as f:
        q = {r.model: float(r.quality_score) for r in rows}
        json.dump(q, f, indent=2, sort_keys=True)
        f.write("\n")


def validate_inputs_strict(paths: Sequence[str]) -> None:
    bad = 0
    for path in paths:
        for lineno, obj in schema.iter_jsonl(path):
            errs = schema.validate_record_strict(obj)
            if len(errs) == 0:
                continue
            bad += 1
            for e in errs:
                _print_err(f"{path}:{lineno}: {e}")
    if bad != 0:
        _print_err(f"invalid_records={bad}")
        raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True, help="input JSONL path (repeatable)")
    ap.add_argument("--out-dir", required=True, help="output directory")
    ap.add_argument("--k", type=float, default=32.0, help="base K factor")
    ap.add_argument("--scale", type=float, default=400.0, help="Elo scale (default 400)")
    ap.add_argument("--sort", action="store_true", help="sort matches (stable but loses chronological meaning)")
    ap.add_argument("--strict", action="store_true", help="require tokens/latency accounting and strict schema constraints")
    ap.add_argument("--quality-mode", choices=["logistic", "minmax"], default="logistic", help="map Elo -> quality_score (default logistic)")
    ap.add_argument("--judge-out-target", type=int, default=64, help="target tokens for compact judge output budgeting")
    args = ap.parse_args()

    if not schema._finite(float(args.k)) or args.k <= 0.0:
        raise SystemExit("K must be finite and > 0")
    if not schema._finite(float(args.scale)) or args.scale <= 0.0:
        raise SystemExit("scale must be finite and > 0")
    if not isinstance(args.judge_out_target, int) or int(args.judge_out_target) <= 0:
        raise SystemExit("--judge-out-target must be an integer > 0")

    if args.strict:
        validate_inputs_strict(args.inputs)

    ratings, stats = compute_elo(args.inputs, float(args.k), float(args.scale), bool(args.sort))
    if args.quality_mode == "minmax":
        q = _quality_minmax(ratings)
        qsrc = "judge_elo_minmax_v1"
    else:
        q = _quality_logistic(ratings, base_elo=1000.0, scale=float(args.scale))
        qsrc = "judge_elo_logistic_v1"
    rows: List[EloRow] = []
    for model, elo in ratings.items():
        st = stats.get(model, {"games": 0, "wins": 0, "losses": 0, "ties": 0})
        rows.append(EloRow(
            model=model,
            elo=float(elo),
            games=int(st["games"]),
            wins=int(st["wins"]),
            losses=int(st["losses"]),
            ties=int(st["ties"]),
            quality_score=float(q.get(model, 50.0)),
            quality_source=str(qsrc),
        ))
    rows.sort(key=lambda r: (r.elo, r.games, r.model), reverse=True)
    write_outputs(args.out_dir, rows)
    with open(os.path.join(args.out_dir, "meta.json"), "w", encoding="utf-8") as f:
        meta = compute_meta(args.inputs, float(args.k), float(args.scale), bool(args.sort))
        meta["strict"] = bool(args.strict)
        meta["quality_mode"] = str(args.quality_mode)
        meta["quality_source"] = str(qsrc)
        meta["judge_out_target_tokens"] = int(args.judge_out_target)
        json.dump(meta, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(args.out_dir, "budget.json"), "w", encoding="utf-8") as f:
        json.dump(compute_budget(args.inputs, judge_out_target=int(args.judge_out_target)), f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
