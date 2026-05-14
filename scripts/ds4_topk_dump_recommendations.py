#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.scheduler import ds4_topk_dump
from sim.scheduler import recommendations
from sim.scheduler import scheduler_sim
from sim.scheduler import topk_dump_report


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run scheduler-simulator sweeps on DS4 antirez ffn_moe_topk i32 dumps (route-only replay with synthetic timing)."
    )
    p.add_argument("--dump-dir", required=True, help="Directory containing ffn_moe_topk-<layer>_pos<pos>.i32 dumps.")
    p.add_argument("--bundle-dir", default="", help="Optional: write a bundle directory (trace.strict.jsonl + report.{json,md} + bundle_meta.json).")
    p.add_argument("--bundle-overwrite", action="store_true", help="Allow overwriting an existing --bundle-dir.")
    p.add_argument("--out-json", default="-", help="Output JSON report path ('-' for stdout).")
    p.add_argument("--format", type=str, default="json", choices=("json", "md"), help="Output format: json (default) or md.")
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
    p.add_argument("--probe-expert-queueing", action="store_true", help="Attach a route-only expert-queue probe summary (synthetic resampling).")
    p.add_argument("--probe-experts", type=int, default=256, help="Expert count for expert-queue probe (default: 256).")
    p.add_argument("--probe-batches", type=str, default="16,32,64,100,128,256,512", help="Comma-separated batch sizes for expert-queue probe.")
    p.add_argument("--probe-trials", type=int, default=250, help="Trials per layer per batch size for expert-queue probe.")
    p.add_argument("--probe-expert-transitions", action="store_true", help="Attach adjacent-layer P(next expert | current expert) and same-spark affinity stats.")
    p.add_argument("--probe-transition-sparks", type=int, default=8, help="Spark count for transition-affinity probe (default: 8).")
    p.add_argument("--probe-transition-logical-lanes", type=int, default=32, help="Logical expert lanes for transition-affinity probe (default: 32).")
    p.add_argument("--probe-transition-top-masses", type=str, default="1,4,8,16,32", help="Comma-separated top-N masses for conditional next-expert stats.")
    p.add_argument("--probe-transition-top-next", type=int, default=8, help="Number of current-expert rows / next-expert entries to retain.")
    args = p.parse_args()

    transition_top_masses = tuple(int(x) for x in str(args.probe_transition_top_masses).split(",") if str(x).strip() != "")
    if str(args.bundle_dir).strip() != "":
        batches = tuple(int(x) for x in str(args.probe_batches).split(",") if str(x).strip() != "")
        out = topk_dump_report.build_ds4_topk_dump_trace_report_bundle(
            str(args.dump_dir),
            out_dir=str(args.bundle_dir),
            pos=int(args.pos),
            topk=int(args.topk),
            num_tokens=int(args.num_tokens),
            seed=int(args.seed),
            sample_mode=str(args.sample_mode),
            time_mode=str(args.time_mode),
            arrival_rate_tps=float(args.arrival_rate_tps),
            batch_size=int(args.batch_size),
            interactive_prob=float(args.interactive_prob),
            trace_speedup=float(args.trace_speedup),
            expert_queue_max=int(args.expert_queue_max),
            expert_parallelism=int(args.expert_parallelism),
            service_ms=float(args.service_ms),
            starvation_ms=float(args.starvation_ms),
            mtp_draft_len=int(args.mtp_draft_len),
            mtp_accept_prob=float(args.mtp_accept_prob),
            mtp_accept_decay=float(args.mtp_accept_decay),
            mtp_draft_cost_scale=float(args.mtp_draft_cost_scale),
            probe_expert_queueing=bool(args.probe_expert_queueing),
            probe_experts=int(args.probe_experts),
            probe_batches=batches,
            probe_trials=int(args.probe_trials),
            probe_expert_transitions=bool(args.probe_expert_transitions),
            probe_transition_sparks=int(args.probe_transition_sparks),
            probe_transition_logical_lanes=int(args.probe_transition_logical_lanes),
            probe_transition_top_masses=transition_top_masses,
            probe_transition_top_next=int(args.probe_transition_top_next),
            overwrite=bool(args.bundle_overwrite),
        )
        print(
            json.dumps(
                {
                    "out_dir": out.get("out_dir"),
                    "trace_path": out.get("trace_path"),
                    "report_json_path": out.get("report_json_path"),
                    "report_md_path": out.get("report_md_path"),
                    "bundle_meta_path": out.get("bundle_meta_path"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    meta, layers = ds4_topk_dump.load_ds4_ffn_moe_topk_dump_layers(
        str(args.dump_dir),
        pos=int(args.pos),
        topk=int(args.topk),
    )

    trace_meta: dict[str, object] = {}
    topk_dump_probe: dict[str, object] = {}
    topk_transition_probe: dict[str, object] = {}
    if bool(args.probe_expert_queueing):
        batches = tuple(int(x) for x in str(args.probe_batches).split(",") if str(x).strip() != "")
        topk_dump_probe = ds4_topk_dump.probe_expert_queueing_from_ds4_topk_dump_layers(
            layers,
            experts=int(args.probe_experts),
            topk=int(args.topk),
            batches=batches,
            trials=int(args.probe_trials),
            seed=int(args.seed),
            strict_expert_ids=True,
        )
    if bool(args.probe_expert_transitions):
        topk_transition_probe = ds4_topk_dump.probe_expert_transitions_from_ds4_topk_dump_layers(
            layers,
            experts=int(args.probe_experts),
            topk=int(args.topk),
            logical_lanes=int(args.probe_transition_logical_lanes),
            sparks=int(args.probe_transition_sparks),
            top_masses=transition_top_masses,
            top_next=int(args.probe_transition_top_next),
            strict_expert_ids=True,
            compact=True,
        )

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
    if len(topk_dump_probe) != 0:
        report["topk_dump_probe"] = {
            "present": True,
            "note": "Probe uses real routes from the topk dumps but resamples rows and assumes synthetic batch sizes; this is not a full decode replay.",
            "summary": topk_dump_probe,
        }
    if len(topk_transition_probe) != 0:
        report["topk_transition_probe"] = {
            "present": True,
            "note": "Probe measures adjacent-layer P(next expert | current expert) and compares expert_id % logical_lanes routing against a balanced layer-specific affinity table.",
            "summary": topk_transition_probe,
        }

    fmt = str(args.format).strip().lower()
    if fmt == "md":
        out_json = recommendations.format_runtime_trace_ablation_markdown(report)
    else:
        out_json = json.dumps(report, indent=2, sort_keys=True)
    if str(args.out_json) == "-":
        print(out_json)
        return 0
    with open(str(args.out_json), "w", encoding="utf-8") as f:
        f.write(out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
