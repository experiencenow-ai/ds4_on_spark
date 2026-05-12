# Scheduler Simulator Recommendations (Synthetic)

Date: 2026-05-12

This note records *synthetic* go/no-go guidance for early scheduler/perf layers:

- expert queue reservation (protect interactive under batch load)
- backpressure units (tasks vs work when cost_scale is meaningful)
- expert batching (microbatch batch-class work to amortize per-batch overhead)
- adaptive K (throttle batch admission under congestion)
- MTP draft/accept (speculative decode efficiency threshold + safety under overload)

All numbers below come from the committed JSON report:

- `docs/scheduler-simulator-recommendations-2026-05-12.json`

Regenerate it with:

```bash
python3 sim/scheduler/recommendations.py --json > docs/scheduler-simulator-recommendations-2026-05-12.json
```

## Expert Queue Reservation

Scenario: two-stream arrivals (interactive + batch) with saturated batch demand, small per-expert queue (`expert_queue_max=128`), and `service_ms=1.0` to force congestion.

Key signals (from the report JSON):

- `drop_frac_tokens_interactive`:
  - with `expert_queue_reserve_interactive=16`: `0.0`
  - with `expert_queue_reserve_interactive=0`: `0.6151742993848257`
- `drop_frac_tokens_batch`:
  - with reserve: `0.6817055879187522`
  - without reserve: `0.5971607701112117`

Recommendation (synthetic): keep a **reservation-style mechanism** available in the runtime design so batch backlog cannot consume all expert queue capacity; tune `N` against real traces to avoid excessive batch drop.

Notes:

- Tail latency comparisons are not meaningful when one variant drops a large fraction of interactive work; use drop/starvation and depth metrics first.

## Backpressure Units (Tasks vs Work)

Scenario: two-stream overload with a variable per-task `cost_scale` (lognormal; service time scales by `sum(cost_scale)` per started expert batch). Baseline uses `backpressure_units=tasks` but still tracks congestion in `pending_units=work`. Compare:

- baseline: `backpressure_units=tasks`
- variant: `backpressure_units=work`

Key signals (from the report JSON):

- `drop_frac_tokens_interactive`: `0.0` for both variants in this scenario
- `token_p95_interactive_ms`:
  - tasks backpressure: `12.97394817019374`
  - work backpressure: `9.73394870584012`
- `starved_task_queue_wait_ms_p95_batch`:
  - tasks backpressure: `262.02197346359674`
  - work backpressure: `164.73410103379825`
- `service_slot_ms_per_output_token`:
  - tasks backpressure: `1.932410530923247`
  - work backpressure: `1.8696613553483787`

Recommendation (synthetic): keep a **work-weighted backpressure** option available for real trace replay when `cost_scale` is meaningful (or derivable from `kv_tokens` / `decode_ms`). Do not default to work backpressure until real quantized-runtime traces show it improves starvation and interactive tail without an unacceptable drop/partial-admit tradeoff.

## Backpressure Zero-Admit Policy (Skip vs Stall)

Scenario: two-stream overload with reservation enabled (`expert_queue_reserve_interactive=16`), fixed batch `K=2`, and a small per-expert queue (`expert_queue_max=128`). Compare:

- baseline: `backpressure_zero_admit_policy=skip` (drop a stage when all candidates are saturated; token may drop if every stage skips)
- variant: `backpressure_zero_admit_policy=stall` (retry the blocked stage later to model upstream queueing)

Key signals (from the report JSON):

- `drop_frac_tokens`:
  - skip: `0.732225`
  - stall: `0.0`
- `token_p95_batch_ms` (batch tail latency):
  - skip: `163.9802753753623`
  - stall: `3967.405404100289`
- `blocked_stages_backpressure_attempts`:
  - skip: `0.0`
  - stall: `1298816.0`

