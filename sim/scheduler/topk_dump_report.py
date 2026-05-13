from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from sim.scheduler import ds4_topk_dump
from sim.scheduler import recommendations
from sim.scheduler import scheduler_sim


def build_ds4_topk_dump_trace_report_bundle(
    dump_dir: str,
    *,
    out_dir: str,
    pos: int = 0,
    topk: int = 6,
    num_tokens: int = 0,
    seed: int = 1,
    sample_mode: str = "sequential",
    time_mode: str = "dt_ms",
    arrival_rate_tps: float = 1000.0,
    batch_size: int = 1,
    interactive_prob: float = 0.0,
    trace_speedup: float = 1.0,
    expert_queue_max: int = 128,
    expert_parallelism: int = 1,
    service_ms: float = 1.0,
    starvation_ms: float = 50.0,
    mtp_draft_len: int = -1,
    mtp_accept_prob: float = 0.0,
    mtp_accept_decay: float = 1.0,
    mtp_draft_cost_scale: float = 0.25,
    probe_expert_queueing: bool = False,
    probe_experts: int = 256,
    probe_batches: Tuple[int, ...] = (16, 32, 64, 100, 128, 256, 512),
    probe_trials: int = 250,
    overwrite: bool = False,
) -> Dict[str, object]:
    """
    Build a small on-disk bundle from a DS4 antirez `ffn_moe_topk` dump dir:

      - `trace.strict.jsonl`: strict scheduler-sim trace (synthetic time)
      - `report.json`: scheduler-simulator ablation report (JSON)
      - `report.md`: markdown rendering of the same report
      - `bundle_meta.json`: inputs + derived DS4 dump meta

    The underlying routes are real; timing (`t_ms`/`dt_ms`) is synthetic.
    """
    out_root = Path(str(out_dir))
    if out_root.exists():
        if overwrite is False:
            raise FileExistsError(f"bundle out_dir already exists: {out_root}")
        if out_root.is_dir() is False:
            raise ValueError(f"bundle out_dir must be a directory: {out_root}")
    out_root.mkdir(parents=True, exist_ok=True)

    trace_path = out_root / "trace.strict.jsonl"
    report_json_path = out_root / "report.json"
    report_md_path = out_root / "report.md"
    meta_path = out_root / "bundle_meta.json"

    meta, layers = ds4_topk_dump.load_ds4_ffn_moe_topk_dump_layers(
        str(dump_dir),
        pos=int(pos),
        topk=int(topk),
    )

    topk_dump_probe: Dict[str, object] = {}
    if bool(probe_expert_queueing):
        topk_dump_probe = ds4_topk_dump.probe_expert_queueing_from_ds4_topk_dump_layers(
            layers,
            experts=int(probe_experts),
            topk=int(topk),
            batches=tuple(int(b) for b in probe_batches),
            trials=int(probe_trials),
            seed=int(seed),
            strict_expert_ids=True,
        )

    ds4_topk_dump.build_scheduler_trace_jsonl_from_ds4_topk_dump(
        meta,
        layers,
        out_path=str(trace_path),
        num_tokens=int(num_tokens),
        seed=int(seed),
        sample_mode=str(sample_mode),
        time_mode=str(time_mode),
        arrival_rate_tps=float(arrival_rate_tps),
        batch_size=int(batch_size),
        interactive_prob=float(interactive_prob),
    )

    trace_meta: Dict[str, object] = {}
    trace = scheduler_sim.load_trace_jsonl(
        str(trace_path),
        time_mode=str(time_mode),
        meta_out=trace_meta,
        non_route_policy="error",
        input_format="strict",
    )

    report = recommendations.run_runtime_trace_mtp_ablation(
        name="ds4_topk_dump_route_only_ablation",
        trace=trace,
        trace_meta=trace_meta,
        expert_queue_max=int(expert_queue_max),
        expert_parallelism=int(expert_parallelism),
        service_ms=float(service_ms),
        starvation_ms=float(starvation_ms),
        trace_speedup=float(trace_speedup),
        mtp_draft_len=int(mtp_draft_len),
        mtp_accept_prob=float(mtp_accept_prob),
        mtp_accept_decay=float(mtp_accept_decay),
        mtp_draft_cost_scale=float(mtp_draft_cost_scale),
    )
    if len(topk_dump_probe) != 0:
        report["topk_dump_probe"] = {
            "present": True,
            "note": "Probe uses real routes from the topk dumps but resamples rows and assumes synthetic batch sizes; this is not a full decode replay.",
            "summary": topk_dump_probe,
        }

    report_json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md_path.write_text(recommendations.format_runtime_trace_ablation_markdown(report) + "\n", encoding="utf-8")

    bundle_meta: Dict[str, object] = {
        "type": "ds4_topk_dump_trace_report_bundle",
        "cwd": os.getcwd(),
        "dump_dir": str(dump_dir),
        "dump_meta": {
            "dump_dir": str(meta.dump_dir),
            "pos": int(meta.pos),
            "topk": int(meta.topk),
            "num_layers": int(meta.num_layers),
            "tokens_per_layer": int(meta.tokens_per_layer),
        },
        "bundle": {
            "trace": str(trace_path.name),
            "report_json": str(report_json_path.name),
            "report_md": str(report_md_path.name),
        },
        "note": "Routes are real DS4 ffn_moe_topk dumps; time is synthetic.",
        "args": {
            "pos": int(pos),
            "topk": int(topk),
            "num_tokens": int(num_tokens),
            "seed": int(seed),
            "sample_mode": str(sample_mode),
            "time_mode": str(time_mode),
            "arrival_rate_tps": float(arrival_rate_tps),
            "batch_size": int(batch_size),
            "interactive_prob": float(interactive_prob),
            "trace_speedup": float(trace_speedup),
            "expert_queue_max": int(expert_queue_max),
            "expert_parallelism": int(expert_parallelism),
            "service_ms": float(service_ms),
            "starvation_ms": float(starvation_ms),
            "mtp_draft_len": int(mtp_draft_len),
            "mtp_accept_prob": float(mtp_accept_prob),
            "mtp_accept_decay": float(mtp_accept_decay),
            "mtp_draft_cost_scale": float(mtp_draft_cost_scale),
            "probe_expert_queueing": bool(probe_expert_queueing),
            "probe_experts": int(probe_experts),
            "probe_batches": [int(b) for b in probe_batches],
            "probe_trials": int(probe_trials),
        },
    }
    meta_path.write_text(json.dumps(bundle_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return(
        {
            "out_dir": str(out_root),
            "trace_path": str(trace_path),
            "report_json_path": str(report_json_path),
            "report_md_path": str(report_md_path),
            "bundle_meta_path": str(meta_path),
            "report": report,
        }
    )

