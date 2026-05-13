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

def _as_dict(obj: object) -> Dict[str, object]:
    if isinstance(obj, dict):
        return(obj)  # type: ignore[return-value]
    return({})

def _as_float(obj: object, key: str, default: float = 0.0) -> float:
    if not isinstance(obj, dict):
        return(float(default))
    v = obj.get(key, default)
    if isinstance(v, (int, float)):
        return(float(v))
    return(float(default))

def _as_int(obj: object, key: str, default: int = 0) -> int:
    if not isinstance(obj, dict):
        return(int(default))
    v = obj.get(key, default)
    if isinstance(v, bool):
        return(int(default))
    if isinstance(v, int):
        return(int(v))
    if isinstance(v, float):
        if float(int(v)) == float(v):
            return(int(v))
    return(int(default))

def _as_str(obj: object, key: str, default: str = "") -> str:
    if not isinstance(obj, dict):
        return(str(default))
    v = obj.get(key, default)
    if isinstance(v, str):
        return(str(v))
    return(str(default))

def _fmt_delta(x: float, *, digits: int = 3) -> str:
    try:
        v = float(x)
    except Exception:
        v = 0.0
    sign = "+" if v >= 0.0 else ""
    return(f"{sign}{v:.{int(digits)}f}")

def format_runtime_trace_ablation_markdown(out: Dict[str, Any]) -> str:
    trace_summary = _as_dict(out.get("trace_summary"))
    inferred = _as_dict(trace_summary.get("inferred"))
    evidence = _as_dict(out.get("evidence"))

    mtp = _as_dict(evidence.get("mtp"))
    expert_queueing = _as_dict(evidence.get("expert_queueing"))
    mtp_draft_queue_cls = _as_dict(evidence.get("mtp_draft_queue_cls"))
    dflash = _as_dict(out.get("dflash_comparator"))
    topk_dump_probe = _as_dict(out.get("topk_dump_probe"))
    results = _as_dict(out.get("results"))

    lines: List[str] = []
    lines.append("# Scheduler Simulator Runtime Trace Report")
    lines.append("")

    tokens = _as_dict(trace_summary.get("tokens"))
    num_interactive = _as_int(tokens, "interactive", 0)
    num_batch = _as_int(tokens, "batch", 0)

    lines.append("## Trace")
    lines.append(f"- name: `{_as_str(out, 'name', 'runtime_trace_mtp_ablation')}`")
    num_records = _as_int(trace_summary, "num_records", 0)
    if num_records > 0:
        lines.append(f"- records: {int(num_records)}")
    num_layers = _as_int(inferred, "num_layers", 0)
    if num_layers > 0:
        lines.append(f"- inferred layers: {int(num_layers)}")
    num_experts = _as_int(inferred, "num_experts", 0)
    if num_experts > 0:
        lines.append(f"- inferred experts: {int(num_experts)}")
    mtp_draft_len = _as_int(inferred, "mtp_draft_len", 0)
    if mtp_draft_len > 0:
        lines.append(f"- inferred mtp_draft_len: {int(mtp_draft_len)}")
    dflash_draft_len = _as_int(inferred, "dflash_draft_len", 0)
    if dflash_draft_len > 0:
        lines.append(f"- inferred dflash_draft_len: {int(dflash_draft_len)}")
    if bool(out.get("trace_assumptions")):
        ta = _as_dict(out.get("trace_assumptions"))
        if bool(ta.get("time_synthetic")):
            lines.append("- time: synthetic timestamps (conditional on arrival_rate_tps/batch_size assumptions)")
    lines.append("")

    lines.append("## Evidence")
    if bool(mtp.get("present")):
        supported = bool(mtp.get("supported_by_trace_counters")) or bool(mtp.get("supported_by_synthetic_model"))
        ratio = _as_float(mtp, "service_slot_ms_per_output_token_ratio_vs_mtp_off", 0.0)
        lines.append(f"- mtp: present (mode=`{_as_str(mtp, 'mode', '')}`) supported={str(bool(supported)).lower()} ratio_vs_off={ratio:.4f}")
        lines.append(f"  - mtp_accept_rate={_as_float(mtp, 'mtp_accept_rate', 0.0):.4f} mtp_mean_accept_len={_as_float(mtp, 'mtp_mean_accept_len', 0.0):.3f}")
        reason = _as_str(mtp, "reason", "")
        if reason != "":
            lines.append(f"  - note: {reason}")
    else:
        lines.append("- mtp: not present in trace (or disabled)")

    if bool(expert_queueing.get("present")) and isinstance(expert_queueing.get("best_variant_by_drop"), dict):
        best = _as_dict(expert_queueing.get("best_variant_by_drop"))
        drop_metric = _as_str(expert_queueing, "drop_metric", "")
        lat_metric = _as_str(expert_queueing, "latency_metric", "")
        supported_q = bool(expert_queueing.get("supported_by_trace_counters"))
        lines.append(f"- expert_queueing: supported={str(bool(supported_q)).lower()} best_variant=`{_as_str(best, 'label', '')}`")
        if drop_metric != "":
            lines.append(f"  - {drop_metric} delta={_fmt_delta(_as_float(best, 'delta_drop', 0.0), digits=6)}")
        if lat_metric != "":
            lines.append(f"  - {lat_metric} delta_ms={_fmt_delta(_as_float(best, 'delta_p95_latency_ms', 0.0), digits=3)}")
        reason = _as_str(expert_queueing, "reason", "")
        if reason != "":
            lines.append(f"  - note: {reason}")
    elif bool(expert_queueing.get("present")):
        note = _as_str(expert_queueing, "note", "")
        if note != "":
            lines.append(f"- expert_queueing: present; note: {note}")
        else:
            lines.append("- expert_queueing: present")

    if bool(mtp_draft_queue_cls.get("present")):
        supported_dq = bool(mtp_draft_queue_cls.get("supported_by_trace_counters")) or bool(mtp_draft_queue_cls.get("supported_by_synthetic_model"))
        lines.append(f"- mtp_draft_queue_cls: present (variant=`{_as_str(mtp_draft_queue_cls, 'variant', '')}`) supported={str(bool(supported_dq)).lower()}")

    if bool(dflash.get("present")):
        ratio = _as_float(dflash, "service_slot_ms_per_output_token_ratio_vs_target_only", 0.0)
        ratio_adj = _as_float(dflash, "service_slot_ms_per_output_token_ratio_vs_target_only_adjusted", 0.0)
        lines.append(f"- dflash_comparator: present ratio_vs_target_only={ratio:.4f} adjusted={ratio_adj:.4f}")

    if bool(topk_dump_probe.get("present")):
        tnote = _as_str(topk_dump_probe, "note", "")
        summary = _as_dict(topk_dump_probe.get("summary"))
        invalid = _as_int(summary, "invalid_expert_ids", 0)
        lines.append(f"- topk_dump_probe: present invalid_expert_ids={int(invalid)}")
        if tnote != "":
            lines.append(f"  - note: {tnote}")
        batches = _as_dict(summary.get("batches"))
        if batches is not None:
            batch_keys: List[int] = []
            for k in batches.keys():
                if isinstance(k, str) and k.strip().isdigit():
                    batch_keys.append(int(k.strip()))
            batch_keys = sorted(set(batch_keys))
            if len(batch_keys) != 0:
                picks: List[int] = []
                if 100 in batch_keys:
                    picks.append(100)
                if 256 in batch_keys and 256 not in picks:
                    picks.append(256)
                for k in (batch_keys[0], batch_keys[-1]):
                    if k not in picks:
                        picks.append(int(k))
                picks = picks[:4]

                def _metric_median(batch: int, metric: str) -> float:
                    b = batches.get(str(int(batch)))
                    if not isinstance(b, dict):
                        return(0.0)
                    block = b.get(metric)
                    if not isinstance(block, dict):
                        return(0.0)
                    v = block.get("median", 0.0)
                    if isinstance(v, (int, float)):
                        return(float(v))
                    return(0.0)

                parts = []
                for batch in picks:
                    active = _metric_median(batch, "active")
                    p90 = _metric_median(batch, "p90_depth")
                    sp6 = _metric_median(batch, "pair_speedup_cap6")
                    parts.append(f"b{int(batch)} active={active:.2f} p90_depth={p90:.2f} speedup_cap6={sp6:.2f}x")
                if len(parts) != 0:
                    lines.append("  - " + "; ".join(parts))



    def _as_summary(obj: object) -> Dict[str, float]:
        if not isinstance(obj, dict):
            return({})
        raw = obj.get("summary")
        if not isinstance(raw, dict):
            return({})
        out_s: Dict[str, float] = {}
        for k, v in raw.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, (int, float)):
                continue
            out_s[k] = float(v)
        return(out_s)

    def _fmt_float(x: float, *, digits: int = 3) -> str:
        try:
            v = float(x)
        except Exception:
            v = 0.0
        return(f"{v:.{int(digits)}f}")

    def _fmt_pct(x: float, *, digits: int = 3) -> str:
        try:
            v = float(x)
        except Exception:
            v = 0.0
        return(f"{(100.0 * v):.{int(digits)}f}%")

    def _render_sweep_table(title: str, sweep: Dict[str, object]) -> None:
        base_node = sweep.get("baseline")
        variants_node = sweep.get("variants")
        if not isinstance(base_node, dict) or not isinstance(variants_node, dict):
            return
        base_sum = _as_summary(base_node)
        if len(base_sum) == 0:
            return

        has_i = bool(int(num_interactive) > 0)
        has_b = bool(int(num_batch) > 0)

        headers = ["variant", "svc_ms/out", "out_tps", "pending_p95", "starv_frac", "starv_p95_ms"]
        if has_i:
            headers += ["pending_hi_p95"]
        if has_b:
            headers += ["pending_lo_p95"]
        if has_i:
            headers += ["drop_i", "p95_i_ms"]
        if has_b:
            headers += ["drop_b", "p95_b_ms"]
        if bool(mtp.get("present")):
            headers += ["verify_q_p95_ms", "draft_q_p95_ms"]

        rows: List[Tuple[str, Dict[str, float]]] = [("baseline", base_sum)]
        for label in sorted(variants_node.keys()):
            node = variants_node.get(label)
            if not isinstance(node, dict):
                continue
            s = _as_summary(node)
            if len(s) == 0:
                continue
            rows.append((str(label), s))

        lines.append(f"## {title}")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---" for _h in headers]) + " |")
        for label, s in rows:
            cells: List[str] = []
            cells.append(str(label))
            cells.append(_fmt_float(float(s.get("service_slot_ms_per_output_token", 0.0)), digits=4))
            cells.append(_fmt_float(float(s.get("output_token_throughput_tps", 0.0)), digits=3))
            cells.append(_fmt_float(float(s.get("pending_depth_time_weighted_p95", 0.0)), digits=3))
            cells.append(_fmt_pct(float(s.get("starved_task_frac", 0.0)), digits=3))
            cells.append(_fmt_float(float(s.get("starved_task_queue_wait_ms_p95", 0.0)), digits=3))
            if has_i:
                cells.append(_fmt_float(float(s.get("pending_hi_depth_time_weighted_p95", 0.0)), digits=3))
            if has_b:
                cells.append(_fmt_float(float(s.get("pending_lo_depth_time_weighted_p95", 0.0)), digits=3))
            if has_i:
                cells.append(_fmt_pct(float(s.get("drop_frac_tokens_interactive", 0.0)), digits=3))
                cells.append(_fmt_float(float(s.get("output_token_p95_interactive_ms", 0.0)), digits=3))
            if has_b:
                cells.append(_fmt_pct(float(s.get("drop_frac_tokens_batch", 0.0)), digits=3))
                cells.append(_fmt_float(float(s.get("output_token_p95_batch_ms", 0.0)), digits=3))
            if bool(mtp.get("present")):
                cells.append(_fmt_float(float(s.get("task_queue_wait_ms_p95_mtp_verify", 0.0)), digits=3))
                cells.append(_fmt_float(float(s.get("task_queue_wait_ms_p95_mtp_draft", 0.0)), digits=3))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    if results is not None:
        sweep_steps = _as_dict(results.get("arrival_units_steps"))
        if sweep_steps is not None:
            _render_sweep_table("Results (arrival_units=steps)", sweep_steps)

        sweep_out = _as_dict(results.get("arrival_units_output_tokens"))
        if sweep_out is not None:
            _render_sweep_table("Results (arrival_units=output_tokens)", sweep_out)

    lines.append("")
    return("\n".join(lines))


