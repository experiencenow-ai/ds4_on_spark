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


def _trace_has_full_k(trace: Sequence[scheduler_sim.TokenRoute]) -> bool:
    for r in trace:
        if r.k is not None:
            continue
        if r.layers is not None and all(lr.k is not None for lr in r.layers):
            continue
        return(False)
    return(True)


def _infer_mtp_draft_len_for_trace(trace: Sequence[scheduler_sim.TokenRoute], meta: Dict[str, object]) -> Optional[int]:
    inferred = scheduler_sim.infer_mtp_draft_len_from_trace(trace, meta)
    if inferred is not None:
        return(int(inferred))

    max_accept_len = 0
    for r in trace:
        if r.mtp_accept_len is None:
            continue
        max_accept_len = max(max_accept_len, int(r.mtp_accept_len))
    if max_accept_len <= 0:
        return(None)

    # mtp_accept_len is the output-token count per verify step (>=1). A draft length of gamma implies:
    #   1 <= accept_len <= (gamma + 1)
    # If a trace only includes accept_len=1 (all rejects), gamma is underdetermined; pick gamma=1 so we can
    # still run an MTP-on replay without violating bounds.
    return(max(1, int(max_accept_len) - 1))


def run_runtime_trace_mtp_ablation(
    *,
    trace: Sequence[scheduler_sim.TokenRoute],
    trace_meta: Optional[Dict[str, object]] = None,
    expert_queue_max: int = 128,
    expert_parallelism: int = 1,
    service_ms: float = 1.0,
) -> Dict[str, Any]:
    meta = dict(trace_meta or {})

    inferred_num_experts = scheduler_sim.infer_num_experts_from_trace(trace, meta)
    if inferred_num_experts is None or int(inferred_num_experts) <= 0:
        raise ValueError("runtime trace ablation requires a trace (or meta.num_experts) with valid expert IDs")

    any_mtp = any((r.mtp_accept_len is not None or r.accepted_mtp is not None or r.rejected_mtp is not None) for r in trace)
    any_dflash = any((r.dflash_accept_len is not None or r.accepted_dflash is not None or r.rejected_dflash is not None) for r in trace)
    mtp_draft_len = 0
    if any_mtp:
        inferred_mtp_draft_len = _infer_mtp_draft_len_for_trace(trace, meta)
        if inferred_mtp_draft_len is None or int(inferred_mtp_draft_len) <= 0:
            raise ValueError("runtime trace ablation requires meta.mtp_draft_len, accepted_mtp+rejected_mtp, or mtp_accept_len in the trace")
        mtp_draft_len = int(inferred_mtp_draft_len)

    k_mode = "trace" if _trace_has_full_k(trace) else "controller"
    base_cfg = scheduler_sim.SimConfig(
        num_experts=int(inferred_num_experts),
        expert_parallelism=int(expert_parallelism),
        expert_queue_max=int(expert_queue_max),
        service_ms=float(service_ms),
        starvation_ms=50.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        ),
        k_mode=str(k_mode),
        k_signal="global",
        sim_seed=123,
        mtp_draft_len=int(mtp_draft_len),
    )

    trace_summary = scheduler_sim.trace_summary_jsonable(trace, mtp_draft_len=int(mtp_draft_len), meta=meta)
    out: Dict[str, Any] = {
        "name": "runtime_trace_mtp_ablation",
        "trace_summary": trace_summary,
        "base_cfg": dataclasses.asdict(base_cfg),
        "results": {},
    }

    if int(mtp_draft_len) <= 0:
        out["note"] = "Trace has no MTP counters; skipping mtp_off ablation."
        if any_dflash:
            cfg_no_mtp = dataclasses.replace(base_cfg, mtp_draft_len=0)
            base_trace = scheduler_sim.scale_trace_arrival_units(trace, "steps", cfg_no_mtp)
            base_metrics = scheduler_sim.run_simulation(cfg_no_mtp, base_trace)
            base_summary = scheduler_sim.compare_summary_jsonable(base_metrics)
            denom = float(base_summary.get("service_slot_ms_per_output_token", 0.0))
            numer = float(base_summary.get("dflash_service_slot_ms_per_output_token", 0.0))
            ratio = (numer / denom) if denom > 0.0 and numer > 0.0 else 0.0
            out["dflash_comparator"] = {
                "present": True,
                "note": "DFlash comparator metrics are kept separate from DeepSeek MTP. Draft compute for the comparator is not modeled; treat efficiency ratios as upper bounds.",
                "summary": base_summary,
                "service_slot_ms_per_output_token_ratio_vs_target_only": float(ratio),
            }
        return(out)

    variants: List[Tuple[str, Dict[str, object]]] = [("mtp_off", {"mtp_draft_len": 0})]
    out["results"] = {
        "arrival_units_steps": scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants, arrival_units="steps"),
        "arrival_units_output_tokens": scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants, arrival_units="output_tokens"),
    }
    if any_dflash:
        mtp_off_summary = out["results"]["arrival_units_steps"]["variants"]["mtp_off"]["summary"]
        denom = float(mtp_off_summary.get("service_slot_ms_per_output_token", 0.0))
        numer = float(mtp_off_summary.get("dflash_service_slot_ms_per_output_token", 0.0))
        ratio = (numer / denom) if denom > 0.0 and numer > 0.0 else 0.0
        out["dflash_comparator"] = {
            "present": True,
            "note": "DFlash comparator metrics are kept separate from DeepSeek MTP. Draft compute for the comparator is not modeled; treat efficiency ratios as upper bounds.",
            "summary": mtp_off_summary,
            "service_slot_ms_per_output_token_ratio_vs_target_only": float(ratio),
        }
    return(out)


