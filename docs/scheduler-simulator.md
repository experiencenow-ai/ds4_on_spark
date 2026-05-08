# Scheduler Simulator (Host-Only)

This repo is not ready for CUDA scheduler integration yet. This simulator is a
host-only harness that exercises continuous batching / MoE-style routing
policies on synthetic routing traces so we can:

- reason about **adaptive K** behavior under congestion
- measure **expert queue depth**, **backpressure drops**, and **starvation**
- separate **latency classes** (interactive vs batch)
- produce **concise metrics** that can guide the eventual CUDA design

## Model

Work units:

- A *token* arrives at time `t_ms` with a latency class.
- The router provides an ordered list of candidate experts.
- The scheduler chooses `K` (adaptive) and admits up to `K` expert tasks, skipping experts that are at `--expert-queue-max` (backpressure).
- Each expert is a small server with:
  - fixed parallelism (`--expert-parallelism`)
  - two FIFO queues (interactive first, then batch)
  - fixed service time per task (`--service-ms`)

Starvation is counted when a task waits in an expert queue for at least
`--starvation-ms` before it starts service.

## Adaptive K

`K` is chosen independently for interactive and batch tokens based on the
current worst-case expert pending depth:

- if `max_pending <= --q-low` then `K = K_max`
- if `max_pending >= --q-high` then `K = K_min`
- otherwise linearly interpolate between `K_max` and `K_min`

This is intentionally simple; it is meant to generate stable, testable behavior
and highlight oscillation or starvation regimes early.

## Running

```bash
python3 sim/scheduler/scheduler_sim.py --json > /tmp/sched_metrics.json
python3 sim/scheduler/scheduler_sim.py --num-tokens 200000 --arrival-rate-tps 8000
```

## Metrics

The simulator prints a JSON object with:

- `token_latency_ms.{interactive,batch}`: count/mean/p50/p95/p99/max
- `chosen_k.{interactive,batch}`: mean/min/max (over tokens)
- `tasks.{admitted,dropped_backpressure,starved}`
- `expert_queue`: median/max of per-expert max-pending and mean-pending

## Next Steps

- Add a trace replay mode that reads real router outputs (when available).
- Replace fixed `--service-ms` with a shape-dependent service model once DS4
  expert GEMM shapes are pinned down.
- Use this harness to define production invariants (interactive p95 bounds,
  max starvation rate, acceptable drop rate) before CUDA integration.

