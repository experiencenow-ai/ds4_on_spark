# Quantized Performance Path (Scheduler + MTP)

Goal: use a working quantized V4 Flash runtime as the fastest path to a useful
high-performance Spark0 build. Native DS4 remains the long-term engine, but a
V4-capable quantized runtime can let us validate scheduler, expert-queue, MTP,
serving, and memory behavior against real generation much earlier.

## Thesis

If Spark0 can load a quantized V4 Flash artifact and produce tokens, then the
next priority is not immediately rewriting the whole model loader. The next
priority is to add measurable performance layers around that working path:

1. stabilize one quantized runtime + artifact pair
2. instrument decode, routing, expert activity, memory, and per-token latency
3. add expert queueing or batching where MoE dispatch underfills GPU work
4. add MTP speculative decode when acceptance rate is measurable and positive
5. turn the best working path into the reference behavior for native DS4

This can get us most of the way to a usable high-performance quantized product
before the native FP4/FP8 loader and dual-Spark TP path are complete.

## Gate 1: Real Quantized Generation

Before scheduler or MTP work, capture one successful run from
`docs/quantized-single-spark.md`.

Required report fields:

- runtime repo, branch, commit, and build flags
- model HF repo/revision or local fixture provenance
- quant, size, sha256, context length, and prompt format
- TTFT, generation tokens/sec, memory snapshots, stdout/stderr
- whether the runtime exposes routing, expert, logits, or MTP hooks

If the runtime cannot expose hooks, record the missing hook as the blocker. Do
not guess at hidden scheduler behavior from aggregate tokens/sec.

## Gate 2: Runtime Instrumentation

The first performance PRs should add read-only instrumentation before changing
scheduling behavior:

- per-token decode latency
- per-layer MoE dispatch counts
- selected expert IDs and top-k scores when available
- expert GEMM batch sizes
- GPU memory and KV cache growth
- MTP draft tokens, accepted tokens, and rejected tokens when available

Preferred output is JSONL so `sim/scheduler/` can replay real route traces.

## Phase 0: Simulator-Only

Use `docs/scheduler-simulator.md` with synthetic traces to explore:

- adaptive-K control loops
- expert queue depth, backpressure drops, starvation
- latency classes (interactive vs batch)
- MTP draft/accept tradeoffs with synthetic acceptance

The goal is to identify safe default invariants: max starvation, acceptable drop
rate, target p95 latency, and whether MTP output-token throughput can plausibly
offset draft overhead for realistic accept rates.

Tip: for synthetic traces, `--arrival-units output_tokens` keeps output-token
demand fixed while varying MTP accept rates.

## Phase 1: Real Router Trace Replay

Once the baseline quantized runtime can emit per-token routing, capture a trace
and replay it:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --trace-summary --json
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --num-experts 64 --json
```

If the runtime trace includes per-token chosen `K`, replay it directly:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --k-mode trace --num-experts 64 --json
```

Trace JSONL fields:

- `t_ms`: token arrival time in milliseconds (default). Alternatively, set `--trace-time-mode dt_ms` and emit per-line `dt_ms` deltas.
- `dt_ms`: optional inter-arrival delta in milliseconds (requires `--trace-time-mode dt_ms`; mutually exclusive with `t_ms`)
- `cls`: `"interactive"` or `"batch"`
- `candidates`: ordered expert candidates for that token
- `k`: optional chosen `K`; required with `--k-mode trace`
- `scores`: optional per-candidate router scores
- `mtp_accept_len`: optional accept length for MTP replay
- `accepted_mtp` / `rejected_mtp`: optional runtime-friendly MTP accounting; the simulator can derive `mtp_accept_len` from these when `mtp_accept_len` is omitted
- `cost_scale`: optional per-token cost multiplier

## Expert Queueing

Expert queueing is worth attempting against the quantized runtime if decode
shows many small expert GEMMs or hot experts causing idle gaps.

Initial scope:

- collect real route traces from the quantized runtime
- replay them in the host scheduler simulator
- test queue depth, adaptive K, batching size, starvation, and latency-class
  policies before changing runtime behavior
- patch the runtime only after simulator metrics show a clear win

Success criteria:

- interactive p95 does not regress beyond the agreed bound
- generation throughput improves on the same prompt set
- starvation and dropped/partial-admit counters stay bounded
- output tokens remain deterministic under temperature `0.0` when scheduling is
  not supposed to change model semantics

## MTP

MTP should move earlier once a quantized runtime works, because V4 Flash includes
MTP artifacts and MTP can be tested as a wrapper around a working decode loop.

Initial scope:

- confirm the quantized artifact includes usable MTP weights or document why it
  does not
- expose draft logits/tokens from the runtime or a sidecar path
- implement strict accept/reject accounting before optimizing
- measure acceptance rate by prompt class and context length

Success criteria:

- accepted-token rate is high enough to offset draft overhead
- generated output matches normal decode for deterministic acceptance tests
- MTP can be disabled at runtime with a flag
- MTP metrics appear in every baseline report

Trace replay should log draft length and observed accept length per verify step
(`mtp_accept_len`, range `1..gamma+1`). Use trace `t_ms` as verify-step
timestamps.

## Practical Loop

1. Reproduce a simulator regime that stresses backpressure or starvation.
2. Capture a router trace from the quantized runtime under comparable load.
3. Replay via `--trace-jsonl` and compare queue depth, starvation, drop rates,
   and MTP accept-rate sensitivity.
4. Document acceptance/throughput evidence before touching runtime code.

## Automation Ownership

- Baseline runtime owns Spark0 quantized runs and records instrumentation/MTP
  flags in reports.
- Scheduler simulator owns real route replay, expert queue experiments, and
  acceptance/backpressure metrics.
- Model contract owns the MTP correctness contract and tokenizer/logit oracle.
- Build skeleton/native DS4 owns reusable control-plane interfaces once the
  quantized path proves which hooks matter.

## Stop Conditions

Stop optimizing the quantized path and fall back to native DS4 work if:

- no available runtime can load a credible single-Spark quantized artifact
- runtime hooks are too invasive to add safely
- expert queueing changes semantics or causes unacceptable p95 regressions
- MTP acceptance is too low to pay for itself on representative prompts