def _expert_queue_reserve_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 12000 if quick else 60000
    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=8,
        num_candidates=8,
        interactive_arrival_rate_tps=500.0,
        batch_arrival_rate_tps=20000.0,
        interactive_burst_prob=0.0,
        interactive_burst_scale=1.0,
        batch_burst_prob=0.0,
        batch_burst_scale=1.0,
        zipf_alpha=1.1,
        seed=123,
    )
    trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=128,
        service_ms=1.0,
        starvation_ms=100.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=2,
            q_low=8,
            q_high=96,
        ),
        expert_queue_reserve_interactive=16,
        k_signal="class",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("no_reserve", {"expert_queue_reserve_interactive": 0}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "expert_queue_reserve",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "expert_queue_reserve_interactive": 16,
                "reason": "Synthetic twostream stress: prevents interactive drops under saturated batch backlog.",
            },
        }
    )


def _mtp_efficiency_sweep(quick: bool) -> Dict[str, Any]:
    num_tokens = 6000 if quick else 25000
    trace_cfg = scheduler_sim.HotsetTraceConfig(
        num_tokens=num_tokens,
        num_experts=16,
        num_candidates=8,
        interactive_prob=0.5,
        arrival_rate_tps=6000.0,
        burst_prob=0.0,
        burst_scale=1.0,
        hotset_size=6,
        hotset_bias=0.9,
        hotset_rotate_every_tokens=2000,
        seed=123,
        synthetic_cost_scale_mode="none",
    )
    trace = scheduler_sim.generate_hotset_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=10_000,
        service_ms=0.2,
        starvation_ms=1e9,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        ),
        sim_seed=123,
    )

    baseline_no_mtp = scheduler_sim.run_simulation(dataclasses.replace(base_cfg, mtp_draft_len=0), trace)
    baseline_summary = scheduler_sim.compare_summary_jsonable(baseline_no_mtp)
    base_service_per_out = float(baseline_summary.get("service_slot_ms_per_output_token", 0.0))

    accept_probs = (0.0, 0.6, 1.0) if quick else (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    sweep: List[Dict[str, float]] = []
    for accept_prob in accept_probs:
        cfg = dataclasses.replace(
            base_cfg,
            mtp_draft_len=2,
            mtp_accept_prob=float(accept_prob),
            mtp_accept_decay=0.8,
            mtp_draft_cost_scale=0.25,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        s = scheduler_sim.compare_summary_jsonable(m)
        mtp_service_per_out = float(s.get("service_slot_ms_per_output_token", 0.0))
        ratio = (mtp_service_per_out / base_service_per_out) if base_service_per_out > 0.0 else 0.0
        sweep.append(
            {
                "accept_prob": float(accept_prob),
                "accept_rate": float(s.get("mtp_accept_rate", 0.0)),
                "service_slot_ms_per_output_token": float(mtp_service_per_out),
                "service_slot_ms_per_output_token_ratio_vs_no_mtp": float(ratio),
            }
        )

    min_accept_rate_for_win = None
    for row in sweep:
        if row["service_slot_ms_per_output_token_ratio_vs_no_mtp"] < 1.0:
            min_accept_rate_for_win = float(row["accept_rate"])
            break

    return(
        {
            "name": "mtp_efficiency_sweep",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "baseline_no_mtp": {"service_slot_ms_per_output_token": float(base_service_per_out)},
            "sweep": sweep,
            "recommendation": {
                "mtp_draft_len": 2,
                "mtp_draft_cost_scale": 0.25,
                "min_accept_rate_for_efficiency_win": float(min_accept_rate_for_win) if min_accept_rate_for_win is not None else None,
                "reason": "Synthetic low-congestion regime: MTP helps when accept_rate is high enough to amortize draft cost; validate on real traces before enabling.",
            },
        }
    )


def _adaptive_k_batch_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 8000 if quick else 40000
    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=8,
        num_candidates=8,
        interactive_arrival_rate_tps=500.0,
        batch_arrival_rate_tps=20000.0,
        interactive_burst_prob=0.0,
        interactive_burst_scale=1.0,
        batch_burst_prob=0.0,
        batch_burst_scale=1.0,
        zipf_alpha=1.1,
        seed=123,
    )
    trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=128,
        service_ms=1.0,
        starvation_ms=100.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=2,
            q_low=8,
            q_high=96,
        ),
        expert_queue_reserve_interactive=0,
        k_signal="global",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("batch_k_fixed_2", {"adaptive_k.k_min_batch": 2, "adaptive_k.k_max_batch": 2, "adaptive_k.q_low": 0, "adaptive_k.q_high": 0}),
        ("batch_k_fixed_1", {"adaptive_k.k_min_batch": 1, "adaptive_k.k_max_batch": 1, "adaptive_k.q_low": 0, "adaptive_k.q_high": 0}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "adaptive_k_batch",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "enable_adaptive_k": True,
                "k_min_batch": 1,
                "k_max_batch": 2,
                "q_low": 8,
                "q_high": 96,
                "reason": "Synthetic two-stream saturation: fixed batch K=2 inflates backpressure drops; adaptive batch K throttles under congestion without pinning batch K to 1.",
            },
        }
    )


