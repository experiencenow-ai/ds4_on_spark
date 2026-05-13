from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from sim.scheduler import recommendations
from sim.scheduler import scheduler_sim


@dataclass(frozen=True)
class RuntimeTraceReportPaths:
    out_dir: str
    canonical_trace_jsonl: str
    report_json: str
    report_md: str


@dataclass(frozen=True)
class RuntimeTraceReportBundle:
    paths: RuntimeTraceReportPaths
    trace_meta: Dict[str, object]
    report: Dict[str, Any]


def build_runtime_trace_report_bundle(
    *,
    in_jsonl: str,
    out_dir: str,
    time_mode: str = "dt_ms",
    input_format: str = "runtime",
    non_route_policy: str = "skip",
    default_cls: str = "",
    route_type: str = "",
    pack_layers_by_token_index: bool = False,
    pack_require_layer_index: bool = False,
    pack_time_policy: str = "strict",
    pack_time_tol_ms: float = 0.0,
    max_tokens: int = 0,
    expert_queue_max: int = 128,
    expert_parallelism: int = 1,
    service_ms: float = 1.0,
    batch_max_interactive: int = 1,
    batch_max_batch: int = 1,
    batch_wait_interactive_ms: float = 0.0,
    batch_wait_batch_ms: float = 0.0,
    service_base_ms: float = 0.0,
    service_per_task_ms: float = -1.0,
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
) -> RuntimeTraceReportBundle:
    if str(in_jsonl).strip() == "":
        raise ValueError("in_jsonl must be non-empty")
    if str(out_dir).strip() == "":
        raise ValueError("out_dir must be non-empty")

    out_dir_abs = os.path.abspath(str(out_dir))
    os.makedirs(out_dir_abs, exist_ok=True)

    trace_meta: Dict[str, object] = {}
    trace = scheduler_sim.load_trace_jsonl(
        str(in_jsonl),
        time_mode=str(time_mode).strip().lower(),
        meta_out=trace_meta,
        non_route_policy=str(non_route_policy).strip().lower(),
        input_format=str(input_format).strip().lower(),
        route_type=str(route_type).strip(),
        default_cls=str(default_cls).strip(),
        pack_layers_by_token_index=bool(pack_layers_by_token_index),
        pack_require_layer_index=bool(pack_require_layer_index),
        pack_time_policy=str(pack_time_policy).strip().lower(),
        pack_time_tol_ms=float(pack_time_tol_ms),
    )
    if int(max_tokens) > 0:
        trace = list(trace[: int(max_tokens)])

    canonical_trace_jsonl = os.path.join(out_dir_abs, "scheduler_trace.canon.jsonl")
    scheduler_sim.write_trace_jsonl_canonical(canonical_trace_jsonl, trace, meta=trace_meta)

    report = recommendations.run_runtime_trace_mtp_ablation(
        name="runtime_trace_bundle",
        trace=trace,
        trace_meta=trace_meta,
        expert_queue_max=int(expert_queue_max),
        expert_parallelism=int(expert_parallelism),
        service_ms=float(service_ms),
        batch_max_interactive=int(batch_max_interactive),
        batch_max_batch=int(batch_max_batch),
        batch_wait_interactive_ms=float(batch_wait_interactive_ms),
        batch_wait_batch_ms=float(batch_wait_batch_ms),
        service_base_ms=float(service_base_ms),
        service_per_task_ms=float(service_per_task_ms),
        starvation_ms=float(starvation_ms),
        trace_derive_cost_scale=str(trace_derive_cost_scale),
        trace_speedup=float(trace_speedup),
        mtp_draft_len=int(mtp_draft_len),
        mtp_accept_model=str(mtp_accept_model),
        mtp_accept_hist=tuple(float(x) for x in mtp_accept_hist),
        mtp_accept_prob=float(mtp_accept_prob),
        mtp_accept_decay=float(mtp_accept_decay),
        mtp_draft_cost_scale=float(mtp_draft_cost_scale),
        mtp_verify_per_draft_cost_scale=float(mtp_verify_per_draft_cost_scale),
        mtp_draft_attempt_policy=str(mtp_draft_attempt_policy),
        dflash_draft_len=int(dflash_draft_len),
        dflash_draft_cost_scale=dflash_draft_cost_scale,
    )

    report_json = os.path.join(out_dir_abs, "scheduler_trace_report.json")
    with open(report_json, "w", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2, sort_keys=True))
        f.write("\n")

    report_md = os.path.join(out_dir_abs, "scheduler_trace_report.md")
    with open(report_md, "w", encoding="utf-8") as f:
        f.write(recommendations.format_runtime_trace_ablation_markdown(report))
        f.write("\n")

    paths = RuntimeTraceReportPaths(
        out_dir=out_dir_abs,
        canonical_trace_jsonl=canonical_trace_jsonl,
        report_json=report_json,
        report_md=report_md,
    )
    return(RuntimeTraceReportBundle(paths=paths, trace_meta=trace_meta, report=report))