def run_runtime_trace_mtp_ablation(
    *,
    name: str = "runtime_trace_mtp_ablation",
    trace: Sequence[scheduler_sim.TokenRoute],
    trace_meta: Optional[Dict[str, object]] = None,
    expert_queue_max: int = 128,
    expert_parallelism: int = 1,
    service_ms: float = 1.0,
    starvation_ms: float = 50.0,
    trace_derive_cost_scale: str = "none",
    trace_speedup: float = 1.0,
    mtp_draft_len: int = -1,
    mtp_accept_model: str = "geom",
    mtp_accept_hist: Sequence[float] = (),
    mtp_accept_prob: float = 0.0,
    mtp_accept_decay: float = 1.0,
    mtp_draft_cost_scale: float = 0.25,
    mtp_verify_per_draft_cost_scale: float = 0.0,
    mtp_draft_attempt_policy: str = "full",
    dflash_draft_len: int = -1,
    dflash_draft_cost_scale: Optional[float] = None,
) -> Dict[str, Any]:
    meta = dict(trace_meta or {})
    name_out = str(name).strip()
    if name_out == "":
        name_out = "runtime_trace_mtp_ablation"

    def _reserve_default(qmax: int) -> int:
        if int(qmax) <= 0:
            return(0)
        return(min(16, int(qmax)))

    def _trace_has_any_cost_scale(trace_in: Sequence[scheduler_sim.TokenRoute]) -> bool:
        for r in trace_in:
            if r.cost_scale is not None:
                return(True)
            if r.layers is None:
                continue
            for lr in r.layers:
                if lr.cost_scale is not None:
                    return(True)
        return(False)

    if trace_derive_cost_scale.strip().lower() != "none":
        trace = scheduler_sim.derive_trace_cost_scale(trace, trace_derive_cost_scale, meta_out=meta)
    if float(trace_speedup) != 1.0:
        trace = scheduler_sim.scale_trace_speedup(trace, float(trace_speedup))

    inferred_num_experts = scheduler_sim.infer_num_experts_from_trace(trace, meta)
    if inferred_num_experts is None or int(inferred_num_experts) <= 0:
        raise ValueError("runtime trace ablation requires a trace (or meta.num_experts) with valid expert IDs")

    any_mtp = any((r.mtp_accept_len is not None or r.accepted_mtp is not None or r.rejected_mtp is not None) for r in trace)
    any_dflash = any((r.dflash_accept_len is not None or r.accepted_dflash is not None or r.rejected_dflash is not None) for r in trace)
    if any_dflash and int(dflash_draft_len) != -1:
        meta["dflash_draft_len"] = int(dflash_draft_len)
    if any_dflash and dflash_draft_cost_scale is not None:
        meta["dflash_draft_cost_scale"] = float(dflash_draft_cost_scale)

    mtp_draft_len_req = int(mtp_draft_len)
    mtp_draft_len_inferred = 0
    mtp_mode = "none"
    if any_mtp:
        inferred_mtp_draft_len = _infer_mtp_draft_len_for_trace(trace, meta)
        if inferred_mtp_draft_len is None or int(inferred_mtp_draft_len) <= 0:
            raise ValueError("runtime trace ablation requires meta.mtp_draft_len, accepted_mtp+rejected_mtp, or mtp_accept_len in the trace")
        mtp_draft_len_inferred = int(inferred_mtp_draft_len)
        mtp_mode = "trace"
    elif mtp_draft_len_req > 0:
        mtp_draft_len_inferred = int(mtp_draft_len_req)
        mtp_mode = "synthetic"

    mtp_draft_len_out = int(mtp_draft_len_inferred)

    k_mode = "trace" if _trace_has_full_k(trace) else "controller"
    fixed_k_from_meta = 0
    if k_mode == "controller":
        sf = str(meta.get("source_format", "")).strip().lower()
        if sf == "ds4_ffn_moe_topk_i32":
            topk_raw = meta.get("topk")
            if isinstance(topk_raw, int):
                fixed_k_from_meta = int(topk_raw)
            elif isinstance(topk_raw, float):
                if float(int(topk_raw)) == float(topk_raw):
                    fixed_k_from_meta = int(topk_raw)
            if fixed_k_from_meta < 1:
                fixed_k_from_meta = 0
            elif fixed_k_from_meta > 0:
                meta["k_fixed_from_meta"] = int(fixed_k_from_meta)
    dflash_cost_scale = 0.0
    if any_dflash:
        if isinstance(meta.get("dflash_draft_cost_scale"), (int, float)):
            dflash_cost_scale = float(meta["dflash_draft_cost_scale"])
        if dflash_cost_scale < 0.0:
            raise ValueError("meta.dflash_draft_cost_scale must be >= 0")

    k_min_interactive = 1
    k_max_interactive = 1
    k_min_batch = 1
    k_max_batch = 1
    q_low = 0
    q_high = 0
    if fixed_k_from_meta > 0:
        # DS4 ffn_moe_topk dumps contain *selected* experts per token/layer. When replaying these
        # route-only traces, treat topk as the fixed K so service and queue depth scale correctly.
        k_min_interactive = int(fixed_k_from_meta)
        k_max_interactive = int(fixed_k_from_meta)
        k_min_batch = int(fixed_k_from_meta)
        k_max_batch = int(fixed_k_from_meta)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=int(inferred_num_experts),
        expert_parallelism=int(expert_parallelism),
        expert_queue_max=int(expert_queue_max),
        service_ms=float(service_ms),
        starvation_ms=float(starvation_ms),
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=int(k_min_interactive),
            k_max_interactive=int(k_max_interactive),
            k_min_batch=int(k_min_batch),
            k_max_batch=int(k_max_batch),
            q_low=int(q_low),
            q_high=int(q_high),
        ),
        k_mode=str(k_mode),
        k_signal="global",
        sim_seed=123,
        mtp_draft_len=int(mtp_draft_len_out),
        mtp_accept_model=str(mtp_accept_model),
        mtp_accept_hist=tuple(float(x) for x in mtp_accept_hist),
        mtp_accept_prob=float(mtp_accept_prob),
        mtp_accept_decay=float(mtp_accept_decay),
        mtp_draft_cost_scale=float(mtp_draft_cost_scale),
        mtp_verify_per_draft_cost_scale=float(mtp_verify_per_draft_cost_scale),
        mtp_draft_attempt_policy=str(mtp_draft_attempt_policy),
        dflash_draft_len=int(meta.get("dflash_draft_len", -1)) if any_dflash else -1,
        dflash_draft_cost_scale=float(dflash_cost_scale) if any_dflash else 0.0,
    )

    trace_summary = scheduler_sim.trace_summary_jsonable(trace, mtp_draft_len=int(mtp_draft_len_out), meta=meta)

    trace_sched = scheduler_sim.strip_trace_mtp_fields(trace)
    cfg_sched = dataclasses.replace(base_cfg, mtp_draft_len=0)
    reserve_n = _reserve_default(int(expert_queue_max))
    has_cost_scale = _trace_has_any_cost_scale(trace)
    has_interactive = any(r.cls == scheduler_sim.LatencyClass.INTERACTIVE for r in trace_sched)
    has_batch = any(r.cls == scheduler_sim.LatencyClass.BATCH for r in trace_sched)

    sched_variants: List[Tuple[str, Dict[str, object]]] = [
        ("stall_zero_admit", {"backpressure_zero_admit_policy": "stall"}),
    ]
    qhalf = max(1, int(expert_queue_max) // 2)
    qdouble = int(expert_queue_max) * 2
    if int(qhalf) != int(expert_queue_max):
        sched_variants.append((f"queue_max_{int(qhalf)}", {"expert_queue_max": int(qhalf)}))
    if int(qdouble) != int(expert_queue_max):
        sched_variants.append((f"queue_max_{int(qdouble)}", {"expert_queue_max": int(qdouble)}))
    if has_cost_scale:
        sched_variants.append(("work_units", {"pending_units": "work", "backpressure_units": "work"}))
    if has_interactive and has_batch and reserve_n > 0:
        sched_variants.append((f"reserve_interactive_{int(reserve_n)}", {"expert_queue_reserve_interactive": int(reserve_n), "k_signal": "class"}))

    if int(expert_queue_max) > 1:
        q_low = max(1, int(expert_queue_max) // 4)
        q_high = max(int(q_low), int(expert_queue_max) // 2)
        sched_variants.append(
            (
                "adaptive_k_batch2",
                {
                    "adaptive_k.k_max_batch": 2,
                    "adaptive_k.q_low": int(q_low),
                    "adaptive_k.q_high": int(q_high),
                    "k_signal": "candidates",
                },
            )
        )

    out: Dict[str, Any] = {
        "name": str(name_out),
        "trace_summary": trace_summary,
        "base_cfg": dataclasses.asdict(base_cfg),
        "mtp_mode": str(mtp_mode),
        "scheduler_sweeps": {
            "arrival_units_steps": scheduler_sim.compare_simulation_summaries(cfg_sched, trace_sched, sched_variants, arrival_units="steps"),
        },
        "results": {},
    }
    if bool(meta.get("time_synthetic")):
        out["trace_assumptions"] = {
            "time_synthetic": True,
            "note": "Trace timestamps are synthetic; queue/backpressure/latency deltas are conditional on arrival_rate_tps/batch_size assumptions.",
        }


    def _as_summary(obj: object) -> Dict[str, float]:
        if not isinstance(obj, dict):
            return({})
        raw = obj.get("summary")
        if not isinstance(raw, dict):
            return({})
        out_s: Dict[str, float] = {}
        for k, v in raw.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, (int, float)):
                continue
            out_s[k] = float(v)
        return(out_s)

    def _as_float(summary: Dict[str, float], key: str) -> float:
        v = summary.get(key, 0.0)
        try:
            return(float(v))
        except Exception:
            return(0.0)

    def _delta(a: Dict[str, float], b: Dict[str, float], key: str) -> float:
        return(_as_float(b, key) - _as_float(a, key))

    def _sweep_baseline_summary(sweep: Dict[str, object]) -> Dict[str, float]:
        if not isinstance(sweep.get("baseline"), dict):
            return({})
        return(_as_summary(sweep["baseline"]))

    def _sweep_variant_summary(sweep: Dict[str, object], label: str) -> Dict[str, float]:
        variants = sweep.get("variants")
        if not isinstance(variants, dict):
            return({})
        v = variants.get(label)
        if not isinstance(v, dict):
            return({})
        return(_as_summary(v))

    def _select_trace_metric(has_interactive: bool, has_batch: bool, interactive_key: str, batch_key: str, fallback_key: str) -> str:
        if has_interactive and interactive_key != "":
            return(str(interactive_key))
        if has_batch and batch_key != "":
            return(str(batch_key))
        return(str(fallback_key))

    evidence: Dict[str, Any] = {"mtp": {"present": bool(any_mtp), "mode": str(mtp_mode)}, "expert_queueing": {"present": True}}

    sweep_steps = out["scheduler_sweeps"]["arrival_units_steps"]
    sweep_base = _sweep_baseline_summary(sweep_steps) if isinstance(sweep_steps, dict) else {}
    if isinstance(sweep_steps, dict):
        v_best = None
        best_drop_delta = 0.0
        drop_key = _select_trace_metric(bool(has_interactive), bool(has_batch), "drop_frac_tokens_interactive", "drop_frac_tokens_batch", "drop_frac_tokens")
        for label in sched_variants:
            if not isinstance(label, tuple) or len(label) != 2:
                continue
            v_label = str(label[0])
            v_sum = _sweep_variant_summary(sweep_steps, v_label)
            if len(v_sum) == 0:
                continue
            dd = _delta(sweep_base, v_sum, drop_key)
            if v_best is None or dd < best_drop_delta:
                v_best = v_label
                best_drop_delta = float(dd)

        if v_best is not None:
            v_sum = _sweep_variant_summary(sweep_steps, v_best)
            lat_key = _select_trace_metric(
                bool(has_interactive),
                bool(has_batch),
                "output_token_p95_interactive_ms",
                "output_token_p95_batch_ms",
                "output_token_p95_batch_ms",
            )
            base_drop = _as_float(sweep_base, drop_key)
            best_drop = _as_float(v_sum, drop_key)
            base_lat = _as_float(sweep_base, lat_key)
            best_lat = _as_float(v_sum, lat_key)
            delta_drop = (best_drop - base_drop)
            delta_lat = (best_lat - base_lat)
            max_latency_increase_frac = 0.10
            max_latency_increase_ms = max(5.0, (max_latency_increase_frac * base_lat)) if base_lat > 0.0 else 0.0
            supported = False
            reason = "No best scheduler variant available."
            if base_drop <= 0.0:
                reason = f"Baseline drop metric is 0.0 (metric={drop_key}); no backpressure evidence to justify expert queueing changes."
            elif delta_drop >= 0.0:
                reason = f"Best scheduler variant does not reduce drops (metric={drop_key}); delta_drop={delta_drop:+.6f}."
            elif base_lat > 0.0 and delta_lat > max_latency_increase_ms:
                reason = f"Drop reduction comes with a large p95 latency increase (metric={lat_key}); delta_p95_latency_ms={delta_lat:+.3f} exceeds heuristic cap={max_latency_increase_ms:.3f} (max({int(max_latency_increase_frac*100)}%,5ms))."
            else:
                supported = True
                reason = f"Best scheduler variant reduces drops (metric={drop_key}) with acceptable p95 latency impact (metric={lat_key}); delta_drop={delta_drop:+.6f}, delta_p95_latency_ms={delta_lat:+.3f}, cap={max_latency_increase_ms:.3f}."
            evidence["expert_queueing"] = {
                "present": True,
                "drop_metric": str(drop_key),
                "latency_metric": str(lat_key),
                "best_variant_by_drop": {
                    "label": str(v_best),
                    "delta_drop": float(_delta(sweep_base, v_sum, drop_key)),
                    "delta_p95_latency_ms": float(_delta(sweep_base, v_sum, lat_key)),
                },
                "supported_by_trace_counters": bool(supported),
                "heuristic": {
                    "max_p95_latency_increase_frac": float(max_latency_increase_frac),
                    "max_p95_latency_increase_ms": float(max_latency_increase_ms),
                },
                "reason": str(reason),
            }
        else:
            evidence["expert_queueing"] = {"present": True, "note": "No scheduler variants produced comparable summaries."}

    if int(mtp_draft_len_out) <= 0:
        out["note"] = "Trace has no MTP counters; skipping mtp_off ablation."
        if any_dflash:
            cfg_no_mtp = dataclasses.replace(base_cfg, mtp_draft_len=0)
            base_trace = scheduler_sim.scale_trace_arrival_units(trace, "steps", cfg_no_mtp)
            base_metrics = scheduler_sim.run_simulation(cfg_no_mtp, base_trace)
            base_summary = scheduler_sim.compare_summary_jsonable(base_metrics)
            denom = float(base_summary.get("service_slot_ms_per_output_token", 0.0))
            numer = float(base_summary.get("dflash_service_slot_ms_per_output_token", 0.0))
            numer_adj = float(base_summary.get("dflash_service_slot_ms_per_output_token_adjusted", 0.0))
            ratio = (numer / denom) if denom > 0.0 and numer > 0.0 else 0.0
            ratio_adj = (numer_adj / denom) if denom > 0.0 and numer_adj > 0.0 else 0.0
            out["dflash_comparator"] = {
                "present": True,
                "note": "DFlash comparator metrics are kept separate from DeepSeek MTP. If dflash_draft_cost_scale is 0 or omitted, the adjusted comparator metrics equal the unadjusted values (treat as an optimistic upper bound).",
                "summary": base_summary,
                "service_slot_ms_per_output_token_ratio_vs_target_only": float(ratio),
                "service_slot_ms_per_output_token_ratio_vs_target_only_adjusted": float(ratio_adj),
            }
        out["evidence"] = evidence
        return(out)

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("mtp_off", {"mtp_draft_len": 0}),
        ("mtp_draft_queue_batch", {"mtp_draft_queue_cls": "batch"}),
    ]
    out["results"] = {
        "arrival_units_steps": scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants, arrival_units="steps"),
        "arrival_units_output_tokens": scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants, arrival_units="output_tokens"),
    }
    if any_dflash:
        mtp_off_summary = out["results"]["arrival_units_steps"]["variants"]["mtp_off"]["summary"]
        denom = float(mtp_off_summary.get("service_slot_ms_per_output_token", 0.0))
        numer = float(mtp_off_summary.get("dflash_service_slot_ms_per_output_token", 0.0))
        numer_adj = float(mtp_off_summary.get("dflash_service_slot_ms_per_output_token_adjusted", 0.0))
        ratio = (numer / denom) if denom > 0.0 and numer > 0.0 else 0.0
        ratio_adj = (numer_adj / denom) if denom > 0.0 and numer_adj > 0.0 else 0.0
        out["dflash_comparator"] = {
            "present": True,
            "note": "DFlash comparator metrics are kept separate from DeepSeek MTP. If dflash_draft_cost_scale is 0 or omitted, the adjusted comparator metrics equal the unadjusted values (treat as an optimistic upper bound).",
            "summary": mtp_off_summary,
            "service_slot_ms_per_output_token_ratio_vs_target_only": float(ratio),
            "service_slot_ms_per_output_token_ratio_vs_target_only_adjusted": float(ratio_adj),
        }

    # Evidence: whether the trace counters support enabling DeepSeek MTP in this regime.
    sweep_mtp = out["results"]["arrival_units_steps"]
    base_sum = _sweep_baseline_summary(sweep_mtp) if isinstance(sweep_mtp, dict) else {}
    off_sum = _sweep_variant_summary(sweep_mtp, "mtp_off") if isinstance(sweep_mtp, dict) else {}
    denom = _as_float(off_sum, "service_slot_ms_per_output_token")
    numer = _as_float(base_sum, "service_slot_ms_per_output_token")
    ratio = (numer / denom) if denom > 0.0 and numer > 0.0 else 0.0

    drop_key = _select_trace_metric(bool(has_interactive), bool(has_batch), "drop_frac_tokens_interactive", "drop_frac_tokens_batch", "drop_frac_tokens")
    lat_key = _select_trace_metric(
        bool(has_interactive),
        bool(has_batch),
        "output_token_p95_interactive_ms",
        "output_token_p95_batch_ms",
        "output_token_p95_batch_ms",
    )
    supported = False
    reason = "No mtp_off comparison available."
    if denom > 0.0:
        supported = bool(ratio > 0.0 and ratio < 1.0)
        dd = _delta(off_sum, base_sum, drop_key)
        dl = _delta(off_sum, base_sum, lat_key)
        reason = f"MTP appears efficiency-positive when service_slot_ms_per_output_token_ratio_vs_mtp_off < 1.0; observed ratio={ratio:.4f}, delta_drop={dd:+.4f} (metric={drop_key}), delta_p95_latency_ms={dl:+.3f} (metric={lat_key})."

    evidence["mtp"] = {
        "present": True,
        "mode": str(mtp_mode),
        "service_slot_ms_per_output_token_ratio_vs_mtp_off": float(ratio),
        "mtp_accept_rate": float(_as_float(base_sum, "mtp_accept_rate")),
        "mtp_mean_accept_len": float(_as_float(base_sum, "mtp_mean_accept_len")),
        "supported_by_trace_counters": bool(supported) if any_mtp else False,
        "supported_by_synthetic_model": bool(supported) if (not any_mtp and str(mtp_mode) == "synthetic") else False,
        "reason": str(reason) if any_mtp else f"Synthetic MTP model (no trace counters): {str(reason)}",
        "delta_vs_mtp_off": {
            str(drop_key): float(_delta(off_sum, base_sum, drop_key)),
            str(lat_key): float(_delta(off_sum, base_sum, lat_key)),
        },
    }

    q_sum = _sweep_variant_summary(sweep_mtp, "mtp_draft_queue_batch") if isinstance(sweep_mtp, dict) else {}
    if len(q_sum) != 0:
        verify_q_key = "task_queue_wait_ms_p95_mtp_verify"
        draft_q_key = "task_queue_wait_ms_p95_mtp_draft"
        dd = _delta(base_sum, q_sum, drop_key)
        dl = _delta(base_sum, q_sum, lat_key)
        dv = _delta(base_sum, q_sum, verify_q_key)
        ddraft = _delta(base_sum, q_sum, draft_q_key)
        supported_q = bool((dv < 0.0 or dl < 0.0) and dd <= 0.0)
        evidence["mtp_draft_queue_cls"] = {
            "present": True,
            "variant": "batch",
            "supported_by_trace_counters": bool(supported_q) if any_mtp else False,
            "supported_by_synthetic_model": bool(supported_q) if (not any_mtp and str(mtp_mode) == "synthetic") else False,
            "delta_vs_inherit": {
                str(drop_key): float(dd),
                str(lat_key): float(dl),
                str(verify_q_key): float(dv),
                str(draft_q_key): float(ddraft),
            },
            "reason": "Treat draft_queue_cls=batch as beneficial when it reduces verify queue wait or output-token p95 latency without increasing drop_frac_tokens.",
        }
    out["evidence"] = evidence

    return(out)


