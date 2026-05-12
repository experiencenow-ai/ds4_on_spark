#!/usr/bin/env python3
"""Analyze DS4 ffn_moe_topk dumps as an expert-queue occupancy probe."""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
from array import array
from pathlib import Path
from typing import Iterable


DUMP_RE = re.compile(r"ffn_moe_topk-(\d+)_pos(\d+)\.i32$")


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


def summary(values: Iterable[float]) -> dict[str, float]:
    vals = list(values)
    return {
        "min": min(vals),
        "median": statistics.median(vals),
        "max": max(vals),
    }


def load_rows(path: Path, topk: int) -> list[list[int]]:
    data = array("i")
    data.frombytes(path.read_bytes())
    if len(data) % topk != 0:
        raise ValueError(f"{path} contains {len(data)} ints, not divisible by topk={topk}")
    return [list(data[i * topk : (i + 1) * topk]) for i in range(len(data) // topk)]


def layer_key(path: Path) -> tuple[int, int]:
    match = DUMP_RE.search(path.name)
    if match is None:
        raise ValueError(f"cannot parse DS4 topk dump name: {path}")
    return int(match.group(1)), int(match.group(2))


def analyze_layer(
    rows: list[list[int]],
    experts: int,
    topk: int,
    batches: list[int],
    trials: int,
    rng: random.Random,
) -> dict[str, object]:
    layer = {"tokens": len(rows), "batches": {}}
    for batch in batches:
        active_vals = []
        max_vals = []
        mean_active_vals = []
        p90_vals = []
        p99_vals = []
        tiles6_vals = []
        speed6_vals = []
        overflow6_vals = []
        for _ in range(trials):
            if batch <= len(rows):
                idxs = rng.sample(range(len(rows)), batch)
            else:
                idxs = [rng.randrange(len(rows)) for _ in range(batch)]
            counts = [0] * experts
            for idx in idxs:
                for expert in rows[idx]:
                    if 0 <= expert < experts:
                        counts[expert] += 1
            nonzero = [count for count in counts if count > 0]
            tiles6 = sum(math.ceil(count / 6) for count in nonzero)
            active = len(nonzero)
            total_pairs = batch * topk
            active_vals.append(active)
            max_vals.append(max(nonzero) if nonzero else 0)
            mean_active_vals.append(total_pairs / active if active > 0 else 0)
            p90_vals.append(percentile(nonzero, 0.90))
            p99_vals.append(percentile(nonzero, 0.99))
            tiles6_vals.append(tiles6)
            speed6_vals.append(total_pairs / tiles6 if tiles6 > 0 else 0)
            overflow6_vals.append(sum(max(0, count - 6) for count in nonzero))
        layer["batches"][str(batch)] = {
            "active": summary(active_vals),
            "max_depth": summary(max_vals),
            "mean_active_depth": summary(mean_active_vals),
            "p90_depth": summary(p90_vals),
            "p99_depth": summary(p99_vals),
            "tiles6": summary(tiles6_vals),
            "pair_speedup_cap6": summary(speed6_vals),
            "overflow_pairs_over6": summary(overflow6_vals),
        }
    return layer


def print_table(result: dict[str, object], batches: list[int]) -> None:
    print(f"layers={result['layers']} tokens_per_layer={result['tokens_per_layer']} topk={result['topk']} experts={result['experts']} trials={result['trials']}")
    print("batch active_med max_depth_med mean_active_depth_med p90_depth_med speedup_cap6_med")
    batch_summary = result["batches"]
    assert isinstance(batch_summary, dict)
    for batch in batches:
        stats = batch_summary[str(batch)]
        print(
            f"{batch} "
            f"{stats['active']['median']:.1f} "
            f"{stats['max_depth']['median']:.1f} "
            f"{stats['mean_active_depth']['median']:.2f} "
            f"{stats['p90_depth']['median']:.1f} "
            f"{stats['pair_speedup_cap6']['median']:.2f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-dir", required=True)
    parser.add_argument("--experts", type=int, default=256)
    parser.add_argument("--topk", type=int, default=6)
    parser.add_argument("--batches", default="16,32,64,100,128,256,512")
    parser.add_argument("--trials", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20260512)
    parser.add_argument("--json-out")
    args = parser.parse_args()
    batches = [int(item) for item in args.batches.split(",") if item]
    dump_dir = Path(args.dump_dir)
    files = sorted(dump_dir.glob("*ffn_moe_topk-*_pos*.i32"), key=layer_key)
    if not files:
        raise SystemExit(f"no ffn_moe_topk dumps found in {dump_dir}")
    rng = random.Random(args.seed)
    layers = []
    for path in files:
        layer, pos = layer_key(path)
        layer_result = analyze_layer(load_rows(path, args.topk), args.experts, args.topk, batches, args.trials, rng)
        layer_result["layer"] = layer
        layer_result["pos"] = pos
        layers.append(layer_result)
    result = {
        "dump_dir": str(dump_dir),
        "layers": len(layers),
        "tokens_per_layer": layers[0]["tokens"],
        "topk": args.topk,
        "experts": args.experts,
        "trials": args.trials,
        "batches": {},
    }
    for batch in batches:
        key = str(batch)
        result["batches"][key] = {}
        for metric in [
            "active",
            "max_depth",
            "mean_active_depth",
            "p90_depth",
            "p99_depth",
            "tiles6",
            "pair_speedup_cap6",
            "overflow_pairs_over6",
        ]:
            result["batches"][key][metric] = summary(
                layer["batches"][key][metric]["median"] for layer in layers
            )
    output = {"summary": result, "layers": layers}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print_table(result, batches)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
