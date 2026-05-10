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

To prevent batch traffic from fully consuming that queue capacity, you can reserve
per-expert headroom for interactive tasks:

- `--expert-queue-reserve-interactive N`: reduces the effective pending limit for **batch**
  admissions to `expert_queue_max - N` while leaving interactive admissions capped by
  `expert_queue_max`. This models a simple reservation mechanism that keeps slots available
  for interactive work under heavy batch load.

### Multi-Layer Routes

When a trace record includes `layers[]` (multi-MoE-layer routes), the simulator treats the token’s work as a sequence of **stages**:

- for each micro-token (verify-only, or draft+verify when MTP is enabled), run layer 0, then layer 1, then layer 2, ...
- tasks for later layers are not enqueued until the previous layer’s tasks complete
- if a given layer cannot admit any tasks because all of that layer’s candidates are full, the simulator skips that layer (models layer-local token dropping via the residual path)

This makes per-token latency approximately additive across layers, which better matches transformer execution than admitting all layers concurrently.

Stage skips (layer-local residual-path drops) are summarized under `stages.skipped_backpressure*` in the simulator JSON output.

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
- `--k-signal class`: `max_pending` is max pending in this token’s latency-class
  queue (interactive or batch) plus in-flight work, across all experts (helps
  decouple interactive K from batch backlog under strict priority)

You can also choose whether pending depth is measured in **task counts** or **work units**:

- `--pending-units tasks` (default): pending is outstanding task count (queued + in-flight)
- `--pending-units work`: pending is sum of `cost_scale` for queued + in-flight work (draft micro-tokens with low `--mtp-draft-cost-scale` contribute less)

When the trace contains multiple MoE layers (`layers[]`), you can choose whether the controller
produces one `K` per trace entry or one `K` per layer:

- `--k-scope token` (default): compute one `K` and apply it to every layer
- `--k-scope layer`: compute `K` independently for each layer using that layer's `candidates`

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

### `chosen_k_total` Metric

For multi-layer traces, the metrics JSON includes `chosen_k_total.{interactive,batch}` summarizing the
*total desired verify work per trace entry* (sum over layers of `min(k_layer, len(layer.candidates))`).
This is helpful when comparing `--k-scope token` vs `--k-scope layer` on the same trace.

## MTP (Draft/Accept) Model

This simulator includes a host-only approximation of **MTP draft/accept** behavior so we can explore
the tradeoffs *before* touching CUDA runtime code.

When `--mtp-draft-len > 0`, each trace element is treated as one **verify step** which performs:

- Draft compute: enqueue draft micro-tokens (same routing candidates as the verify token) with per-task cost scaled by `--mtp-draft-cost-scale`.
  - Default `--mtp-draft-attempt-policy full` always enqueues exactly `--mtp-draft-len` draft micro-tokens.
  - `--mtp-draft-attempt-policy stop_at_reject` enqueues only the draft prefix up to the first rejection (synthetic accept sampling) or up to the derived attempted length from `mtp_accept_len` in trace replay.
  - Draft micro-tokens are enqueued **before** the verify micro-token (FIFO), so they consume capacity first.
- Verify compute: enqueue one verify micro-token at full cost (optionally scaled by `--mtp-verify-per-draft-cost-scale` to model verify overhead that grows with draft length).
- Accept/reject: sample an **accept length** in `[1, --mtp-draft-len + 1]`:
  - Draft position `i` is accepted with conditional probability `--mtp-accept-prob * (--mtp-accept-decay ** i)` until the first rejection.
  - If all draft tokens are accepted, the simulator counts one extra **bonus token** (accept length `= draft_len + 1`).

Notes:

- Acceptance sampling is controlled by `--sim-seed` for determinism.
- Output tokens are tracked separately in the metrics JSON (`mtp.output_tokens`); the main `sim.num_tokens` is still the number of trace steps.
- Queueing effects are broken down by phase in the metrics JSON under `mtp.task_queue_wait_ms.{draft,verify}` and `mtp.starved_task_frac.{draft,verify}` (useful for spotting draft-induced verify starvation).

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

For concise, loop-friendly output, use `--summary-json` (prints the same summary block as `--compare`, without the full metrics payload):

```bash
python3 sim/scheduler/scheduler_sim.py --summary-json
python3 sim/scheduler/scheduler_sim.py --summary-json --compare 'mtp_off:{"mtp_draft_len":0}'
```

The summary output is intentionally small but includes per-class backpressure/starvation and queue-depth signals that are useful for go/no-go decisions (for example: `drop_frac_tokens_{interactive,batch}`, `starved_task_frac_{interactive,batch}`, and `{pending,hi_queue,lo_queue}_depth_time_weighted_p95`).

