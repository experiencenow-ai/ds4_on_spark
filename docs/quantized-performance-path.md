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

## Gate 0: MTP sidecar + one-token wiring (no full downloads)

If you plan to evaluate DeepSeek V4 Flash MTP (or any DS4-style sidecar-driven MTP path), add an explicit correctness gate *before* any acceptance/perf claims:

- If your reference runtime is `antirez/ds4` on Spark/Linux CUDA, note that the DS4-tuned sidecar uses `Q4_K` routed experts and requires a CUDA fallback path (otherwise MTP draft fails before it can be compared). This repo tracks the minimal patch + a host-side math verifier:
  - `docs/mtp-antirez-q4-sidecar-breakthrough-2026-05-12.md`
  - `docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch`
  - `docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch` (prevents trunk/sidecar cache key collisions under CUDA weight caching)
  - `python3 scripts/verify_antirez_ds4_q4k_dot_math.py` (fixture provenance/regeneration: `docs/mtp-q4k-dot-validation.md`)

- Validate the staged MTP sidecar **contract** (Spark-safe; header + tensor table only; no trunk load):

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1' \
scripts/run_mtp_sidecar_contract_probe_spark.sh spark0@<spark-host>
```

- Recommended stronger gate (still no trunk load): run the combined **contract + loader** probe. This validates the 32 `mtp.0.*` tensors twice (Python contract probe + llama.cpp-side probe binary), can optionally `--load-weights` the sidecar tensor blob into RAM to ensure all payloads are readable, and cross-checks the JSON inventories. The output directory includes a machine-readable `summary.json`.

```bash
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1' \
REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV='ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1 JSON_ONLY=1' \
scripts/run_mtp_sidecar_loader_probe_spark.sh spark0@<spark-host>
```

- Only after the sidecar contract passes, run the llama.cpp **one-token** MTP wiring probe (gamma=1) runner (still gated; see `docs/mtp-one-token-draft-probe.md`):

```bash
scripts/run_llamacpp_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```

- Before any acceptance or speedup claims, capture an **oracle** one-token probe JSON (for example from `antirez/ds4`, patched as needed) and diff it against the candidate probe JSON:

```bash
python3 scripts/diff_mtp_one_token_draft_probe.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json
```

Do not start acceptance/metrics work until the one-token probe emits `ok=true` and the JSON validator passes; otherwise you risk optimizing a non-MTP stub path.

## Gate 1: Real Quantized Generation

Before scheduler or MTP work, capture one successful run from
`docs/quantized-single-spark.md`.

Required report fields:

- runtime repo, branch, commit, and build flags
- model HF repo/revision or local fixture provenance
- quant, size, sha256, context length, and prompt format
- TTFT, generation tokens/sec, memory snapshots, stdout/stderr
- attention scheduling signal when available (`fattn_unique_nodes`, `fattn_log_lines`)
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
- quantized-kernel routing/dispatch for MoE (`MUL_MAT_ID`): MMQ vs MMVQ counts plus a small shape histogram (for example `dst_ne[2]`, active tokens, and batch dimensions)
- GPU memory and KV cache growth
- CUDA fallback nodes and graph placement (for example `__fattn__` / `__op__` scheduling lines when present)
- MTP draft tokens, accepted tokens, and rejected tokens when available

Preferred output is JSONL so `sim/scheduler/` can replay real route traces. CSV is also supported (`--trace-csv`) when JSONL logging is awkward; use the same field names and encode list fields like `candidates` / `scores` as JSON lists.

### Current Spark0 clues (May 2026)

- Single-Spark llama.cpp DeepSeek V4 Flash IQ2XXS aggregate decode plateaus around ~13.5–14.2 tok/s; see `docs/baseline-batching-throughput.md` for the pinned command-line shapes and gating notes.
- A `MUL_MAT_ID` sampler has observed MoE routed shapes up to `dst_ne[2]=38`, with larger routed shapes hitting `mmq` while smaller shapes hit `mmvq`; treat this as a clue that some grouping exists, but require per-shape histograms and per-op timing before making any “expert queue” claims.

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

Tip: for trace replay, `--arrival-units output_tokens` scales trace arrival deltas by the expected/observed MTP accept length per run, so MTP comparisons hold output-token demand roughly constant (use this for non-MTP traces where each record is one output token).

Tip: when comparing MTP on/off against a replay trace that already includes `mtp_accept_len` (or `accepted_mtp`/`rejected_mtp`), `mtp_off` variants ignore (strip) those fields so a single-run compare works.

Tip: use `--num-layers > 1` to approximate multi-MoE-layer routing (more realistic for V4-class models) before real quantized-runtime traces are available.

Tip: to exercise score-aware admission before real traces, use `--synthetic-score-mode random` with `--admit-policy score_desc`. To explore work-weighted congestion signals on synthetic traces, emit `cost_scale` with `--synthetic-cost-scale-mode lognormal` and run with `--pending-units work` (summary includes `pending_work_depth_time_weighted_p95`, `{hi_queue,lo_queue}_work_depth_time_weighted_p95`, and `{pending_hi,pending_lo}_work_depth_time_weighted_p95`).

Tip: when `cost_scale` is meaningful (synthetic or replayed), consider `--backpressure-units work` so backpressure reflects weighted expert work instead of raw task counts.

Synthetic recommendations (reservation + MTP breakeven) are tracked in:

- `docs/scheduler-simulator-recommendations.md`
- `docs/scheduler-simulator-recommendations-2026-05-12.json`

## Phase 1: Real Router Trace Replay

Once the baseline quantized runtime can emit per-token routing, capture a trace
and replay it:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --trace-summary --json
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --num-experts 0 --json   # 0 = infer from trace/meta
```

