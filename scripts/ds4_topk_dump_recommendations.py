#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile

from sim.scheduler import ds4_topk_dump
from sim.scheduler import recommendations
from sim.scheduler import scheduler_sim


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run scheduler-simulator sweeps on DS4 antirez ffn_moe_topk i32 dumps (route-only replay with synthetic timing)."
    )
    p.add_argument("--dump-dir", required=True, help="Directory containing ffn_moe_topk-<layer>_pos<pos>.i32 dumps.")
    p.add_argument("--out-json", default="-", help="Output JSON report path ('-' for stdout).")
    p.add_argument("--pos", type=int, default=0, help="Dump position index to extract (default: 0).")
    p.add_argument("--topk", type=int, default=6, help="Experts per row in each dump (default: 6).")
    p.add_argument("--num-tokens", type=int, default=0, help="Number of output trace records (0 = tokens_per_layer).")
    p.add_argument("--seed", type=int, default=1, help="RNG seed used for sampling and cls assignment.")
    p.add_argument(
        "--sample-mode",
        type=str,
        default="sequential",
        choices=("sequential", "sample", "resample"),
        help="sequential: first N rows; sample: sample N unique rows; resample: sample N rows with replacement.",
    )
    p.add_argument("--time-mode", type=str, default="dt_ms", choices=("t_ms", "dt_ms"), help="Time mode: dt_ms (default) or t_ms.")
    p.add_argument("--arrival-rate-tps", type=float, default=1000.0, help="Synthetic arrival rate (tokens/sec) used to emit dt_ms/t_ms.")
    p.add_argument("--batch-size", type=int, default=1, help="Group tokens into batches that arrive at the same time (default: 1).")
    p.add_argument("--interactive-prob", type=float, default=0.0, help="Probability to mark a token as interactive (default: 0.0).")
    p.add_argument("--trace-speedup", type=float, default=1.0, help="Scale synthetic arrivals by dividing t_ms by this factor (>0).")
    p.add_argument("--expert-queue-max", type=int, default=128, help="Per-expert queue capacity for the sweeps.")
    p.add_argument("--expert-parallelism", type=int, default=1, help="Per-expert service parallelism for the sweeps.")
    p.add_argument("--service-ms", type=float, default=1.0, help="Per-task service time in ms (simulated).")
    p.add_argument("--starvation-ms", type=float, default=50.0, help="Starvation threshold in ms (simulated).")
    p.add_argument("--mtp-draft-len", type=int, default=-1, help="Optional: enable synthetic MTP ablation with this draft length (>0).")
    p.add_argument("--mtp-accept-prob", type=float, default=0.0, help="Synthetic MTP: initial accept probability at position 0.")
    p.add_argument("--mtp-accept-decay", type=float, default=1.0, help="Synthetic MTP: accept prob decay per position.")
    p.add_argument("--mtp-draft-cost-scale", type=float, default=0.25, help="Synthetic MTP: draft compute cost vs verify.")
    p.add_argument("--trace-jsonl-out", default="", help="Optional: also write the intermediate scheduler-trace JSONL to this path.")
    args = p.parse_args()

    meta, layers = ds4_topk_dump.load_ds4_ffn_moe_topk_dump_layers(
        str(args.dump_dir),
        pos=int(args.pos),
        topk=int(args.topk),
    )

    trace_meta: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as td:
        tmp_trace = os.path.join(td, "routes.jsonl")
        trace_path = str(args.trace_jsonl_out) if str(args.trace_jsonl_out).strip() != "" else tmp_trace
        ds4_topk_dump.build_scheduler_trace_jsonl_from_ds4_topk_dump(
            meta,
            layers,
            out_path=str(trace_path),
            num_tokens=int(args.num_tokens),
            seed=int(args.seed),
            sample_mode=str(args.sample_mode),
            time_mode=str(args.time_mode),
            arrival_rate_tps=float(args.arrival_rate_tps),
            batch_size=int(args.batch_size),
            interactive_prob=float(args.interactive_prob),
        )

        trace = scheduler_sim.load_trace_jsonl(
            str(trace_path),
            time_mode=str(args.time_mode),
            meta_out=trace_meta,
            non_route_policy="error",
            input_format="strict",
        )

    report = recommendations.run_runtime_trace_mtp_ablation(
        name="ds4_topk_dump_route_only_ablation",
        trace=trace,
        trace_meta=trace_meta,
        expert_queue_max=int(args.expert_queue_max),
        expert_parallelism=int(args.expert_parallelism),
        service_ms=float(args.service_ms),
        starvation_ms=float(args.starvation_ms),
        trace_speedup=float(args.trace_speedup),
        mtp_draft_len=int(args.mtp_draft_len),
        mtp_accept_prob=float(args.mtp_accept_prob),
        mtp_accept_decay=float(args.mtp_accept_decay),
        mtp_draft_cost_scale=float(args.mtp_draft_cost_scale),
    )

    out_json = json.dumps(report, indent=2, sort_keys=True)
    if str(args.out_json) == "-":
        print(out_json)
        return 0
    with open(str(args.out_json), "w", encoding="utf-8") as f:
        f.write(out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

