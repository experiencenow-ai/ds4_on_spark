# Quantized Performance Path (Scheduler + MTP)

This doc connects the **host-only scheduler simulator** (`sim/scheduler/`) to the first
quantized-runtime traces so we can validate whether **expert queueing** and **MTP**
are worth enabling before patching CUDA/runtime code.

## Phase 0: Simulator-Only (Synthetic Traces)

Use `docs/scheduler-simulator.md` to explore:

- adaptive-K control loops
- expert queue depth, backpressure drops, starvation
- latency classes (interactive vs batch)
- MTP draft/accept tradeoffs (synthetic acceptance)

The goal is to identify:

- safe default invariants (max starvation, acceptable drop rate, target p95 latency)
- whether MTP’s output-token throughput can plausibly offset its draft overhead for realistic accept rates

## Phase 1: Real Router Trace Replay (JSONL)

Once the baseline quantized runtime can emit per-token routing, capture a trace and replay it:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --num-experts 64 --json
```

### Trace Schema (JSONL)

One JSON object per line:

- `t_ms` (number): token arrival time in milliseconds
- `cls` (string): `"interactive"` or `"batch"`
- `candidates` (list[int]): ordered expert candidates for that token
- `scores` (optional list[number]): per-candidate router scores (same length as `candidates`)
- `mtp_accept_len` (optional int): when replaying MTP (`--mtp-draft-len > 0`), the observed accept length for that verify step in the range `[1, mtp_draft_len+1]`

The simulator validates:

- `t_ms >= 0`
- `0 <= candidates[i] < --num-experts`
- `len(scores) == len(candidates)` when present

### What To Log In Quantized Runtime (Minimum Viable)

To make the first replay meaningful, log at least:

- token enqueue timestamp (`t_ms`) at the scheduler boundary (before admission/backpressure)
- latency class (`cls`) derived from request lane / priority
- ordered candidate expert ids (`candidates`) as produced by the router

Optional but useful:

- router scores/probabilities (`scores`)
- observed per-expert queue depth at enqueue time (for later model/validation)

## MTP Status

As of this track:

- The simulator models MTP accept/reject with synthetic knobs (`--mtp-*`), producing acceptance and output-token throughput metrics.
- Trace replay optionally supports per-step `mtp_accept_len` (accept length per verify step), but there are **no** real quantized-runtime MTP traces checked into this repo yet.

Next trace milestones for MTP:

- log the draft length per verify step (or configured `gamma`)
- log observed accept length per step (`mtp_accept_len`): `1..gamma+1` where `gamma` is the configured draft length

## Practical Loop

1. Reproduce a simulator regime (synthetic) that stresses backpressure/starvation.
2. Capture a router trace from quantized runtime under a comparable load.
3. Replay via `--trace-jsonl` and compare:
   - queue depth distributions
   - starvation and drop rates
   - (when enabled) MTP accept-rate sensitivity vs throughput gains

When the trace-backed simulator results support an optimization (MTP or expert queueing),
prefer documenting the acceptance/throughput evidence here before touching runtime code.