def _expert_batching_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 6000 if quick else 30000
    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=8,
        num_candidates=8,
        interactive_arrival_rate_tps=500.0,
        batch_arrival_rate_tps=20000.0,
        interactive_burst_prob=0.0,
        interactive_burst_scale=1.0,
        batch_burst_prob=0.0,
        batch_burst_scale=1.0,
        zipf_alpha=1.1,
        seed=123,
    )
    trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=128,
        service_ms=1.0,
        starvation_ms=100.0,
        hi_burst=8,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=2,
            q_low=8,
            q_high=96,
        ),
        expert_queue_reserve_interactive=16,
        k_signal="global",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
        batch_max_interactive=1,
        batch_max_batch=1,
        batch_wait_interactive_ms=0.0,
        batch_wait_batch_ms=0.0,
        service_base_ms=0.25,
        service_per_task_ms=1.0,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("batch_max_batch_4", {"batch_max_batch": 4}),
        ("batch_max_batch_8", {"batch_max_batch": 8}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "expert_batching",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "batch_max_batch_default": 4,
                "batch_wait_batch_ms_default": 0.0,
                "service_base_ms_model": 0.25,
                "reason": "Synthetic overload with per-batch overhead: larger batch_max_batch amortizes service_base_ms and reduces backpressure drops, but increases interactive tail latency because batch work becomes less preemptible. Treat 4 as a conservative starting point; validate on real traces.",
            },
        }
    )


def _admit_policy_skew_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 64 if quick else 256
    num_experts = 8
    candidates = tuple(range(num_experts))
    trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=candidates) for _ in range(num_tokens)]

    base_cfg = scheduler_sim.SimConfig(
        num_experts=num_experts,
        expert_parallelism=1,
        expert_queue_max=100_000,
        service_ms=1.0,
        starvation_ms=1e9,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=2,
            k_max_batch=2,
            q_low=0,
            q_high=0,
        ),
        admit_policy="ordered",
        sim_seed=123,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("least_pending", {"admit_policy": "least_pending"}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "admit_policy_skew",
            "trace_cfg": {
                "trace_mode": "manual_burst_same_time",
                "num_tokens": int(num_tokens),
                "num_experts": int(num_experts),
                "candidates": list(candidates),
                "cls": "batch",
                "t_ms": 0.0,
            },
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "default_admit_policy": "ordered",
                "experimental_admit_policy": "least_pending",
                "reason": "Synthetic burst stress: least_pending spreads work across candidates and sharply reduces load skew/makespan, but it ignores router preference order; validate on real traces before enabling in runtime.",
            },
        }
    )


