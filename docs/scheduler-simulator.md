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
- If no expert tasks can be admitted for a token because all candidates are full, the token is counted as dropped by backpressure.
- Each expert is a small server with:
  - fixed parallelism (`--expert-parallelism`)
  - two FIFO queues (interactive first, then batch)
  - fixed service time per task (`--service-ms`)

Starvation is counted when a task waits in an expert queue for at least
`--starvation-ms` before it starts service.

### Candidate Admission Policy

When `K < len(candidates)`, the simulator must pick which experts receive tasks.
Two policies are supported:

- `--admit-policy ordered` (default): admit in router-provided order
- `--admit-policy least_pending`: admit the least-pending experts among the candidates (ties broken by router order)

### Per-Expert Service Discipline

By default experts serve interactive tasks before batch tasks (strict priority).
Two optional knobs let us explore fairness / anti-starvation strategies:

- `--hi-burst N`: after starting `N` interactive tasks consecutively on an expert,
  the simulator forces one batch task start if any batch tasks are queued
  (`0` keeps strict priority).
- `--promote-ms T`: if a batch task waits at least `T` ms in the batch queue,
  it is promoted into the interactive queue (`0` disables aging).

## Adaptive K

`K` is chosen independently for interactive and batch tokens based on a
congestion signal derived from expert pending depth:

- `--k-signal global` (default): `max_pending` is max pending across all experts
- `--k-signal candidates`: `max_pending` is max pending among this token's candidates

Then:

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

### Synthetic Trace Modes

Default synthetic mode is Zipf-skewed expert popularity:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode zipf --zipf-alpha 1.1 --json
```

Hotset mode creates a small moving set of "hot" experts (router candidates are biased toward the hotset),
which is useful for stress-testing backpressure, queue depth, and adaptive-K oscillations:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode hotset --hotset-size 8 --hotset-bias 0.9 --hotset-rotate-every-tokens 2000 --json
```

### Trace Replay (JSONL)

Replay mode reads one JSON object per line with required fields:

- `t_ms` (number): arrival time in milliseconds
- `cls` (`"interactive"` or `"batch"`)
- `candidates` (list[int]): ordered expert candidates
- `scores` (optional list[number]): per-candidate router scores (same length as `candidates`)

Example:

```bash
cat > /tmp/route.jsonl <<'EOF'
{"t_ms":0.0,"cls":"interactive","candidates":[3,7,1,0]}
{"t_ms":0.2,"cls":"batch","candidates":[7,2,3,5]}
EOF
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.jsonl --num-experts 8 --json
```

## Metrics

The simulator prints a JSON object with:

- `sim`: makespan + token/task throughput
- `token_latency_ms.{interactive,batch}`: count/mean/p50/p95/p99/max (admitted tokens only)
- `tokens`: token-level admitted vs dropped-by-backpressure counts
- `task_queue_wait_ms.{interactive,batch}`: queue wait before service starts (count/mean/p50/p95/p99/max)
- `chosen_k.{interactive,batch}`: mean/min/max (over tokens)
- `tasks`: total + per-latency-class admitted/dropped/starved counters
- `tasks.promoted`: number of batch tasks promoted by `--promote-ms`
- `tasks.forced_batch_starts`: number of times `--hi-burst` forced a batch start
- `expert_queue`: median/max of per-expert max-pending and mean-pending
- `expert_utilization`: median/p95/max of per-expert mean utilization (time-weighted `in_flight / expert_parallelism`)
- `expert_saturation`: median/p95/max of per-expert fraction of time pending at `--expert-queue-max`

## Next Steps

- Add a trace replay mode that reads real router outputs (when available).
- Replace fixed `--service-ms` with a shape-dependent service model once DS4
  expert GEMM shapes are pinned down.
- Use this harness to define production invariants (interactive p95 bounds,
  max starvation rate, acceptable drop rate) before CUDA integration.