For concise loop output, use `--summary-json`:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --num-experts 0 --summary-json
```

To run a small set of trace-backed go/no-go sweeps (expert queue max, reservation, k-signal policy, admit policy, starvation knobs, expert batching, optional pending-units and backpressure-units when `cost_scale` is present, optional per-layer K scope, and optionally MTP attempt policy; when the trace omits observed MTP accept lengths it also includes an MTP accept-prob sensitivity sweep), use:

```bash
python3 sim/scheduler/trace_sweep.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --num-experts 0 --max-tokens 5000
```

If the runtime trace does not tag `cls`, force a default for replay:

```bash
python3 sim/scheduler/trace_sweep.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-default-cls batch --num-experts 0 --max-tokens 5000
```

If the trace includes DeepSeek MTP counters (`mtp_accept_len` or `accepted_mtp`/`rejected_mtp`), generate an MTP-on vs MTP-off replay report (includes both `arrival_units=steps` and `arrival_units=output_tokens`) with:

```bash
python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip > /tmp/runtime_mtp_ablation.json
```

The report also includes an `evidence` block intended for fast go/no-go checks:

- `evidence.mtp.supported_by_trace_counters`: `true` when the replayed MTP-on run is efficiency-positive vs `mtp_off` (by `service_slot_ms_per_output_token`).
- `evidence.expert_queueing.best_variant_by_drop`: the scheduler sweep variant that most reduces backpressure drops (and its p95-latency delta) on the same trace with MTP disabled.

If the same runtime trace also includes speculative-decoding comparator counters (`dflash_accept_len` or `accepted_dflash`/`rejected_dflash`), the report includes a separate `dflash_comparator` block and keeps those counters isolated from DeepSeek MTP acceptance assumptions.

If the runtime trace omits `cost_scale` but includes `kv_tokens` or `decode_ms`, you can ask the ablation tool to derive a simple proxy cost_scale before replay (helps explore work-weighted pending/backpressure signals later):

```bash
python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --trace-derive-cost-scale kv_tokens_p50 > /tmp/runtime_mtp_ablation.json
```

If the trace includes a speculative-decoding comparator and you have (or want to assume) a draft-overhead multiplier for it, set `--dflash-draft-cost-scale` so the report’s `dflash_*_adjusted` metrics include that crude overhead model:

```bash
python3 sim/scheduler/recommendations.py --trace-jsonl /path/to/route.jsonl --trace-input-format runtime --trace-non-route skip --dflash-draft-cost-scale 0.25 > /tmp/runtime_mtp_ablation.json
```

For token-level debugging (trace-vs-model mismatches, drops, stage skips, MTP accept lengths), also dump per-step results:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --num-experts 0 --dump-sim-jsonl /tmp/sim_tokens.jsonl --summary-json
```