When batching is enabled (or when replay traces include `expert_batch_size`), the summary also reports batch-size percentiles for quick calibration loops: `service_batch_size_p{50,95}_{interactive,batch}` (simulated start batch sizes) and `trace_expert_batch_size_p{50,95}_{interactive,batch}` (observed, when present).

When replay traces include `decode_ms` and/or `kv_tokens`, the summary also reports trace percentiles and model-vs-trace decode error percentiles (for quick sanity checks that queueing/backpressure behavior is in the right ballpark): `trace_decode_ms_p{50,95}_{interactive,batch}`, `trace_decode_error_ms_p{50,95}_{interactive,batch}`, and `trace_kv_tokens_p{50,95}_{interactive,batch}`.

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

### Synthetic Scores and Cost Scaling

To exercise score-aware admission (`--admit-policy score_desc`) before real runtime traces are available, synthetic traces can emit per-candidate `scores`:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode zipf --synthetic-score-mode random --admit-policy score_desc --json
```

Notes:

- `--synthetic-score-mode random` assigns independent `U[0,1)` scores per candidate while keeping the candidate order unchanged.
- `--synthetic-score-mode router_desc` also reorders candidates by descending score (router-like), which makes `--admit-policy ordered` and `score_desc` equivalent.
- When `--num-layers > 1`, scores are emitted under `layers[].scores` (top-level `scores` is omitted).

To explore work-weighted congestion (and `--pending-units work`) on synthetic traces, you can also emit per-token `cost_scale`:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode hotset --synthetic-cost-scale-mode lognormal --pending-units work --json
```

### Synthetic Multi-Layer Routes

To approximate multi-MoE-layer models before real quantized-runtime traces are available, synthetic traces can emit per-layer routing:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-mode hotset --num-layers 4 --num-candidates 8 --json
```

When `--num-layers > 1`, each generated trace record includes a `layers` array with one candidate list per layer. The top-level `candidates` field is set to the union of all layer candidates (first-seen order) for compatibility with `--k-signal candidates` and trace replay tooling.

### Trace Replay (JSONL or CSV)

Replay mode can read either JSONL (`--trace-jsonl`) or CSV (`--trace-csv`).

JSONL reads one JSON object per line (use `--trace-jsonl -` to read from stdin) with required fields:

- `t_ms` (number): arrival time in milliseconds (default). Alternatively, set `--trace-time-mode dt_ms` and provide `dt_ms` instead.
- `dt_ms` (optional number): inter-arrival delta in milliseconds (requires `--trace-time-mode dt_ms`; mutually exclusive with `t_ms`)
- `cls` (`"interactive"` or `"batch"`)
- `candidates` (list[int]): ordered expert candidates
  - Replay requires `--num-experts > expert_id_range.max` (see `--trace-summary`); the simulator rejects out-of-range expert IDs with a clear error.
- Inline metadata records are also accepted in JSONL and ignored by the simulator's event stream:
  - `{"type":"meta","meta":{...}}` (preferred), or
  - `{"meta":{...}}` when no other routing fields are present
  - You can also pass a sidecar metadata JSON via `--trace-meta-json` (its keys are merged into the trace summary; inline records override it).

If you have a raw runtime trace that uses `dt_ms` deltas (or emits `accepted_mtp` / `rejected_mtp` but not `mtp_accept_len`), you can canonicalize it into the simulator’s preferred strict JSONL form (writes a meta header plus derived `t_ms`/`mtp_accept_len`):

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/raw.jsonl --trace-time-mode dt_ms --canonicalize-trace-jsonl /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

If the runtime emits a *mixed* JSONL log stream (multiple record types), canonicalization and replay can ignore non-route records that have a non-meta `type` field via `--trace-non-route skip`:

```bash
cat /path/to/runtime.log.jsonl | python3 sim/scheduler/scheduler_sim.py --trace-jsonl - --trace-non-route skip --canonicalize-trace-jsonl - > /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

When `--trace-non-route skip` is set, the loader also ignores non-JSON lines (plain text logs) so you can pipe raw mixed stdout/stderr streams without pre-filtering.

If the runtime log stream is mixed *and/or* uses different field names (for example `latency_class` instead of `cls`, or `experts` instead of `candidates`), you can run replay/canonicalization in `runtime` input format (which applies the same alias mapping as `trace_extract.py` inline):

```bash
cat /path/to/runtime.log.jsonl | python3 sim/scheduler/scheduler_sim.py --trace-jsonl - --trace-input-format runtime --trace-non-route skip --trace-time-mode dt_ms --canonicalize-trace-jsonl - > /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

Or, use the lightweight extractor explicitly to map common aliases into the strict simulator contract:

```bash
cat /path/to/runtime.log.jsonl | python3 sim/scheduler/trace_extract.py --in-jsonl - --out-jsonl - --non-route skip > /tmp/route.extracted.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.extracted.jsonl --trace-time-mode dt_ms --trace-non-route skip --canonicalize-trace-jsonl /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

