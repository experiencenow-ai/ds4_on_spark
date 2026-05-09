# Scheduler Simulator (Host-Only)

This repo is not ready for CUDA scheduler integration yet. This simulator is a
host-only harness that exercises continuous batching / MoE-style routing
policies on synthetic routing traces so we can:

- reason about **adaptive K** behavior under congestion
- measure **expert queue depth**, **backpressure drops**, and **starvation**
- separate **latency classes** (interactive vs batch)
- produce **concise metrics** that can guide the eventual CUDA design

The quantized runtime path changes the priority: as soon as Spark0 can generate
tokens with a V4-capable quantized runtime, this simulator should ingest real
route traces from that runtime and decide whether expert queueing and MTP are
worth patching into the working path.

## Model

Work units:

- A *token* arrives at time `t_ms` with a latency class.
- The router provides an ordered list of candidate experts.
- The scheduler chooses `K` (adaptive) and admits up to `K` expert tasks, skipping experts that are at `--expert-queue-max` (backpressure).
- If no expert tasks can be admitted for a token because all candidates are full, the token is counted as dropped by backpressure.
- Each expert is a small server with:
  - fixed parallelism (`--expert-parallelism`)
  - two FIFO queues (interactive first, then batch)
  - a simple service model:
    - default (no batching): fixed service time per task (`--service-ms`)
    - optional batching: start up to `--batch-max-{interactive,batch}` tasks at once on an expert worker, with service time
      `--service-base-ms + --service-per-task-ms * batch_size` (when `--service-per-task-ms=-1`, it uses `--service-ms`)
    - optional batching window: when an expert worker is idle and the chosen queue has fewer than `--batch-max-*` tasks,
      delay starting the batch until the oldest queued task has waited `--batch-wait-*-ms` (or until the batch fills)

Starvation is counted when a task waits in an expert queue for at least
`--starvation-ms` before it starts service.

Backpressure (`--expert-queue-max`) is applied to **total outstanding tasks per expert**:
queued tasks plus tasks currently in service (in-flight).

### Candidate Admission Policy

When `K < len(candidates)`, the simulator must pick which experts receive tasks.
Two policies are supported:

- `--admit-policy ordered` (default): admit in router-provided order
- `--admit-policy least_pending`: admit the least-pending experts among the candidates (ties broken by router order)
- `--admit-policy score_desc`: order candidates by descending `scores` from trace replay (ties broken by router order). Requires `scores` for every trace entry.

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

### Control Loop Knobs

The base controller uses the instantaneous pending signal at each token arrival.
Three optional knobs let you turn this into a more realistic (and more stable)
control loop:

- `--k-ema-alpha A`: apply EMA smoothing to the pending signal (`A=1` disables smoothing).
- `--k-update-ms T`: only update `K` at most once per `T` ms per latency class (`T=0` updates per token).
- `--k-slew N`: limit `|delta K|` per controller update (`N=0` disables slew limiting).

This is intentionally simple; it is meant to generate stable, testable behavior
and highlight oscillation or starvation regimes early.

### Trace-Driven K (Replay)

