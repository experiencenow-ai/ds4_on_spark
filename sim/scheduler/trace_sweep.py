#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sim.scheduler import scheduler_sim  # noqa: E402


def _reserve_default(expert_queue_max: int) -> int:
    if expert_queue_max <= 0:
        return(0)
    return(min(16, int(expert_queue_max)))


def _maybe_slice_trace(trace: Sequence[scheduler_sim.TokenRoute], max_tokens: int) -> List[scheduler_sim.TokenRoute]:
    if max_tokens <= 0:
        return(list(trace))
    return(list(trace[: int(max_tokens)]))


def run_trace_sweeps(
    trace: Sequence[scheduler_sim.TokenRoute],
    base_cfg: scheduler_sim.SimConfig,
    *,
    trace_meta: Optional[Dict[str, object]] = None,
    max_tokens: int = 0,
) -> Dict[str, Any]:
    trace_in = _maybe_slice_trace(trace, int(max_tokens))
    scenarios: Dict[str, Any] = {}

    base_batch_max = int(base_cfg.batch_max_batch)
    batch_variants: List[Tuple[str, Dict[str, object]]] = []
    for b in (1, 4, 8):
        if int(b) == base_batch_max:
            continue
        batch_variants.append((f"batch_max_batch_{int(b)}", {"batch_max_batch": int(b)}))
    if len(batch_variants) != 0:
        scenarios["expert_batching_sweep"] = {
            "name": "expert_batching_sweep",
            "base_cfg": dataclasses.asdict(base_cfg),
            "variants": batch_variants,
            "results": scheduler_sim.compare_simulation_summaries(base_cfg, trace_in, batch_variants),
        }

    base_queue_max = int(base_cfg.expert_queue_max)
    queue_variants: List[Tuple[str, Dict[str, object]]] = []
    if base_queue_max > 0:
        for qmax in (max(1, (base_queue_max // 2)), (base_queue_max * 2)):
            if int(qmax) == base_queue_max:
                continue
            queue_variants.append((f"queue_max_{int(qmax)}", {"expert_queue_max": int(qmax)}))
    if len(queue_variants) != 0:
        scenarios["expert_queue_max_sweep"] = {
            "name": "expert_queue_max_sweep",
            "base_cfg": dataclasses.asdict(base_cfg),
            "variants": queue_variants,
            "results": scheduler_sim.compare_simulation_summaries(base_cfg, trace_in, queue_variants),
        }

    reserve_n = _reserve_default(int(base_cfg.expert_queue_max))
    if reserve_n > 0:
        variants_reserve: List[Tuple[str, Dict[str, object]]] = [
            ("reserve_0", {"expert_queue_reserve_interactive": 0}),
            (f"reserve_{reserve_n}", {"expert_queue_reserve_interactive": int(reserve_n)}),
        ]
        scenarios["expert_queue_reserve_sweep"] = {
            "name": "expert_queue_reserve_sweep",
            "base_cfg": dataclasses.asdict(base_cfg),
            "variants": variants_reserve,
            "results": scheduler_sim.compare_simulation_summaries(base_cfg, trace_in, variants_reserve),
        }

    variants_k_signal: List[Tuple[str, Dict[str, object]]] = [
        ("k_signal_global", {"k_signal": "global"}),
        ("k_signal_candidates", {"k_signal": "candidates"}),
        ("k_signal_class", {"k_signal": "class"}),
    ]
    scenarios["k_signal_policy"] = {
        "name": "k_signal_policy",
        "base_cfg": dataclasses.asdict(base_cfg),
        "variants": variants_k_signal,
        "results": scheduler_sim.compare_simulation_summaries(base_cfg, trace_in, variants_k_signal),
    }

    variants_starvation: List[Tuple[str, Dict[str, object]]] = [
        ("strict_priority", {"hi_burst": 0, "promote_ms": 0.0}),
        ("hi_burst_16", {"hi_burst": 16, "promote_ms": 0.0}),
        ("promote_50ms", {"hi_burst": 0, "promote_ms": 50.0}),
        ("hybrid_16_50ms", {"hi_burst": 16, "promote_ms": 50.0}),
    ]
    scenarios["starvation_knobs"] = {
        "name": "starvation_knobs",
        "base_cfg": dataclasses.asdict(base_cfg),
        "variants": variants_starvation,
        "results": scheduler_sim.compare_simulation_summaries(base_cfg, trace_in, variants_starvation),
    }

    if int(base_cfg.mtp_draft_len) > 0:
        variants_mtp: List[Tuple[str, Dict[str, object]]] = [
            ("mtp_full", {"mtp_draft_attempt_policy": "full"}),
            ("mtp_stop_at_reject", {"mtp_draft_attempt_policy": "stop_at_reject"}),
        ]
        scenarios["mtp_attempt_policy"] = {
            "name": "mtp_attempt_policy",
            "base_cfg": dataclasses.asdict(base_cfg),
            "variants": variants_mtp,
            "results": scheduler_sim.compare_simulation_summaries(base_cfg, trace_in, variants_mtp),
        }

    out: Dict[str, Any] = {
        "trace_summary": scheduler_sim.trace_summary_jsonable(trace_in, mtp_draft_len=int(base_cfg.mtp_draft_len), meta=trace_meta),
        "base_cfg": dataclasses.asdict(base_cfg),
        "scenarios": scenarios,
    }
    if trace_meta is not None and len(trace_meta) != 0:
        out["trace_meta"] = trace_meta
    if max_tokens > 0:
        out["max_tokens"] = int(max_tokens)
    return(out)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run trace-backed scheduler simulator sweeps against a JSONL trace.")
    p.add_argument("--trace-jsonl", type=str, required=True, help="Input JSONL trace path ('-' for stdin).")
    p.add_argument("--trace-time-mode", type=str, default="t_ms", choices=("t_ms", "dt_ms"))
    p.add_argument("--trace-input-format", type=str, default="runtime", choices=("strict", "runtime"))
    p.add_argument("--trace-non-route", type=str, default="skip", choices=("skip", "error"))
    p.add_argument("--trace-route-type", type=str, default="", help="Runtime-format trace: only accept records with obj.type == this value (empty = accept all).")
    p.add_argument("--trace-meta-json", type=str, default="", help="Optional JSON file merged into trace_meta.")
    p.add_argument("--trace-derive-cost-scale", type=str, default="none", choices=("none", "kv_tokens_p50", "decode_ms_p50"))
    p.add_argument("--trace-speedup", type=float, default=1.0, help="Scale trace time by 1/speedup (>= 1 makes arrivals faster).")
    p.add_argument("--max-tokens", type=int, default=0, help="If > 0, slice the trace to the first N entries before sweeping.")

    p.add_argument("--num-experts", type=int, default=0, help="0 = infer from trace/meta.")
    p.add_argument("--expert-parallelism", type=int, default=1)
    p.add_argument("--expert-queue-max", type=int, default=128)
    p.add_argument("--expert-queue-reserve-interactive", type=int, default=0, help="Baseline reserve (scenario sweep still includes reserve_0 and reserve_16 by default).")
    p.add_argument("--service-ms", type=float, default=1.0)
    p.add_argument("--starvation-ms", type=float, default=100.0)
    p.add_argument("--hi-burst", type=int, default=0)
    p.add_argument("--promote-ms", type=float, default=0.0)
    p.add_argument("--k-mode", type=str, default="controller", choices=("controller", "trace"))
    p.add_argument("--k-signal", type=str, default="global", choices=("global", "candidates", "class"))
    p.add_argument("--pending-units", type=str, default="tasks", choices=("tasks", "work"))
    p.add_argument("--k-scope", type=str, default="token", choices=("token", "layer"))
    p.add_argument("--admit-policy", type=str, default="ordered", choices=("ordered", "least_pending", "score_desc"))
    p.add_argument("--sla-interactive-ms", type=float, default=0.0)
    p.add_argument("--sla-batch-ms", type=float, default=0.0)
    p.add_argument("--sim-seed", type=int, default=1)

    p.add_argument("--mtp-draft-len", type=int, default=0)
    p.add_argument("--mtp-accept-prob", type=float, default=0.0)
    p.add_argument("--mtp-accept-decay", type=float, default=1.0)
    p.add_argument("--mtp-draft-cost-scale", type=float, default=0.25)
    p.add_argument("--mtp-verify-per-draft-cost-scale", type=float, default=0.0)
    p.add_argument("--mtp-draft-attempt-policy", type=str, default="full", choices=("full", "stop_at_reject"))

    p.add_argument("--batch-max-interactive", type=int, default=1)
    p.add_argument("--batch-max-batch", type=int, default=1)
    p.add_argument("--batch-wait-interactive-ms", type=float, default=0.0)
    p.add_argument("--batch-wait-batch-ms", type=float, default=0.0)
    p.add_argument("--service-base-ms", type=float, default=0.0)
    p.add_argument("--service-per-task-ms", type=float, default=-1.0)

    p.add_argument("--k-min-interactive", type=int, default=1)
    p.add_argument("--k-max-interactive", type=int, default=4)
    p.add_argument("--k-min-batch", type=int, default=1)
    p.add_argument("--k-max-batch", type=int, default=2)
    p.add_argument("--q-low", type=int, default=8)
    p.add_argument("--q-high", type=int, default=96)
    p.add_argument("--ema-alpha", type=float, default=1.0)
    p.add_argument("--update-ms", type=float, default=0.0)
    p.add_argument("--k-slew", type=int, default=0)
    return(p.parse_args(argv))


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    trace_meta: Dict[str, object] = {}
    if args.trace_meta_json.strip() != "":
        with open(args.trace_meta_json, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            raise SystemExit("--trace-meta-json must be a JSON object")
        trace_meta.update(obj)

    trace = scheduler_sim.load_trace_jsonl(
        args.trace_jsonl,
        time_mode=args.trace_time_mode.strip().lower(),
        meta_out=trace_meta,
        non_route_policy=args.trace_non_route.strip().lower(),
        input_format=args.trace_input_format.strip().lower(),
        route_type=args.trace_route_type.strip(),
    )
    if args.trace_speedup != 1.0:
        trace = scheduler_sim.scale_trace_speedup(trace, float(args.trace_speedup))
    if args.trace_derive_cost_scale.strip().lower() != "none":
        trace = scheduler_sim.derive_trace_cost_scale(trace, args.trace_derive_cost_scale, meta_out=trace_meta)

    num_experts = int(args.num_experts)
    if num_experts == 0:
        inferred = scheduler_sim.infer_num_experts_from_trace(trace, trace_meta)
        if inferred is None:
            raise SystemExit("--num-experts 0 requires trace/meta with inferable expert range")
        num_experts = int(inferred)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=num_experts,
        expert_parallelism=int(args.expert_parallelism),
        expert_queue_max=int(args.expert_queue_max),
        service_ms=float(args.service_ms),
        starvation_ms=float(args.starvation_ms),
        hi_burst=int(args.hi_burst),
        promote_ms=float(args.promote_ms),
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=int(args.k_min_interactive),
            k_max_interactive=int(args.k_max_interactive),
            k_min_batch=int(args.k_min_batch),
            k_max_batch=int(args.k_max_batch),
            q_low=int(args.q_low),
            q_high=int(args.q_high),
            ema_alpha=float(args.ema_alpha),
            update_ms=float(args.update_ms),
            k_slew=int(args.k_slew),
        ),
        expert_queue_reserve_interactive=int(args.expert_queue_reserve_interactive),
        k_mode=str(args.k_mode),
        k_signal=str(args.k_signal),
        pending_units=str(args.pending_units),
        k_scope=str(args.k_scope),
        admit_policy=str(args.admit_policy),
        sla_interactive_ms=float(args.sla_interactive_ms),
        sla_batch_ms=float(args.sla_batch_ms),
        sim_seed=int(args.sim_seed),
        mtp_draft_len=int(args.mtp_draft_len),
        mtp_accept_prob=float(args.mtp_accept_prob),
        mtp_accept_decay=float(args.mtp_accept_decay),
        mtp_draft_cost_scale=float(args.mtp_draft_cost_scale),
        mtp_verify_per_draft_cost_scale=float(args.mtp_verify_per_draft_cost_scale),
        mtp_draft_attempt_policy=str(args.mtp_draft_attempt_policy),
        batch_max_interactive=int(args.batch_max_interactive),
        batch_max_batch=int(args.batch_max_batch),
        batch_wait_interactive_ms=float(args.batch_wait_interactive_ms),
        batch_wait_batch_ms=float(args.batch_wait_batch_ms),
        service_base_ms=float(args.service_base_ms),
        service_per_task_ms=float(args.service_per_task_ms),
    )

    out = run_trace_sweeps(trace, base_cfg, trace_meta=trace_meta, max_tokens=int(args.max_tokens))
    print(json.dumps(out, sort_keys=True))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