Recommendation (synthetic): keep **`skip`** as the default for early experiments so overload regimes surface as explicit drops/partial-admit rather than extreme queueing latency. Treat **`stall`** as a separate upstream-queueing mode to evaluate on real quantized-runtime traces when drops are unacceptable and queueing latency bounds are well-defined.

## Expert Batching (Per-Expert Microbatching)

Scenario: two-stream overload with reservation enabled (`expert_queue_reserve_interactive=16`) and a simple service model with per-batch overhead:

- `service_base_ms=0.25` (fixed cost per started expert batch)
- `service_per_task_ms=1.0` (incremental cost per task/work-unit inside the batch)

Compare `batch_max_batch`:

- baseline `batch_max_batch=1` (no batching)
- `batch_max_batch=4`
- `batch_max_batch=8`

Key signals (from the report JSON):

- `service_slot_ms_per_output_token` (lower is better):
  - no batching: `1.262110980622431`
  - batch 4: `1.08307777493824`
  - batch 8: `1.0529988370161156`
- `drop_frac_tokens` (lower is better):
  - no batching: `0.6594`
  - batch 4: `0.6087`
  - batch 8: `0.5987333333333333`
- `token_p95_interactive_ms` (interactive tail cost):
  - no batching: `2.9098653334482805`
  - batch 4: `5.379310308471679`
  - batch 8: `9.234806787588198`

Recommendation (synthetic): keep an **expert batching** knob available (at least for batch-class work). Start with `batch_max_batch≈4` as a conservative default when per-batch overhead is non-trivial, but validate the interactive tail-cost tradeoff on real quantized-runtime traces before enabling.

## MTP (Draft/Accept) Efficiency Threshold

Scenario: hotset routing with low congestion (`expert_queue_max=10_000`, `service_ms=0.2`) to focus on compute efficiency rather than queueing artifacts. Sweep uses:

- `mtp_draft_len=2`
- `mtp_accept_decay=0.8`
- `mtp_draft_cost_scale=0.25`

Metric: `service_slot_ms_per_output_token_ratio_vs_no_mtp` (lower is better).

From the report JSON:

- At `accept_rate=0.0`: ratio `1.500000000001324` (strictly worse than no MTP).
- First observed efficiency win at `accept_rate≈0.2639`: ratio `0.9818039010350333`.
- At `accept_rate≈0.44152`: ratio `0.7965842467506394`.

Recommendation (synthetic): don’t enable MTP by default unless real traces show **measured** acceptance rate comfortably above ~`0.27` for the chosen `draft_len` and cost model; otherwise treat it as an opt-in experiment.

## MTP (Congestion Safety + Draft Attempt Policy)

Scenario: two-stream overload (interactive + saturated batch) with a small expert queue (`expert_queue_max=128`) and reservation enabled (`expert_queue_reserve_interactive=16`). This tests whether MTP draft work can amplify queue pressure and harm interactive SLA/starvation, even when MTP looks efficient in a low-congestion sweep.

This scenario holds *output-token demand* approximately constant by scaling verify-step arrivals using the model-expected accept length (equivalent to `--arrival-units output_tokens` in the CLI, but implemented inside the harness).

Key signals to inspect (from the report JSON, per accept probability):

- `mtp_full` vs `mtp_stop_at_reject`:
  - `service_slot_ms_per_output_token` (efficiency)
  - `sla_violation_frac_tokens_interactive` (interactive SLA safety)
  - `starved_task_frac_mtp_verify` (verify-phase starvation under draft pressure)

Recommendation (synthetic): default MTP compute policy should behave like `stop_at_reject` (don’t always compute full `gamma` drafts). Even at accept_prob `0.0`, this reduces wasted draft work vs `full`, which is a safer baseline under unknown/low accept regimes. Validate the full queueing story on real quantized-runtime traces before enabling MTP.

## MTP (Accept-Length Shape Sensitivity)