`trace_extract.py` also preserves multi-layer routing when the runtime logs `layers[]` (or `moe_layers[]`) and derives top-level `candidates` as the union of `layers[].candidates` (first-seen order) to satisfy the simulator trace contract.

If the runtime trace logs `kv_tokens` or `decode_ms` but does not log `cost_scale`, you can derive a simple per-token `cost_scale` proxy during replay or canonicalization. This is useful with `--pending-units work` so adaptive-K reacts to *work* rather than raw task counts:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/raw.jsonl --trace-time-mode dt_ms --trace-non-route skip --trace-derive-cost-scale kv_tokens_p50 --canonicalize-trace-jsonl /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --pending-units work --json
```
- `layers` (optional list[object]): per-layer routing (for multi-MoE-layer traces). Each element is a JSON object with:
  - `candidates` (list[int]): ordered expert candidates for that layer (required)
  - `scores` (optional list[number]): per-candidate router scores (same length as that layer's `candidates`)
  - `k` (optional int): layer-specific chosen `K`. When using `--k-mode trace`, you may omit top-level `k` if every layer provides `k`.
  - `cost_scale` (optional number): layer-specific cost multiplier (multiplied into the top-level `cost_scale` when both are present)
  - When `layers` is present, the simulator expects `candidates` to either be omitted/empty or equal the union of `layers[].candidates` (first-seen order); it uses the per-layer candidate lists for admission and runs the layers sequentially.
- `token_index` (optional int): monotonically increasing token index from the runtime (debugging aid only)
- `k` (optional int): the chosen `K` for this token (required when using `--k-mode trace` unless every layer provides `layers[].k`)
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

Tip: in replay mode you can set `--num-experts 0` to infer `num_experts` from the trace (or `meta.num_experts`), and `--mtp-draft-len -1` to infer `mtp_draft_len` from `meta.mtp_draft_len` or consistent `accepted_mtp+rejected_mtp` fields.

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
- `work`: service-slot time, work-units, and batch-size accounting (useful for comparing compute per output token, especially with MTP enabled)
  - `work.batch_size.{interactive,batch}` summarizes the simulator’s started batch sizes per expert worker (queue served, not token class; promoted batch tasks count as interactive-queue batches)
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
- `pending_signal.{interactive,batch}`: per-token distribution (count/mean/p50/p95/p99/max) of the controller's congestion signal (max pending depth, using `--k-signal {global,candidates,class}`); useful for choosing `--q-low/--q-high`
- `effective_k.{interactive,batch}`: distribution of actually admitted tasks per admitted token (captures backpressure shortfalls)
- `effective_k_total.{interactive,batch}`: like `effective_k`, but summed across all routing layers when `layers` is present
- `tasks`: total + per-latency-class admitted/dropped/starved counters
- `tasks.promoted`: number of batch tasks promoted by `--promote-ms`
- `tasks.forced_batch_starts`: number of times `--hi-burst` forced a batch start
- `tokens.partial_admit*`: number of admitted tokens that received fewer than `min(K, len(candidates))` tasks due to backpressure
- `tokens.partial_admit_any_layer*`: like `tokens.partial_admit*`, but triggers when *any* routing layer under-admits during the verify step
- `expert_queue`: median/max of per-expert max-pending and mean-pending
  - also includes `expert_queue.work` (per-expert max/mean pending work units, time-weighted) so `--pending-units work` has observable queue depth
  - also includes `expert_queue.starvation_task_frac` (median/p95/max across experts) for the fraction of started tasks that waited at least `--starvation-ms` before service
  - also includes `expert_queue.max_task_queue_wait_ms` (median/p95/max across experts) for per-expert worst-case queue wait before service
  - also includes time-weighted depth percentiles across expert-time:
    - `pending_depth_time_weighted.p{50,95,99}`: total outstanding tasks (queued + in-flight)
    - `hi_queue_depth_time_weighted.p{50,95,99}`: interactive queue depth (queued only)
    - `lo_queue_depth_time_weighted.p{50,95,99}`: batch queue depth (queued only)
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

Tip: when the runtime can also report observed `expert_batch_size`, compare it against `work.batch_size` under the same trace replay settings to see whether the simulator’s batching window + admission policy approximates the observed dispatch regime.

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
- Once real traces include `expert_batch_size`, calibrate service/batching knobs and decide whether expert queueing improves batch sizes without interactive p95 regressions.
- Replace fixed `--service-ms` with a shape-dependent service model once DS4
  expert GEMM shapes are pinned down.
- Use this harness to define production invariants (interactive p95 bounds,
  max starvation rate, acceptable drop rate) before CUDA integration.