def _expert_queue_reserve_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 2000 if quick else 60000
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
    num_tokens = 1500 if quick else 25000
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
    num_tokens = 2000 if quick else 40000
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
    num_tokens = 1500 if quick else 30000
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
    num_tokens = 2000 if quick else 40000
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


def _mtp_accept_hist_shape_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 1500 if quick else 30000
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

    def _scale_trace_time(trace: List[scheduler_sim.TokenRoute], scale: float) -> List[scheduler_sim.TokenRoute]:
        if scale <= 0.0:
            raise ValueError("scale must be > 0")
        return([dataclasses.replace(r, t_ms=(float(r.t_ms) * float(scale))) for r in trace])

    no_mtp_metrics = scheduler_sim.run_simulation(dataclasses.replace(base_cfg, mtp_draft_len=0), base_trace)
    no_mtp_summary = scheduler_sim.compare_summary_jsonable(no_mtp_metrics)

    draft_len = 3
    hists: List[Tuple[str, Tuple[float, ...]]] = [
        ("uniform", (0.25, 0.25, 0.25, 0.25)),
        ("middle_heavy", (0.1, 0.4, 0.4, 0.1)),
        ("bimodal_extremes", (0.4, 0.1, 0.1, 0.4)),
    ]

    variants: List[Dict[str, Any]] = []
    for name, hist in hists:
        exp_len = scheduler_sim.expected_mtp_accept_len(
            draft_len,
            0.0,
            1.0,
            mtp_accept_model="hist",
            mtp_accept_hist=hist,
        )
        trace_scaled = _scale_trace_time(base_trace, float(exp_len))
        cfg = dataclasses.replace(
            base_cfg,
            mtp_draft_len=draft_len,
            mtp_accept_model="hist",
            mtp_accept_hist=hist,
            mtp_draft_cost_scale=0.25,
            mtp_draft_attempt_policy="stop_at_reject",
        )
        m = scheduler_sim.run_simulation(cfg, trace_scaled)
        s = scheduler_sim.compare_summary_jsonable(m)
        variants.append(
            {
                "name": str(name),
                "mtp_accept_hist": list(hist),
                "expected_accept_len": float(exp_len),
                "trace_time_scale": float(exp_len),
                "no_mtp": no_mtp_summary,
                "mtp_hist": s,
            }
        )

    return(
        {
            "name": "mtp_accept_hist_shape",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "draft_len": int(draft_len),
            "variants": variants,
            "recommendation": {
                "note": "All variants share the same mean accept_len (=2.5) but different shape/variance; if real traces show a heavy tail of short accepts, expect worse queue pressure than mean-only geom fits suggest.",
                "default_accept_model": "geom",
                "enable_hist_when_available": True,
                "reason": "Synthetic overload: accept-length distribution shape (not just mean accept rate) can materially change queue pressure and SLA safety; prefer replaying empirical accept_len histograms once real quantized-runtime traces provide them.",
            },
        }
    )