Scenario: the same two-stream overload regime as the congestion sweep, but using the simulator’s histogram accept model (`mtp_accept_model=hist`) with `draft_len=3` and three different accept-length histograms that all share the same mean accept length (`E[accept_len]=2.5`):

- `uniform`: `[0.25, 0.25, 0.25, 0.25]`
- `middle_heavy`: `[0.1, 0.4, 0.4, 0.1]`
- `bimodal_extremes`: `[0.4, 0.1, 0.1, 0.4]`

Key signals to inspect (from the report JSON, per histogram):

- `service_slot_ms_per_output_token` (compute efficiency)
- `sla_violation_frac_tokens_interactive` and `token_p95_interactive_ms` (interactive safety)
- `pending_depth_time_weighted_p95_mtp_verify` and `starved_task_frac_mtp_verify` (verify-phase congestion / starvation)

Recommendation (synthetic): treat MTP accept-length *shape* as a first-class input once real traces exist. Mean-only fits (for example a single accept rate) can miss heavy tails of short accepts that amplify queue pressure. Prefer replaying empirical `accept_len` histograms from quantized-runtime traces before enabling MTP.

## Adaptive K (Batch Throttling Under Congestion)

Scenario: two-stream arrivals (interactive + batch) with sustained overload, small per-expert queue (`expert_queue_max=128`), and `service_ms=1.0`. Compare:

- adaptive batch K (`k_min_batch=1`, `k_max_batch=2`, `q_low=8`, `q_high=96`)
- fixed batch K=2 (always admit 2 batch experts per step)
- fixed batch K=1

Key signals (from the report JSON):

- `drop_frac_tokens`:
  - adaptive: `0.58295`
  - fixed batch K=2: `0.724825`
  - fixed batch K=1: `0.5813`
- `partial_admit_frac_tokens` (tokens that admitted some but not all desired tasks):
  - adaptive: `0.0`
  - fixed batch K=2: `0.4518033978377396`
  - fixed batch K=1: `0.0`

Recommendation (synthetic): keep an **adaptive batch-K controller** available; fixed high batch K can sharply inflate backpressure drops under overload. Tune thresholds against real traces once available.

## Adaptive K Controller Smoothing (EMA + Update Interval)

Scenario: two-stream arrivals with bursty inter-arrival deltas (both classes), moderate queue capacity (`expert_queue_max=512`), and adaptive K enabled. Compare:

- baseline (no smoothing): `ema_alpha=1.0`, `update_ms=0.0`, `k_slew=0`
- EMA smoothing: `ema_alpha=0.2`, `update_ms=0.0`, `k_slew=1`
- EMA + rate-limited updates: `ema_alpha=0.2`, `update_ms=2.0`, `k_slew=1`

Key signals (from the report JSON):

- `k_change_frac_tokens_batch`:
  - baseline: `0.000225`
  - EMA: `7.5e-05`
  - EMA + update_ms: `7.5e-05`
- `k_update_frac_tokens_batch`:
  - baseline: `1.0`
  - EMA: `1.0`
  - EMA + update_ms: `0.137625`

Recommendation (synthetic): keep **controller smoothing knobs** available in the runtime design (EMA, update interval, and optional slew). They reduce controller churn in bursty regimes without changing drop behavior here; tune against real quantized-runtime traces before committing to defaults.

## Adaptive K Signal Choice (Global vs Candidates vs Class)

Scenario: two-stream overload with non-trivial interactive demand (`interactive_arrival_rate_tps=2000`) plus saturated batch demand (`batch_arrival_rate_tps=20000`), small expert queue (`expert_queue_max=128`), and adaptive K enabled.

Compare `k_signal` policies:

- `global`: congestion signal is max pending across all experts
- `candidates`: congestion signal is max pending among this token’s candidate experts
- `class`: congestion signal is max pending in this token’s latency-class queue only
- `global_mean`: congestion signal is mean pending across all experts (less sensitive to single hot experts)
- `candidates_mean`: congestion signal is mean pending among this token’s candidate experts
- `class_mean`: congestion signal is mean pending in this token’s latency-class queue only