def _mtp_congestion_sweep(quick: bool) -> Dict[str, Any]:
    num_tokens = 8000 if quick else 40000
    interactive_output_tps = 500.0
    batch_output_tps = 20000.0

    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=8,
        num_candidates=8,
        interactive_arrival_rate_tps=float(interactive_output_tps),
        batch_arrival_rate_tps=float(batch_output_tps),
        interactive_burst_prob=0.0,
        interactive_burst_scale=1.0,
        batch_burst_prob=0.0,
        batch_burst_scale=1.0,
        zipf_alpha=1.1,
        seed=123,
    )
    base_trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=128,
        service_ms=1.0,
        starvation_ms=100.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=2,
            q_low=8,
            q_high=96,
        ),
        expert_queue_reserve_interactive=16,
        k_signal="class",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
    )

    draft_len = 2
    accept_decay = 0.8
    accept_probs = (0.0, 0.6, 1.0) if quick else (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

    def _scale_trace_time(trace: List[scheduler_sim.TokenRoute], scale: float) -> List[scheduler_sim.TokenRoute]:
        if scale <= 0.0:
            raise ValueError("scale must be > 0")
        return([dataclasses.replace(r, t_ms=(float(r.t_ms) * float(scale))) for r in trace])

    no_mtp_metrics = scheduler_sim.run_simulation(dataclasses.replace(base_cfg, mtp_draft_len=0), base_trace)
    no_mtp_summary = scheduler_sim.compare_summary_jsonable(no_mtp_metrics)

    sweep: List[Dict[str, Any]] = []
    for accept_prob in accept_probs:
        exp_len = scheduler_sim.expected_mtp_accept_len(draft_len, float(accept_prob), float(accept_decay))
        if exp_len <= 0.0:
            exp_len = 1.0
        trace_scaled = _scale_trace_time(base_trace, float(exp_len))

        cfg_full = dataclasses.replace(
            base_cfg,
            mtp_draft_len=draft_len,
            mtp_accept_prob=float(accept_prob),
            mtp_accept_decay=float(accept_decay),
            mtp_draft_cost_scale=0.25,
            mtp_draft_attempt_policy="full",
        )
        cfg_stop = dataclasses.replace(cfg_full, mtp_draft_attempt_policy="stop_at_reject")

        m_full = scheduler_sim.run_simulation(cfg_full, trace_scaled)
        m_stop = scheduler_sim.run_simulation(cfg_stop, trace_scaled)

        s_full = scheduler_sim.compare_summary_jsonable(m_full)
        s_stop = scheduler_sim.compare_summary_jsonable(m_stop)

        sweep.append(
            {
                "accept_prob": float(accept_prob),
                "expected_accept_len": float(exp_len),
                "trace_time_scale": float(exp_len),
                "no_mtp": no_mtp_summary,
                "mtp_full": s_full,
                "mtp_stop_at_reject": s_stop,
            }
        )

    return(
        {
            "name": "mtp_congestion_sweep",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "sweep": sweep,
            "recommendation": {
                "draft_len": int(draft_len),
                "draft_attempt_policy_default": "stop_at_reject",
                "reason": "Synthetic overload: even when MTP can improve service/throughput, draft work can increase queue pressure; prefer stop_at_reject for safer overhead under low accept, and validate interactive SLA + verify-phase starvation on real traces before enabling.",
            },
        }
    )


def _k_signal_policy_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 12000 if quick else 60000
    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=16,
        num_candidates=4,
        interactive_arrival_rate_tps=2000.0,
        batch_arrival_rate_tps=20000.0,
        interactive_burst_prob=0.0,
        interactive_burst_scale=1.0,
        batch_burst_prob=0.0,
        batch_burst_scale=1.0,
        zipf_alpha=1.1,
        seed=123,
    )
    trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=128,
        service_ms=1.0,
        starvation_ms=100.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=2,
            q_low=8,
            q_high=96,
        ),
        expert_queue_reserve_interactive=16,
        k_signal="global",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("k_signal_candidates", {"k_signal": "candidates"}),
        ("k_signal_class", {"k_signal": "class"}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "k_signal_policy",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "k_signal_default": "global",
                "reason": "Synthetic overload: class-local pending signals can over-admit interactive work and amplify SLA violations under heavy batch congestion; keep global/candidates signals as the default until real-trace calibration says otherwise.",
            },
        }
    )


def _batch_starvation_knobs_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 12000 if quick else 60000
    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=8,
        num_candidates=8,
        interactive_arrival_rate_tps=5000.0,
        batch_arrival_rate_tps=2000.0,
        interactive_burst_prob=0.0,
        interactive_burst_scale=1.0,
        batch_burst_prob=0.0,
        batch_burst_scale=1.0,
        zipf_alpha=0.2,
        seed=123,
    )
    trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=10_000,
        service_ms=1.0,
        starvation_ms=50.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        ),
        k_signal="global",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("hi_burst_8", {"hi_burst": 8}),
        ("promote_20ms", {"promote_ms": 20.0}),
        ("hi_burst_8_promote_20ms", {"hi_burst": 8, "promote_ms": 20.0}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "batch_starvation_knobs",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "hi_burst_default": 8,
                "reason": "Synthetic mixed load: hi_burst reduces batch starvation with modest interactive p95 cost; promote_ms can reduce starvation further but may substantially inflate interactive tail latency. Treat promote as an opt-in.",
            },
        }
    )


