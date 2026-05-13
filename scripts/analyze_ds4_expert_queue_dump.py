#!/usr/bin/env python3
"""Analyze DS4 ffn_moe_topk dumps as an expert-queue occupancy probe."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.scheduler import ds4_topk_dump
from sim.scheduler import expert_queue_probe


_DUMP_RE = re.compile(r"ffn_moe_topk-(\d+)_pos(\d+)\.i32$")


def _available_positions(dump_dir: Path) -> list[int]:
    positions: set[int] = set()
    for path in dump_dir.glob("*ffn_moe_topk-*_pos*.i32"):
        m = _DUMP_RE.search(path.name)
        if m is None:
            continue
        positions.add(int(m.group(2)))
    return(sorted(positions))


def _print_table(result: dict[str, object], batches: list[int]) -> None:
    print(
        f"layers={result['layers']} tokens_per_layer={result['tokens_per_layer']} "
        f"topk={result['topk']} experts={result['experts']} trials={result['trials']}"
    )
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
    parser.add_argument("--pos", type=int, default=-1, help="Dump position index to analyze (-1 = infer, requires a single pos in dump-dir).")
    parser.add_argument("--experts", type=int, default=256)
    parser.add_argument("--topk", type=int, default=6)
    parser.add_argument("--batches", default="16,32,64,100,128,256,512")
    parser.add_argument("--trials", type=int, default=250)
    parser.add_argument("--seed", type=int, default=20260512)
    parser.add_argument("--strict-expert-ids", type=int, default=1, help="If 1 (default), fail fast on out-of-range expert ids.")
    parser.add_argument("--json-out")
    args = parser.parse_args()
    batches = [int(item) for item in args.batches.split(",") if item]
    dump_dir = Path(args.dump_dir)
    if not dump_dir.exists():
        raise SystemExit(f"dump-dir does not exist: {dump_dir}")

    pos = int(args.pos)
    if pos < 0:
        positions = _available_positions(dump_dir)
        if len(positions) == 0:
            raise SystemExit(f"no ffn_moe_topk dumps found in {dump_dir}")
        if len(positions) != 1:
            raise SystemExit(f"dump-dir contains multiple pos values {positions}; pass --pos to select one")
        pos = int(positions[0])

    meta, layers = ds4_topk_dump.load_ds4_ffn_moe_topk_dump_layers(str(dump_dir), pos=int(pos), topk=int(args.topk))
    cfg = expert_queue_probe.ExpertQueueProbeConfig(
        experts=int(args.experts),
        topk=int(args.topk),
        batches=tuple(int(b) for b in batches),
        trials=int(args.trials),
        seed=int(args.seed),
        strict_expert_ids=bool(int(args.strict_expert_ids) != 0),
    )
    probe = expert_queue_probe.analyze_ds4_ffn_moe_topk_layers(layers, cfg)

    summary = {
        "dump_dir": str(dump_dir),
        "pos": int(meta.pos),
        "layers": int(probe.num_layers),
        "tokens_per_layer": int(probe.tokens_per_layer),
        "topk": int(probe.topk),
        "experts": int(probe.experts),
        "trials": int(probe.trials),
        "invalid_expert_ids": int(probe.invalid_expert_ids),
        "batches": probe.batches,
    }

    output = {"summary": summary}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(output, indent=2), encoding="utf-8")
    _print_table(summary, batches)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