Key signals to inspect (from the report JSON):

- `token_p95_interactive_ms` and `sla_violation_frac_tokens_interactive` (interactive safety)
- `drop_frac_tokens_batch` and `pending_depth_time_weighted_p95` (congestion + backpressure pressure)

Recommendation (synthetic): default to **`k_signal=global`** (or `candidates`) until real traces are replayed. In this overload regime, `k_signal=class` can over-admit interactive work and amplify interactive SLA violations even when a reservation is present.

## Candidate Admission Policy (Load Skew)

Scenario: a worst-case burst where every token arrives at the same timestamp and shares the same candidate set (`candidates=[0..7]`). Batch K is fixed at `2` so the only difference is *which* two experts are chosen from the candidate list.

Compare `admit_policy`:

- `ordered` (router order; default)
- `least_pending` (pick the least-pending experts among candidates)

Key signals (from the report JSON):

- `expert_tasks_started_gini` (lower is more balanced):
  - `ordered`: `0.75`
  - `least_pending`: `0.0`
- `expert_tasks_started_top1_frac` (lower is more balanced):
  - `ordered`: `0.5`
  - `least_pending`: `0.125`
- `makespan_ms` (lower is faster completion under burst):
  - `ordered`: `256.0`
  - `least_pending`: `64.0`

Recommendation (synthetic): keep `ordered` as the default to respect router preference ordering, but keep `least_pending` available as an experiment for hot-expert regimes. Validate on real quantized-runtime traces before enabling because changing admission order could change routing quality (and potentially output).

## Batch Starvation Knobs (hi_burst vs promote_ms)

Scenario: mixed load with more uniform routing (low Zipf skew) to isolate service-discipline effects. Strict priority can starve batch tasks even when interactive latency is healthy.

Compare:

- strict priority (`hi_burst=0`, `promote_ms=0`)
- bounded priority (`hi_burst=8`) to force periodic batch starts
- aging (`promote_ms=20ms`) and combined (`hi_burst=8` + `promote_ms=20ms`)

Key signals to inspect (from the report JSON):

- `starved_task_frac_batch` (batch starvation)
- `starved_task_queue_wait_ms_p95_batch` (how severe the starvation is)
- `token_p95_interactive_ms` (interactive tail cost)

Recommendation (synthetic): keep **`hi_burst`** as a default anti-starvation safety valve; treat `promote_ms` as an opt-in knob that can reduce starvation further but may inflate interactive tail latency.

## Next Step (Real Traces)

These are synthetic signals only. The next gating artifact for scheduler work is a real quantized-runtime JSONL route trace (routing + latency + optional MTP accounting) that can be replayed via:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --summary-json
```

You can run a runtime-trace report that always includes a small scheduler knob sweep (`scheduler_sweeps`) for backpressure/queueing policies, and when the trace includes DeepSeek MTP counters (`mtp_accept_len` or `accepted_mtp`/`rejected_mtp`) it also includes an MTP-on vs MTP-off ablation (both `arrival_units=steps` and `arrival_units=output_tokens`) via:

```bash
python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip > /tmp/runtime_mtp_ablation.json
```

If the trace also includes a speculative-decoding comparator (for example a target+DFlash run) via `dflash_accept_len` or `accepted_dflash`/`rejected_dflash`, the same report includes a separate `dflash_comparator` block that summarizes acceptance and reports efficiency ratios without mixing the comparator into DeepSeek MTP acceptance assumptions. If you set `--dflash-draft-cost-scale`, the report also emits an `_adjusted` ratio that applies a crude per-step draft overhead model (still treat comparator ratios as approximate).

Optional knobs for runtime traces:

```bash
python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-derive-cost-scale kv_tokens_p50
python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --dflash-draft-cost-scale 0.25
```