def _backpressure_units_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 8000 if quick else 40000
    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=8,
        num_candidates=8,
        interactive_arrival_rate_tps=500.0,
        batch_arrival_rate_tps=20000.0,
        interactive_burst_prob=0.0,
        interactive_burst_scale=1.0,
        batch_burst_prob=0.0,
        batch_burst_scale=1.0,
        zipf_alpha=1.1,
        seed=123,
        synthetic_cost_scale_mode="lognormal",
        synthetic_cost_scale_log_sigma=1.0,
    )
    trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=128,
        service_ms=1.0,
        starvation_ms=100.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=2,
            k_max_batch=2,
            q_low=8,
            q_high=96,
        ),
        expert_queue_reserve_interactive=16,
        k_signal="class",
        pending_units="work",
        backpressure_units="tasks",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("backpressure_work", {"backpressure_units": "work"}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "backpressure_units",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "support_backpressure_units_work": True,
                "reason": "Synthetic variable-cost traces: task-count backpressure can hide large work spikes; work-unit backpressure better matches service-time scaling when cost_scale is meaningful. Validate against real quantized-runtime traces before defaulting to work units.",
            },
        }
    )


def run_recommendations(*, quick: bool = False) -> Dict[str, Any]:
    scenarios = {
        "expert_queue_reserve": _expert_queue_reserve_scenario(quick),
        "mtp_efficiency_sweep": _mtp_efficiency_sweep(quick),
        "adaptive_k_batch": _adaptive_k_batch_scenario(quick),
        "expert_batching": _expert_batching_scenario(quick),
        "admit_policy_skew": _admit_policy_skew_scenario(quick),
        "mtp_congestion_sweep": _mtp_congestion_sweep(quick),
        "k_signal_policy": _k_signal_policy_scenario(quick),
        "batch_starvation_knobs": _batch_starvation_knobs_scenario(quick),
        "backpressure_units": _backpressure_units_scenario(quick),
    }
    return({"scenarios": scenarios})


def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scheduler simulator recommendation harness (synthetic scenarios, plus optional runtime-trace MTP ablation).")
    p.add_argument("--json", action="store_true", help="Print JSON only (default).")
    p.add_argument("--quick", action="store_true", help="Run a reduced-size scenario set (intended for unit tests).")
    p.add_argument("--trace-jsonl", type=str, default="", help="Optional: run runtime-trace MTP ablation on this JSONL trace path ('-' for stdin) instead of synthetic scenarios.")
    p.add_argument(
        "--trace-input-format",
        type=str,
        default="runtime",
        choices=("strict", "runtime"),
        help="Trace parser input format for --trace-jsonl: strict expects the simulator contract; runtime maps common runtime-field aliases (and with --trace-non-route skip scans non-JSON lines for embedded JSON objects).",
    )
    p.add_argument("--trace-non-route", type=str, default="skip", help="When --trace-jsonl contains non-route records, skip or error (default: skip).")
    p.add_argument("--trace-default-cls", type=str, default="", help="When --trace-jsonl records omit latency class, force all extracted records to this cls (interactive or batch).")
    p.add_argument("--trace-time-mode", type=str, default="t_ms", help="Trace time field mode: t_ms (default) or dt_ms.")
    p.add_argument("--max-tokens", type=int, default=0, help="Optional cap on number of trace records to read (0 = no cap).")
    return(p.parse_args(argv))


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.trace_jsonl.strip() != "":
        meta: Dict[str, object] = {}
        trace = scheduler_sim.load_trace_jsonl(
            args.trace_jsonl.strip(),
            time_mode=args.trace_time_mode.strip().lower(),
            meta_out=meta,
            non_route_policy=args.trace_non_route.strip().lower(),
            input_format=args.trace_input_format.strip().lower(),
            route_type="",
            default_cls=args.trace_default_cls,
        )
        if int(args.max_tokens) > 0:
            trace = list(trace[: int(args.max_tokens)])
        out = run_runtime_trace_mtp_ablation(trace=trace, trace_meta=meta)
    else:
        out = run_recommendations(quick=bool(args.quick))
    print(json.dumps(out, sort_keys=True))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
