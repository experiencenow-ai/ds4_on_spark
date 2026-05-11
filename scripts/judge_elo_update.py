#!/usr/bin/env python3
"""Offline deterministic Elo updater over compact DSv4 judge records."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True, help="input JSONL path (repeatable)")
    ap.add_argument("--out-dir", required=True, help="output directory")
    ap.add_argument("--k", type=float, default=32.0, help="base K factor")
    ap.add_argument("--scale", type=float, default=400.0, help="Elo scale (default 400)")
    ap.add_argument("--sort", action="store_true", help="sort matches (stable but loses chronological meaning)")
    args = ap.parse_args()

    if not schema._finite(float(args.k)) or args.k <= 0.0:
        raise SystemExit("K must be finite and > 0")
    if not schema._finite(float(args.scale)) or args.scale <= 0.0:
        raise SystemExit("scale must be finite and > 0")

    ratings, stats = compute_elo(args.inputs, float(args.k), float(args.scale), bool(args.sort))
    q = _quality_minmax(ratings)
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
            quality_source="judge_elo_minmax_v1",
        ))
    rows.sort(key=lambda r: (r.elo, r.games, r.model), reverse=True)
    write_outputs(args.out_dir, rows)


if __name__ == "__main__":
    main()
