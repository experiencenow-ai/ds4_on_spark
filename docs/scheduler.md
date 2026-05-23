# Scheduler

> Supersedes: `docs/scheduler-simulator.md`, `docs/scheduler-simulator-recommendations.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 2 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `scheduler-simulator.md`: Scheduler Simulator (Host-Only) (723 lines).
- `scheduler-simulator-recommendations.md`: Scheduler Simulator Recommendations (Synthetic) (321 lines).

## Command Inventory

- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --k-mode trace --json`
- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --json > /tmp/sched_metrics.json`
- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --num-tokens 200000 --arrival-rate-tps 8000`
- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --summary-json`
- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --summary-json --compare 'mtp_off:{"mtp_draft_len":0}'`
- `scheduler-simulator.md`: `python3 sim/scheduler/trace_sweep.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --num-experts 0 --max-tokens 5000`
- `scheduler-simulator.md`: `python3 sim/scheduler/trace_sweep.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-arrival-units output_tokens --mtp-draft-len 2 --mtp-accept-prob 0.7 --mtp-accept-decay 0.6 --num-experts 0 --max-tokens 5000`
- `scheduler-simulator.md`: `python3 sim/scheduler/trace_sweep.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-default-cls batch --num-experts 0 --max-tokens 5000`
- `scheduler-simulator.md`: `python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --mtp-draft-len 2 --mtp-accept-prob 0.7 --mtp-accept-decay 0.6`
- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --num-tokens 20000 --arrival-units output_tokens --arrival-rate-tps 8000 --mtp-draft-len 2 --mtp-accept-prob 0.7 --mtp-accept-decay 0.6 --json --compare 'mtp_off:{"mtp_draft_len":0}'`
- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --summary-json --dump-sim-jsonl '/tmp/sim_{label}.jsonl' --compare 'reserve:{"expert_queue_reserve_interactive":16}' --compare 'no_reserve:{"expert_queue_reserve_interactive":0}'`
- `scheduler-simulator.md`: `python3 sim/scheduler/scheduler_sim.py --batch-max-batch 8 --service-base-ms 0.05 --service-per-task-ms 0.02 --json`
- `scheduler-simulator-recommendations.md`: `python3 sim/scheduler/recommendations.py --json > docs/scheduler-simulator-recommendations-2026-05-13.json`
- `scheduler-simulator-recommendations.md`: `python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --summary-json`
- `scheduler-simulator-recommendations.md`: `python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip > /tmp/runtime_mtp_ablation.json`
- `scheduler-simulator-recommendations.md`: `python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-derive-cost-scale kv_tokens_p50`
- `scheduler-simulator-recommendations.md`: `python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --dflash-draft-cost-scale 0.25`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/scheduler-simulator.md` | 723 | Scheduler Simulator (Host-Only) | Model, Adaptive K, MTP (Draft/Accept) Model, Running, Metrics |
| `docs/scheduler-simulator-recommendations.md` | 321 | Scheduler Simulator Recommendations (Synthetic) | Expert Queue Reservation, Backpressure Units (Tasks vs Work), Backpressure Zero-Admit Policy (Skip vs Stall), Expert Batching (Per-Expert Microbatching), MTP (Draft/Accept) Efficiency Threshold |