def _k_signal_policy_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 2000 if quick else 60000
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
    num_tokens = 2000 if quick else 60000
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
    num_tokens = 2000 if quick else 40000
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


def _k_controller_smoothing_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 2000 if quick else 60000
    trace_cfg = scheduler_sim.TwoStreamTraceConfig(
        num_tokens=num_tokens,
        num_experts=16,
        num_candidates=4,
        interactive_arrival_rate_tps=1500.0,
        batch_arrival_rate_tps=3000.0,
        interactive_burst_prob=0.05,
        interactive_burst_scale=50.0,
        batch_burst_prob=0.05,
        batch_burst_scale=50.0,
        zipf_alpha=1.1,
        seed=123,
    )
    trace = scheduler_sim.generate_twostream_trace(trace_cfg)

    base_cfg = scheduler_sim.SimConfig(
        num_experts=trace_cfg.num_experts,
        expert_parallelism=1,
        expert_queue_max=512,
        service_ms=1.0,
        starvation_ms=100.0,
        hi_burst=0,
        promote_ms=0.0,
        adaptive_k=scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=4,
            q_low=32,
            q_high=256,
            ema_alpha=1.0,
            update_ms=0.0,
            k_slew=0,
        ),
        expert_queue_reserve_interactive=16,
        k_signal="global",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("smooth_ema_0p2_slew1", {"adaptive_k.ema_alpha": 0.2, "adaptive_k.update_ms": 0.0, "adaptive_k.k_slew": 1}),
        ("smooth_ema_0p2_update_2ms_slew1", {"adaptive_k.ema_alpha": 0.2, "adaptive_k.update_ms": 2.0, "adaptive_k.k_slew": 1}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "k_controller_smoothing",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "support_k_smoothing_knobs": True,
                "default_ema_alpha": 0.2,
                "default_update_ms": 2.0,
                "default_k_slew": 1,
                "reason": "Synthetic bursty overload: smoothing the congestion signal (EMA) and rate-limiting/slewing K updates reduces controller churn; calibrate these knobs against real quantized-runtime traces before baking them into runtime defaults.",
            },
        }
    )


