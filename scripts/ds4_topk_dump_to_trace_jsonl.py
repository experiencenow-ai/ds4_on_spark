#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.scheduler import ds4_topk_dump


def main() -> int:
    p = argparse.ArgumentParser(description="Convert DS4 antirez ffn_moe_topk i32 dumps into a scheduler-simulator JSONL trace (multi-layer routes).")
    p.add_argument("--dump-dir", required=True, help="Directory containing ffn_moe_topk-<layer>_pos<pos>.i32 dumps.")
    p.add_argument("--out-jsonl", default="-", help="Output JSONL path ('-' for stdout).")
    p.add_argument("--pos", type=int, default=0, help="Dump position index to extract (default: 0).")
    p.add_argument("--topk", type=int, default=6, help="Experts per row in each dump (default: 6).")
    p.add_argument("--num-tokens", type=int, default=0, help="Number of output trace records (0 = tokens_per_layer).")
    p.add_argument("--seed", type=int, default=1, help="RNG seed used for sampling and cls assignment.")
    p.add_argument("--sample-mode", type=str, default="sequential", choices=("sequential", "sample", "resample"), help="sequential: first N rows; sample: sample N unique rows; resample: sample N rows with replacement.")
    p.add_argument("--time-mode", type=str, default="dt_ms", choices=("t_ms", "dt_ms"), help="Time mode: dt_ms (default) or t_ms.")
    p.add_argument("--arrival-rate-tps", type=float, default=1000.0, help="Synthetic arrival rate (tokens/sec) used to emit dt_ms/t_ms.")
    p.add_argument("--batch-size", type=int, default=1, help="Group tokens into batches that arrive at the same time (default: 1).")
    p.add_argument("--interactive-prob", type=float, default=0.0, help="Probability to mark a token as interactive (default: 0.0).")
    args = p.parse_args()

    meta, layers = ds4_topk_dump.load_ds4_ffn_moe_topk_dump_layers(
        args.dump_dir,
        pos=int(args.pos),
        topk=int(args.topk),
    )
    ds4_topk_dump.build_scheduler_trace_jsonl_from_ds4_topk_dump(
        meta,
        layers,
        out_path=str(args.out_jsonl),
        num_tokens=int(args.num_tokens),
        seed=int(args.seed),
        sample_mode=str(args.sample_mode),
        time_mode=str(args.time_mode),
        arrival_rate_tps=float(args.arrival_rate_tps),
        batch_size=int(args.batch_size),
        interactive_prob=float(args.interactive_prob),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
