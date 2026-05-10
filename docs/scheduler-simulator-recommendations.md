# Scheduler Simulator Recommendations (Synthetic)

Date: 2026-05-10

This note records *synthetic* go/no-go guidance for two early performance layers:

- expert queue reservation (protect interactive under batch load)
- MTP draft/accept (speculative decode efficiency threshold)

All numbers below come from the committed JSON report:

- `docs/scheduler-simulator-recommendations-2026-05-10.json`

Regenerate it with:

```bash
python3 sim/scheduler/recommendations.py --json > docs/scheduler-simulator-recommendations-2026-05-10.json
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

## Next Step (Real Traces)

These are synthetic signals only. The next gating artifact for scheduler work is a real quantized-runtime JSONL route trace (routing + latency + optional MTP accounting) that can be replayed via:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --summary-json
```