When replaying a real quantized-runtime trace, you can bypass the controller and use the
per-token `k` decisions from the trace:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --k-mode trace --json
```

This is useful for validating the queueing/backpressure/MTP layers against a real schedule before
tuning the controller.

## MTP (Draft/Accept) Model

This simulator includes a host-only approximation of **MTP draft/accept** behavior so we can explore
the tradeoffs *before* touching CUDA runtime code.

When `--mtp-draft-len > 0`, each trace element is treated as one **verify step** which performs:

- Draft compute: enqueue `--mtp-draft-len` draft micro-tokens (same routing candidates as the verify token) with per-task cost scaled by `--mtp-draft-cost-scale`.
  - Draft micro-tokens are enqueued **before** the verify micro-token (FIFO), so they consume capacity first.
- Verify compute: enqueue one verify micro-token at full cost (optionally scaled by `--mtp-verify-per-draft-cost-scale` to model verify overhead that grows with draft length).
- Accept/reject: sample an **accept length** in `[1, --mtp-draft-len + 1]`:
  - Draft position `i` is accepted with conditional probability `--mtp-accept-prob * (--mtp-accept-decay ** i)` until the first rejection.
  - If all draft tokens are accepted, the simulator counts one extra **bonus token** (accept length `= draft_len + 1`).

Notes:

- Acceptance sampling is controlled by `--sim-seed` for determinism.
- Output tokens are tracked separately in the metrics JSON (`mtp.output_tokens`); the main `sim.num_tokens` is still the number of trace steps.

### Arrival Rate Units (MTP Comparisons)

By default `--arrival-rate-tps` is interpreted as **verify steps per second** (one trace entry per step).
When exploring MTP, it is often more useful to hold **output tokens per second** constant instead.

For synthetic traces only, `--arrival-units output_tokens` reinterprets `--arrival-rate-tps` as output-token demand and rescales the synthetic step arrival rate by the model-expected MTP accept length derived from `--mtp-accept-prob/--mtp-accept-decay`.

Notes:

- `--num-tokens` still controls the number of verify steps (trace entries). Use `mtp.output_tokens` in the metrics JSON to see the realized output-token volume.
- Trace replay (`--trace-jsonl`) uses the `t_ms` values as-is (verify-step timestamps), so `--arrival-units` is rejected in replay mode.

## Running

```bash
python3 sim/scheduler/scheduler_sim.py --json > /tmp/sched_metrics.json
python3 sim/scheduler/scheduler_sim.py --num-tokens 200000 --arrival-rate-tps 8000
```

### Compare Variants (Ablations)

Use `--compare label:JSON` to run one or more config variants against the
baseline (the config implied by the other CLI flags). The JSON object can
override any `SimConfig` field, plus `adaptive_k.*` fields.

Example: compare MTP on vs off on the same synthetic trace:

```bash
python3 sim/scheduler/scheduler_sim.py --num-tokens 20000 --arrival-units output_tokens --arrival-rate-tps 8000 --mtp-draft-len 2 --mtp-accept-prob 0.7 --mtp-accept-decay 0.6 --json --compare 'mtp_off:{"mtp_draft_len":0}'
```

The output includes:

- `baseline`: `summary` + full `metrics`
- `variants.<label>`: `summary`, `delta_vs_baseline`, and full `metrics`

Batching-style service model example:

```bash
python3 sim/scheduler/scheduler_sim.py --batch-max-batch 8 --service-base-ms 0.05 --service-per-task-ms 0.02 --json
```

Batching window example (trade queueing latency for larger batches):

```bash
python3 sim/scheduler/scheduler_sim.py --batch-max-batch 8 --batch-wait-batch-ms 0.5 --service-base-ms 0.05 --service-per-task-ms 0.02 --json
```

Example: damp K oscillations and expose SLA violations:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode markov --markov-stay-prob 0.95 --k-ema-alpha 0.2 --k-update-ms 1.0 --k-slew 1 --sla-interactive-ms 25 --json
```

MTP example (synthetic accept-all vs accept-none):

```bash
python3 sim/scheduler/scheduler_sim.py --num-tokens 20000 --mtp-draft-len 2 --mtp-accept-prob 1.0 --mtp-accept-decay 0.5 --mtp-draft-cost-scale 0.25 --json
python3 sim/scheduler/scheduler_sim.py --num-tokens 20000 --mtp-draft-len 2 --mtp-accept-prob 0.0 --mtp-draft-cost-scale 0.25 --json
```

MTP example (hold output-token arrival rate constant across accept rates):

```bash
python3 sim/scheduler/scheduler_sim.py --num-tokens 20000 --arrival-units output_tokens --arrival-rate-tps 8000 --mtp-draft-len 2 --mtp-accept-prob 1.0 --mtp-accept-decay 0.5 --mtp-draft-cost-scale 0.25 --json
python3 sim/scheduler/scheduler_sim.py --num-tokens 20000 --arrival-units output_tokens --arrival-rate-tps 8000 --mtp-draft-len 2 --mtp-accept-prob 0.0 --mtp-draft-cost-scale 0.25 --json
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

Markov mode creates temporal locality by reusing the previous token's primary expert with probability `--markov-stay-prob`
(candidates are still filled out to `--num-candidates` with Zipf-weighted sampling):

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode markov --markov-stay-prob 0.9 --zipf-alpha 1.1 --json
```

### Trace Replay (JSONL or CSV)

Replay mode can read either JSONL (`--trace-jsonl`) or CSV (`--trace-csv`).

JSONL reads one JSON object per line with required fields:

- `t_ms` (number): arrival time in milliseconds (default). Alternatively, set `--trace-time-mode dt_ms` and provide `dt_ms` instead.
- `dt_ms` (optional number): inter-arrival delta in milliseconds (requires `--trace-time-mode dt_ms`; mutually exclusive with `t_ms`)
- `cls` (`"interactive"` or `"batch"`)
- `candidates` (list[int]): ordered expert candidates
- `layers` (optional list[object]): per-layer routing (for multi-MoE-layer traces). Each element is a JSON object with:
  - `candidates` (list[int]): ordered expert candidates for that layer (required)
  - `scores` (optional list[number]): per-candidate router scores (same length as that layer's `candidates`)
  - `k` (optional int): layer-specific chosen `K` (accepted, but the simulator still treats `k` as a per-token control input)
  - `cost_scale` (optional number): layer-specific cost multiplier (multiplied into the top-level `cost_scale` when both are present)
  - When `layers` is present, the simulator expects `candidates` to either be omitted/empty or equal the union of `layers[].candidates` (first-seen order); it uses the per-layer candidate lists for admission.
- `token_index` (optional int): monotonically increasing token index from the runtime (debugging aid only)
- `k` (optional int): the chosen `K` for this token (required when using `--k-mode trace`)
- `scores` (optional list[number]): per-candidate router scores (same length as `candidates`). Required when using `--admit-policy score_desc` (when `layers` is present, use `layers[].scores` instead).
- `mtp_accept_len` (optional int): when `--mtp-draft-len > 0`, accept length for that verify step in the range `[1, mtp_draft_len+1]`
- `accepted_mtp` / `rejected_mtp` (optional int): runtime-friendly MTP accounting fields; when present, the simulator derives `mtp_accept_len` as:
  - `accepted_mtp + 1` (preferred), or
  - `(mtp_draft_len - rejected_mtp) + 1` when only `rejected_mtp` is provided
  - if both are provided, `accepted_mtp + rejected_mtp` must equal `mtp_draft_len`
  - note: when any of `mtp_accept_len` / `accepted_mtp` / `rejected_mtp` is present, replay uses it to populate the simulator’s MTP accept-rate metrics (not just output-token counts)
- `cost_scale` (optional number): per-token cost multiplier applied to all admitted tasks for that token (useful for shape-dependent service modeling in replay traces)
- `decode_ms` (optional number): observed per-token decode latency from a runtime trace; the simulator records `trace.decode_ms` and `trace.decode_error_ms` to compare the model to the trace
- `kv_tokens` (optional int): KV/cache token count at this step (the simulator summarizes this under `trace.kv_tokens`)
- `expert_batch_size` (optional int): observed expert batch size (the simulator summarizes this under `trace.expert_batch_size`)

Example:

```bash
cat > /tmp/route.jsonl <<'EOF'
{"t_ms":0.0,"cls":"interactive","candidates":[3,7,1,0]}
{"t_ms":0.2,"cls":"batch","candidates":[7,2,3,5]}
EOF
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.jsonl --num-experts 8 --json
```

CSV replay uses a header row with the same field names (list fields like `candidates` / `scores` can be JSON lists; `candidates` also accepts a simple delimiter format like `"0 1 2"`):

```bash
cat > /tmp/route.csv <<'EOF'
t_ms,cls,candidates
0.0,interactive,"[3,7,1,0]"
0.2,batch,"[7,2,3,5]"
EOF
python3 sim/scheduler/scheduler_sim.py --trace-csv /tmp/route.csv --num-experts 8 --json
```

Delta-time example (cumulative `dt_ms`):

```bash
cat > /tmp/route_dt.jsonl <<'EOF'
{"dt_ms":0.0,"cls":"interactive","candidates":[3,7,1,0]}
{"dt_ms":0.2,"cls":"batch","candidates":[7,2,3,5]}
EOF
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route_dt.jsonl --trace-time-mode dt_ms --num-experts 8 --json
```

Trace speedup (stress backpressure/starvation by compressing arrival times; `--trace-speedup 2` doubles offered load):

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.jsonl --trace-speedup 2 --num-experts 8 --json
```

Trace sanity-check (contract summary only):

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.jsonl --trace-summary --json
```

Synthetic trace dump (generate, write JSONL, and exit after printing the trace summary):

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode hotset --num-tokens 10000 --num-experts 16 --dump-trace-jsonl /tmp/synth_route.jsonl --trace-summary --json
```

Synthetic trace dump (CSV):

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode hotset --num-tokens 10000 --num-experts 16 --dump-trace-csv /tmp/synth_route.csv --trace-summary --json
```

## Metrics

The simulator prints a JSON object with:

- `sim`: makespan + token/task throughput
- `work`: total service-slot time and work-units accounting (useful for comparing compute per output token, especially with MTP enabled)
- `mtp`: MTP output-token throughput + accept-length / accept-rate metrics (enabled when `--mtp-draft-len > 0`)
- `trace.decode_ms.{interactive,batch}` and `trace.decode_error_ms.{interactive,batch}`: when trace replay includes `decode_ms`, summarize observed decode latency and error vs simulated token latency (admitted tokens only)
- `trace.kv_tokens.{interactive,batch}` and `trace.expert_batch_size.{interactive,batch}`: when trace replay includes `kv_tokens` / `expert_batch_size`, summarize observed values for admitted tokens
- `token_latency_ms.{interactive,batch}`: count/mean/p50/p95/p99/max (admitted tokens only)
- `output_token_latency_ms.{interactive,batch}`: token latency distribution weighted by realized output tokens (MTP-aware; equals `token_latency_ms` when MTP is disabled)
- `sla`: per-class token-SLA violation counts/fractions (when `--sla-*-ms` is set)
- `tokens`: token-level admitted vs dropped-by-backpressure counts
- `task_queue_wait_ms.{interactive,batch}`: queue wait before service starts (count/mean/p50/p95/p99/max)
- `chosen_k.{interactive,batch}`: mean/min/max (over tokens)
  - also includes controller update/change counts when `--k-update-ms` / `--k-slew` are used
- `pending_signal.{interactive,batch}`: per-token distribution (count/mean/p50/p95/p99/max) of the controller's congestion signal (max pending depth, using `--k-signal {global,candidates}`); useful for choosing `--q-low/--q-high`
- `effective_k.{interactive,batch}`: distribution of actually admitted tasks per admitted token (captures backpressure shortfalls)
- `tasks`: total + per-latency-class admitted/dropped/starved counters
- `tasks.promoted`: number of batch tasks promoted by `--promote-ms`
- `tasks.forced_batch_starts`: number of times `--hi-burst` forced a batch start
- `tokens.partial_admit*`: number of admitted tokens that received fewer than `min(K, len(candidates))` tasks due to backpressure
- `expert_queue`: median/max of per-expert max-pending and mean-pending
  - also includes time-weighted pending-depth percentiles across expert-time (`pending_depth_time_weighted.p{50,95,99}`)
- `expert_utilization`: median/p95/max of per-expert mean utilization (time-weighted `in_flight / expert_parallelism`)
- `expert_saturation`: median/p95/max of per-expert fraction of time pending at `--expert-queue-max`

## Quantized Runtime Trace Contract

When the baseline loop can instrument a working quantized runtime, prefer JSONL
records that are easy to replay here:

```json
{"t_ms":0.0,"token_index":12,"cls":"interactive","candidates":[7,3,19,2,1,0],"scores":[0.9,0.7,0.4,0.2,0.1,0.05]}
```

Optional fields should be added when available:

- `accepted_mtp`: number of MTP draft tokens accepted after this decode step
- `rejected_mtp`: number of MTP draft tokens rejected after this decode step
- `expert_batch_size`: observed batch size for the dispatched expert work
- `decode_ms`: measured decode latency for this token
- `kv_tokens`: KV/cache token count at this step

The first useful runtime patch can be instrumentation-only. Expert queueing
should be enabled only after replay shows a throughput win without unacceptable
interactive p95, starvation, or partial-admit regressions.

## MTP Simulation

MTP is modeled as a draft/accept layer on top of decode:

- draft cost adds work before acceptance is known
- accepted drafts reduce future decode steps
- rejected drafts still consume draft compute

Initial scheduler metrics should include accepted-token rate, rejected-token
rate, draft overhead, and net generated tokens/sec. MTP remains runtime-disabled
by default until deterministic acceptance tests pass.

## Next Steps

- Start collecting real quantized-runtime router traces and feed them into `--trace-jsonl` (see `docs/quantized-performance-path.md`).
- Add MTP draft/accept accounting once a runtime exposes draft tokens/logits.
- Replace fixed `--service-ms` with a shape-dependent service model once DS4
  expert GEMM shapes are pinned down.
- Use this harness to define production invariants (interactive p95 bounds,
  max starvation rate, acceptable drop rate) before CUDA integration.