def _backpressure_zero_admit_policy_scenario(quick: bool) -> Dict[str, Any]:
    num_tokens = 2000 if quick else 40000
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
            k_min_batch=2,
            k_max_batch=2,
            q_low=0,
            q_high=0,
        ),
        expert_queue_reserve_interactive=16,
        k_signal="class",
        sla_interactive_ms=25.0,
        sla_batch_ms=250.0,
        sim_seed=123,
        backpressure_zero_admit_policy="skip",
    )

    variants: List[Tuple[str, Dict[str, object]]] = [
        ("stall", {"backpressure_zero_admit_policy": "stall"}),
    ]

    out = scheduler_sim.compare_simulation_summaries(base_cfg, trace, variants)
    return(
        {
            "name": "backpressure_zero_admit_policy",
            "trace_cfg": dataclasses.asdict(trace_cfg),
            "base_cfg": dataclasses.asdict(base_cfg),
            "results": out,
            "recommendation": {
                "default_policy": "skip",
                "experimental_policy": "stall",
                "reason": "Synthetic saturation: stalling avoids token drops when all candidates are saturated, but it can sharply increase latency/makespan; treat stall as an upstream-queueing mode to evaluate on real traces before adopting in runtime.",
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
        "mtp_accept_hist_shape": _mtp_accept_hist_shape_scenario(quick),
        "k_signal_policy": _k_signal_policy_scenario(quick),
        "batch_starvation_knobs": _batch_starvation_knobs_scenario(quick),
        "backpressure_units": _backpressure_units_scenario(quick),
        "backpressure_zero_admit_policy": _backpressure_zero_admit_policy_scenario(quick),
        "k_controller_smoothing": _k_controller_smoothing_scenario(quick),
    }
    return({"scenarios": scenarios})


def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scheduler simulator recommendation harness (synthetic scenarios, plus optional runtime-trace MTP ablation).")
    p.add_argument("--json", action="store_true", help="Print JSON only (default).")
    p.add_argument("--format", type=str, default="json", choices=("json", "md"), help="Output format for runtime-trace ablation mode: json (default) or md.")
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
    p.add_argument(
        "--trace-pack-layers-by-token-index",
        type=int,
        default=0,
        help="Trace replay helper: pack per-layer runtime route records that share token_index into a single multi-layer trace record (layers[]) before parsing.",
    )
    p.add_argument("--trace-pack-require-layer-index", type=int, default=0, help="When packing per-layer records, require every record to include layer_index (default: 0).")
    p.add_argument("--trace-time-mode", type=str, default="t_ms", help="Trace time field mode: t_ms (default) or dt_ms.")
    p.add_argument("--max-tokens", type=int, default=0, help="Optional cap on number of trace records to read (0 = no cap).")
    p.add_argument("--trace-derive-cost-scale", type=str, default="none", choices=("none", "kv_tokens_p50", "decode_ms_p50"))
    p.add_argument("--trace-speedup", type=float, default=1.0, help="Scale trace time by 1/speedup (>= 1 makes arrivals faster).")
    p.add_argument("--expert-queue-max", type=int, default=128)
    p.add_argument("--expert-parallelism", type=int, default=1)
    p.add_argument("--service-ms", type=float, default=1.0)
    p.add_argument("--starvation-ms", type=float, default=50.0)
    p.add_argument("--mtp-draft-len", type=int, default=-1, help="Optional: enable synthetic MTP ablation when the trace has no MTP counters (>=1), or override inferred draft length (-1 = infer when present, else disabled).")
    p.add_argument("--mtp-accept-model", type=str, default="geom", choices=("geom", "hist"))
    p.add_argument("--mtp-accept-hist", type=str, default="", help="When --mtp-accept-model=hist, comma-separated probabilities for accept_len=1..draft_len+1.")
    p.add_argument("--mtp-accept-prob", type=float, default=0.0)
    p.add_argument("--mtp-accept-decay", type=float, default=1.0)
    p.add_argument("--mtp-draft-cost-scale", type=float, default=0.25)
    p.add_argument("--mtp-verify-per-draft-cost-scale", type=float, default=0.0)
    p.add_argument(
        "--mtp-draft-attempt-policy",
        type=str,
        default="full",
        choices=("full", "stop_at_reject", "trace"),
        help="MTP: draft compute policy: full, stop_at_reject, or trace (use accepted_mtp+rejected_mtp when present).",
    )
    p.add_argument("--dflash-draft-len", type=int, default=-1, help="Optional: override/inject meta.dflash_draft_len for runtime-trace comparator accounting (-1 = keep/infer).")
    p.add_argument("--dflash-draft-cost-scale", type=float, default=-1.0, help="Optional: draft-cost multiplier for the speculative-decoding comparator (-1 = use meta if present, 0 = disable overhead adjustment).")
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
            pack_layers_by_token_index=(int(args.trace_pack_layers_by_token_index) != 0),
            pack_require_layer_index=(int(args.trace_pack_require_layer_index) != 0),
        )
        if int(args.max_tokens) > 0:
            trace = list(trace[: int(args.max_tokens)])
        dflash_cost_scale: Optional[float] = None
        if float(args.dflash_draft_cost_scale) >= 0.0:
            dflash_cost_scale = float(args.dflash_draft_cost_scale)
        mtp_hist: List[float] = []
        if str(args.mtp_accept_hist).strip() != "":
            for tok in str(args.mtp_accept_hist).split(","):
                tok = tok.strip()
                if tok == "":
                    continue
                mtp_hist.append(float(tok))
        out = run_runtime_trace_mtp_ablation(
            trace=trace,
            trace_meta=meta,
            expert_queue_max=int(args.expert_queue_max),
            expert_parallelism=int(args.expert_parallelism),
            service_ms=float(args.service_ms),
            starvation_ms=float(args.starvation_ms),
            trace_derive_cost_scale=str(args.trace_derive_cost_scale),
            trace_speedup=float(args.trace_speedup),
            mtp_draft_len=int(args.mtp_draft_len),
            mtp_accept_model=str(args.mtp_accept_model),
            mtp_accept_hist=mtp_hist,
            mtp_accept_prob=float(args.mtp_accept_prob),
            mtp_accept_decay=float(args.mtp_accept_decay),
            mtp_draft_cost_scale=float(args.mtp_draft_cost_scale),
            mtp_verify_per_draft_cost_scale=float(args.mtp_verify_per_draft_cost_scale),
            mtp_draft_attempt_policy=str(args.mtp_draft_attempt_policy),
            dflash_draft_len=int(args.dflash_draft_len),
            dflash_draft_cost_scale=dflash_cost_scale,
        )
    else:
        out = run_recommendations(quick=bool(args.quick))
    if str(args.format).strip().lower() == "md":
        if args.trace_jsonl.strip() == "":
            raise SystemExit("--format md is supported only with --trace-jsonl (runtime-trace ablation mode).")
        print(format_runtime_trace_ablation_markdown(out))
        return(0)
    print(json.dumps(out, sort_keys=True))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
