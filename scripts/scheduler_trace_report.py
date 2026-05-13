#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.scheduler import trace_report  # noqa: E402


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bundle a scheduler-simulator runtime trace report (canonical trace JSONL + runtime-trace MTP/expert-queue ablation report)."
    )
    p.add_argument("--in-jsonl", required=True, help="Input JSONL stream (can include mixed logs; runtime format supported). Use '-' for stdin.")
    p.add_argument("--out-dir", required=True, help="Output directory (created if missing).")
    p.add_argument("--time-mode", default="dt_ms", choices=("t_ms", "dt_ms"))
    p.add_argument("--input-format", default="runtime", choices=("runtime", "strict"))
    p.add_argument("--non-route", default="skip", choices=("skip", "error"))
    p.add_argument("--default-cls", default="", help="Force a default latency class (interactive/batch) when missing.")
    p.add_argument("--route-type", default="", help="Optional route type hint for runtime extraction.")
    p.add_argument("--pack-layers-by-token-index", type=int, default=0, help="Pack per-layer records into layers[] by token_index.")
    p.add_argument("--pack-require-layer-index", type=int, default=0, help="Require layer_index when packing layers.")
    p.add_argument("--pack-time-policy", default="strict", choices=("strict", "first", "min", "max"))
    p.add_argument("--pack-time-tol-ms", type=float, default=0.0)
    p.add_argument("--max-tokens", type=int, default=0, help="Optional max number of trace records to load (0 = all).")

    p.add_argument("--expert-queue-max", type=int, default=128)
    p.add_argument("--expert-parallelism", type=int, default=1)
    p.add_argument("--service-ms", type=float, default=1.0)
    p.add_argument("--batch-max-interactive", type=int, default=1)
    p.add_argument("--batch-max-batch", type=int, default=1)
    p.add_argument("--batch-wait-interactive-ms", type=float, default=0.0)
    p.add_argument("--batch-wait-batch-ms", type=float, default=0.0)
    p.add_argument("--service-base-ms", type=float, default=0.0)
    p.add_argument("--service-per-task-ms", type=float, default=-1.0)
    p.add_argument("--starvation-ms", type=float, default=50.0)
    p.add_argument("--trace-derive-cost-scale", type=str, default="none", help="Optional: derive cost_scale from trace fields (e.g., kv_tokens_p50).")
    p.add_argument("--trace-speedup", type=float, default=1.0, help="Optional: divide trace time deltas by this factor (>0).")
    p.add_argument("--mtp-draft-len", type=int, default=-1, help="Override/inject mtp_draft_len (-1 = infer when present, else disabled).")
    p.add_argument("--mtp-accept-model", type=str, default="geom", choices=("geom", "hist"))
    p.add_argument("--mtp-accept-hist", type=str, default="", help="When mtp_accept_model=hist, comma-separated accept_len probs.")
    p.add_argument("--mtp-accept-prob", type=float, default=0.0)
    p.add_argument("--mtp-accept-decay", type=float, default=1.0)
    p.add_argument("--mtp-draft-cost-scale", type=float, default=0.25)
    p.add_argument("--mtp-verify-per-draft-cost-scale", type=float, default=0.0)
    p.add_argument("--mtp-draft-attempt-policy", type=str, default="full", choices=("full", "stop_at_reject", "trace"))
    p.add_argument("--dflash-draft-len", type=int, default=-1)
    p.add_argument("--dflash-draft-cost-scale", type=float, default=-1.0, help="Draft-cost multiplier for the DFlash comparator (-1 = meta/infer).")
    return(p.parse_args(argv))


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    mtp_hist = []
    if str(args.mtp_accept_hist).strip() != "":
        for tok in str(args.mtp_accept_hist).split(","):
            tok = tok.strip()
            if tok == "":
                continue
            mtp_hist.append(float(tok))
    dflash_cost_scale = None
    if float(args.dflash_draft_cost_scale) >= 0.0:
        dflash_cost_scale = float(args.dflash_draft_cost_scale)

    bundle = trace_report.build_runtime_trace_report_bundle(
        in_jsonl=str(args.in_jsonl),
        out_dir=str(args.out_dir),
        time_mode=str(args.time_mode),
        input_format=str(args.input_format),
        non_route_policy=str(args.non_route),
        default_cls=str(args.default_cls),
        route_type=str(args.route_type),
        pack_layers_by_token_index=(int(args.pack_layers_by_token_index) != 0),
        pack_require_layer_index=(int(args.pack_require_layer_index) != 0),
        pack_time_policy=str(args.pack_time_policy),
        pack_time_tol_ms=float(args.pack_time_tol_ms),
        max_tokens=int(args.max_tokens),
        expert_queue_max=int(args.expert_queue_max),
        expert_parallelism=int(args.expert_parallelism),
        service_ms=float(args.service_ms),
        batch_max_interactive=int(args.batch_max_interactive),
        batch_max_batch=int(args.batch_max_batch),
        batch_wait_interactive_ms=float(args.batch_wait_interactive_ms),
        batch_wait_batch_ms=float(args.batch_wait_batch_ms),
        service_base_ms=float(args.service_base_ms),
        service_per_task_ms=float(args.service_per_task_ms),
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

    print(f"ok: wrote bundle to {bundle.paths.out_dir}")
    print(f"- canonical trace: {bundle.paths.canonical_trace_jsonl}")
    print(f"- report json: {bundle.paths.report_json}")
    print(f"- report md: {bundle.paths.report_md}")
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())

