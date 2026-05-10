#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from typing import Any, Dict, List, Tuple

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sim.scheduler import scheduler_sim  # noqa: E402


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


def run_recommendations(*, quick: bool = False) -> Dict[str, Any]:
    scenarios = {
        "expert_queue_reserve": _expert_queue_reserve_scenario(quick),
        "mtp_efficiency_sweep": _mtp_efficiency_sweep(quick),
        "adaptive_k_batch": _adaptive_k_batch_scenario(quick),
    }
    return({"scenarios": scenarios})


def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scheduler simulator recommendation harness (synthetic scenarios).")
    p.add_argument("--json", action="store_true", help="Print JSON only (default).")
    p.add_argument("--quick", action="store_true", help="Run a reduced-size scenario set (intended for unit tests).")
    return(p.parse_args(argv))


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    out = run_recommendations(quick=bool(args.quick))
    print(json.dumps(out, sort_keys=True))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