If the runtime emits `dt_ms` deltas (or only emits `accepted_mtp` / `rejected_mtp`), canonicalize it first so replay can infer `num_experts` / `mtp_draft_len` cleanly:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/raw.jsonl --trace-time-mode dt_ms --canonicalize-trace-jsonl /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

If the runtime produces a mixed JSONL log stream (multiple record types), use `--trace-jsonl -` with `--trace-non-route skip` to ignore non-route objects that have a non-meta `type` field:

```bash
cat /path/to/runtime.log.jsonl | python3 sim/scheduler/scheduler_sim.py --trace-jsonl - --trace-non-route skip --trace-time-mode dt_ms --canonicalize-trace-jsonl - > /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

When `--trace-non-route skip` is set, the loader also ignores non-JSON lines (plain text logs), which makes it safe to pipe raw mixed stdout/stderr streams.

If the runtime log stream is mixed and/or cannot easily emit the simulator’s strict trace field names, you can run replay/canonicalization in `runtime` input format (inline alias mapping), or normalize it explicitly with the extractor.

Inline alias mapping:

```bash
cat /path/to/runtime.log.jsonl | python3 sim/scheduler/scheduler_sim.py --trace-jsonl - --trace-input-format runtime --trace-non-route skip --trace-time-mode dt_ms --canonicalize-trace-jsonl - > /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

Extractor (maps common aliases like `latency_class`→`cls`, `experts`→`candidates`):

```bash
cat /path/to/runtime.log.jsonl | python3 sim/scheduler/trace_extract.py --in-jsonl - --out-jsonl - --non-route skip > /tmp/route.extracted.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.extracted.jsonl --trace-time-mode dt_ms --trace-non-route skip --canonicalize-trace-jsonl /tmp/route.canon.jsonl
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /tmp/route.canon.jsonl --num-experts 0 --mtp-draft-len -1 --json
```

If the runtime mixes JSON objects into plain-text log lines (for example `INFO route={...}`), keep `--extract-substrings 1` (default) so `trace_extract.py` scans each line for embedded JSON objects.

`trace_extract.py` preserves multi-layer routing when present (`layers[]` / `moe_layers[]`) and derives top-level `candidates` as the union of `layers[].candidates` so the simulator can replay the trace without additional massaging.

Some runtimes emit **one route record per MoE layer per token** (repeated `token_index`, optional `layer_index`) instead of a single `layers[]` object. Pack those per-layer records into `layers[]` first:

```bash
python3 sim/scheduler/trace_extract.py \
  --in-jsonl /path/to/runtime.log \
  --out-jsonl /tmp/routes_packed.jsonl \
  --non-route skip \
  --pack-layers-by-token-index 1
```

If the runtime provides a stable `layer_index`, require it so layer ordering is explicit:

```bash
python3 sim/scheduler/trace_extract.py \
  --in-jsonl /path/to/runtime.log \
  --out-jsonl /tmp/routes_packed.jsonl \
  --non-route skip \
  --pack-layers-by-token-index 1 \
  --pack-require-layer-index 1
```

If the runtime trace includes per-token chosen `K`, replay it directly:

```bash
python3 sim/scheduler/scheduler_sim.py --trace-jsonl /path/to/route.jsonl --k-mode trace --num-experts 0 --json
```

Trace JSONL fields:

- `t_ms`: token arrival time in milliseconds (default). Alternatively, set `--trace-time-mode dt_ms` and emit per-line `dt_ms` deltas.
- `dt_ms`: optional inter-arrival delta in milliseconds (requires `--trace-time-mode dt_ms`; mutually exclusive with `t_ms`)
- Runtime traces may emit microsecond/nanosecond variants (`t_us` / `t_ns` or `dt_us` / `dt_ns`); `--trace-input-format runtime` (or `trace_extract.py`) normalizes them into millisecond `t_ms` / `dt_ms` fields.
- `cls`: `"interactive"` or `"batch"` (runtime input format also accepts integer class IDs `0` (interactive) and `1` (batch), normalized by `--trace-input-format runtime` / `trace_extract.py`)
- Integer-like numeric fields (`candidates` entries, `k`, `mtp_accept_len`, `accepted_mtp`/`rejected_mtp`, `dflash_accept_len`, `accepted_dflash`/`rejected_dflash`, `kv_tokens`, `expert_batch_size`) may appear as integral floats in some runtimes (for example `2.0`). Both `--trace-input-format runtime` and strict trace replay accept these and coerce them to integers.
- `candidates`: ordered expert candidates for that token. For minimal router logs, `--trace-input-format runtime` (or `trace_extract.py`) also accepts a single chosen expert alias like `expert_id` / `chosen_expert` and normalizes it into `candidates=[expert_id]`.
- `layers`: optional per-layer routing list for multi-MoE-layer traces. Each element is a JSON object with:
  - `candidates`: ordered expert candidates for that layer (required)
  - `scores`: optional per-candidate scores (same length as that layer's `candidates`)
  - `k`: optional layer-local chosen `K`. When using `--k-mode trace`, you may omit top-level `k` if every layer provides `k`.
  - `cost_scale`: optional layer-specific cost multiplier (multiplied into top-level `cost_scale` when both are present)
  - when `layers` is present, `candidates` should either be omitted/empty or equal the union of `layers[].candidates` (first-seen order); the simulator uses the per-layer candidate lists for admission
- `k`: optional chosen `K`; required with `--k-mode trace` unless every layer provides `layers[].k`
- `scores`: optional per-candidate router scores (when `layers` is present, use `layers[].scores`; top-level `scores` are not valid when `layers` is present)
- `mtp_accept_len`: optional accept length for MTP replay
- `accepted_mtp` / `rejected_mtp`: optional runtime-friendly MTP accounting; the simulator can derive `mtp_accept_len` from these when `mtp_accept_len` is omitted
- `dflash_accept_len`: optional accept length for a speculative-decoding comparator trace (kept separate from DeepSeek MTP). The simulator reports separate comparator metrics (for example: `dflash_output_tokens`, `dflash_mean_accept_len`, `dflash_accept_rate`, `dflash_bonus_tokens`, `dflash_service_slot_ms_per_output_token`) in `--summary-json` without mixing them into DS4 MTP assumptions.
- `accepted_dflash` / `rejected_dflash`: optional comparator counters (kept separate from MTP). When `dflash_accept_len` is omitted but `accepted_dflash` is present, canonicalization derives `dflash_accept_len = accepted_dflash + 1`. When only `rejected_dflash` is present, canonicalization can also derive `dflash_accept_len` if `dflash_draft_len` is known (from `meta.dflash_draft_len` or consistent `accepted_dflash+rejected_dflash` elsewhere in the trace).
- `cost_scale`: optional per-token cost multiplier
- `decode_ms`: optional observed per-token decode latency (the simulator reports `trace.decode_ms` and `trace.decode_error_ms` vs modeled latency when present)
- `kv_tokens`: optional KV/cache token count at this step (the simulator summarizes this under `trace.kv_tokens` when present)
- `expert_batch_size`: optional observed expert batch size (the simulator summarizes this under `trace.expert_batch_size` when present)
- (optional) metadata: JSONL meta records like `{"type":"meta","meta":{...}}` are accepted and ignored by replay; you can also supply a sidecar metadata JSON via `--trace-meta-json`

If you emit meaningful `cost_scale` (or per-layer `layers[].cost_scale`), consider using `--pending-units work` so adaptive-K reacts to *work* rather than raw task counts, and `--backpressure-units work` so backpressure capacity is enforced in the same units.

If the runtime can log `kv_tokens` or `decode_ms` but cannot easily log `cost_scale`, the scheduler simulator can derive a simple `cost_scale` proxy during replay/canonicalization via `--trace-derive-cost-scale {kv_tokens_p50,decode_ms_p50}`.

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
  - As of 2026-05-12, metadata-only inspections of pinned community GGUF trunk artifacts reported `mtp_present=false` and `tensor_key_namespace_guess=llama.cpp` (see `docs/quantized-single-spark.md`), so assume MTP is missing unless a sidecar is supplied.
  - Treat MTP presence as a property of the **artifact set**:
    - trunk-only GGUFs commonly report `mtp_present=false` and `mtp_namespace.has_mtp0=false` (the upstream `mtp.0.*` namespace was dropped during conversion).
    - some community conversions publish MTP as a sidecar GGUF; these can report `mtp_present=true` and `mtp_namespace.has_mtp0=true` but still fail `mtp_contract.complete` (example: DS4-tuned “compact” sidecars; see `docs/gguf-inspect-antirez-3274cdc-iq2xxs-chat-v2-mtp-set.json`).
  - When available, capture `tensor_type_profile` from `scripts/model_contract_inspect_quantized_artifact.py --json` to record whether experts appear `MXFP4` (Flash-leaning) vs primarily FP8 (helps interpret external runtimes and conversions).
  - When `fixtures/model_contract/deepseek_v4_flash/contract_summary.json` is available, also record `mtp_namespace`, `mtp_contract`, and `mtp_trust` from `scripts/model_contract_inspect_quantized_artifact.py --json`.
    - `mtp_trust.status=absent|namespace_missing_mtp0|namespace_incomplete|incomplete|structural_complete_untrusted` is the expected progression for artifact sets that lack upstream-complete `mtp.0.*`.
    - Treat `structural_complete_untrusted` as “MTP weights appear complete, but still requires an MTP logits oracle (`--include-mtp`) before enabling speculative decoding.”
- expose draft logits/tokens from the runtime or a sidecar path
- when using a DS4-tuned MTP sidecar (`general.architecture=deepseek4_mtp_support`) on Spark/CUDA llama.cpp forks, validate the sidecar contract first (metadata-only): `docs/llamacpp-mtp-sidecar-probe.md`
  - Spark-only runner (local sidecar file already staged, or `https://` URL via range reads; no trunk load): `scripts/run_mtp_sidecar_contract_probe_spark.sh` (defaults to the Spark0-staged pinned sidecar path when readable)
  - Combined contract + llama.cpp loader probe (optional `LOAD_WEIGHTS=1`, still no trunk load) + pinned payload fingerprint gate: `scripts/run_mtp_sidecar_loader_probe_spark.sh` (defaults to the Spark0-staged pinned sidecar path when readable)
  - Local combined runner (no fetch/build; requires a prebuilt `llama-ds4-mtp-sidecar-probe`): `scripts/run_mtp_sidecar_loader_probe_local.sh`
- recorded metadata-only sidecar inspection (pinned antirez sidecar): `docs/gguf-inspect-antirez-3274cdc-mtp-sidecar.json`
- once the runtime can load/bind the sidecar, run the one-verify-step wiring gate before acceptance metrics: `docs/mtp-one-token-draft-probe.md`
- implement strict accept/reject accounting before optimizing
- measure acceptance rate by prompt class and context length

Trust gates (quantized high-performance path):

- Structural gate (artifact validity): require `mtp_namespace.has_mtp0 == true` and `mtp_contract.complete == true` before claiming the artifact “preserves upstream MTP”.
- Oracle gate (semantic correctness): even if structurally complete, keep MTP **untrusted** until an MTP logits oracle passes (generate with `scripts/model_contract_generate_deepseek_v4_flash_oracle.py --include-mtp` and compare both prefill and decode cases).
- Acceptance gate (runtime integration): before optimizing acceptance rate, run the one-verify-step wiring probe (`docs/mtp-one-token-draft-probe.md`) and require deterministic pass/fail behavior at `temperature=0.0`.

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
