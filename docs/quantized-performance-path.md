# Quantized Performance Path (Single-Spark → Native DS4)

This document describes the **minimum-risk** path to a credible quantized performance baseline, starting with an **existing external runtime** on **one Spark (Spark0)** and advancing toward native `ds4_on_spark` measurements.

Constraints:

- Do **not** automate large model downloads or long builds.
- Prefer read-only probes and low-cost smoke generations first.
- Record full provenance (runtime, model artifact, quant, hashes, command line, env).

## Milestone 0: First Token Stream (Quantized Single-Spark)

Canonical definition: `docs/quantized-single-spark.md`.

Success means: one command on Spark0 produces non-empty generated text from a DeepSeek V4 Flash-family **quantized artifact**, with a baseline report capturing:

- runtime provenance (source + revision, or binary hash/version)
- model provenance (source, quant, file size, sha256)
- exact command line + key env knobs
- TTFT, tokens/sec where available
- GPU snapshots + CPU RSS
- stdout/stderr + exit code
- failure mode classification when it fails

## Milestone 1: Small-Cost Repeatability

Once Milestone 0 succeeds, immediately establish repeatability without growing cost:

- Same model + runtime, same prompt, **2 runs** (cold + warm)
- `CTX=2048`, `N_TOKENS=32` (or smaller if needed)
- Confirm the baseline report contains stable provenance fields and predictable failure modes.

## Milestone 2: “Smallest Credible” Artifact Envelope

Goal: the smallest artifact that is still credible for V4 Flash behavior, for iteration speed.

- Prefer a small quant (example: `Q2_K`) for first smoke.
- If the runtime supports it, validate a second quant (example: `Q3_K_M`) with the same run shape to sanity-check quality/memory pressure deltas.
- Keep context and tokens small until memory growth behavior is characterized.

## Milestone 3: Read-Only Instrumentation (After First Success)

After the first successful run, prioritize instrumentation that does **not** require runtime modifications:

- **Per-run GPU polling**: `nvidia-smi` CSV sampled during the run.
  - The baseline scripts already support `GPU_SAMPLE=1` (default) and emit `nvidia_smi_poll.csv`.
  - Adjust `GPU_SAMPLE_INTERVAL_S` (default `1`) for higher/lower resolution.
  - The llama.cpp baseline summary derives best-effort stats from the CSV (mem min/max/delta; plus util/power percentiles when present).
- **CPU RSS**: captured by the wrapper (`max_rss_*` fields).
- **KV / memory growth proxy**: inferred from GPU polling deltas during prefill vs decode.
- **KV cache init (best-effort)**: when the runtime prints `llama_kv_cache_init` / KV buffer sizing lines, `scripts/benchmark_llamacpp_spark.sh` emits `kv_probe.json` in the artifacts dir and mirrors `kv_probe_*` summary fields (sizes are heuristic; log formats vary across forks).

Then, add runtime-exposed counters only when the runtime makes them available (do not guess flags):

- routed expert IDs / top-k scores
- expert batch sizes / queue depth
- MTP draft/accepted/rejected counters
- CUDA fallback / graph placement (best-effort): run `scripts/benchmark_llamacpp_server_sweep.py` and inspect `fattn_reservation_probe.json` + the `node_kind_*` / `sched_reserve_*` fields (see `docs/baseline-fattn-reservation.md`).
  - To include this sweep in the standard baseline report (Mac → Spark), set `LLAMA_SERVER_SWEEP=1` and provide `LLAMA_SERVER=/abs/path/on/spark/to/llama-server` when running `scripts/run_baseline_existing_runtime.sh`.
  - If the runtime exposes a Prometheus `/metrics` endpoint (for example when started with `--metrics`), set `LLAMA_SERVER_SWEEP_SCRAPE_METRICS=1` to snapshot `metrics_start.prom` and `metrics_end.prom` alongside the sweep (read-only).
- Batching/concurrency throughput sweep (expensive): run `scripts/benchmark_llamacpp_server_throughput_sweep.py` and treat `--parallel`, `-b/--batch-size`, `-ub/--ubatch-size`, prompt size, and request concurrency as first-class variables.
  - To include this sweep in the standard baseline report, set `LLAMA_SERVER_THROUGHPUT_SWEEP=1` and provide `LLAMA_SERVER=/abs/path/on/spark/to/llama-server` when running `scripts/run_baseline_existing_runtime.sh`.
  - See `docs/baseline-batching-throughput.md` and `docs/baseline-multislot-parallel2.md` (multi-slot failure probe).
- Patch presence (optional, read-only): set `LLAMA_FATTN_PATCH_PROBE=1` to run `scripts/benchmark_llamacpp_fattn_patch_probe.py` on Spark and fetch `fattn_patch_probe.json` (heuristic source scan; see `docs/baseline-fattn-reservation.md`).
- Patch presence (optional, read-only): set `LLAMA_MULTISLOT_PATCH_PROBE=1` to run `scripts/benchmark_llamacpp_multislot_patch_probe.py` on Spark and fetch `multislot_patch_probe.json` (heuristic source scan; see `docs/baseline-multislot-parallel2.md`).
- CUDA fallback / placement (one-shot, best-effort): when the runtime prints `sched_reserve:` / `__fattn__-*` placement lines during a normal `llama-cli` run, `scripts/benchmark_llamacpp_spark.sh` writes `fattn_cli_probe.json` into the fetched artifacts directory and mirrors key fields into the baseline summary (`fattn_*`, `node_kind_*`, `sched_reserve_*`). This is opportunistic and may be `NA` on forks that do not emit those lines.

The llama.cpp Spark baseline script also supports a **best-effort token trace** capture:

- If the runtime emits per-token JSON log lines (for example, `function=process_token` events), the script writes them to `token_trace.jsonl` inside the Spark artifacts directory for the run.
- This is disabled by default unless the runtime is configured to emit those events; consult `llama_cli.help.txt` in the artifacts directory and only enable logging flags that the runtime actually supports.

When token JSON is present, the llama.cpp Spark baseline script also computes **read-only** derived metrics and prints them into the `== baseline summary (approx) ==` block:

- per-token latency percentiles (ms, from local monotonic timestamps between token events)
- routed expert ID frequencies (best-effort: only if the runtime includes expert IDs in token JSON)
- routed expert top-k score summaries (best-effort: `router_top1_score_*` and `router_topk_n_*` only when token JSON includes a compatible `scores` list)
- queue depth / batch size / expert batch size summaries (best-effort: only if present in token JSON)
- MTP draft/accepted/rejected counters (best-effort: only if present in token JSON)

These derived fields are intended to be *opportunistic*: they are `NA` unless the runtime actually emits compatible keys.

## Spark0 Command Shape (No Downloads/Builds)

From the Mac:

```sh
ALLOW_RUN=1 \
RUNTIME_LABEL=v4-capable-llama \
MODEL_SOURCE='<hf-repo-or-local-note>' \
MODEL_QUANT=Q2_K \
MODEL_GGUF=/abs/path/to/model.gguf \
LLAMA_CLI=/abs/path/to/v4-capable/llama-cli \
CTX=2048 \
N_TOKENS=32 \
N_GPU_LAYERS=99 \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Wrapper variant:

```sh
MODEL_GGUF=/abs/path/to/model.gguf \
LLAMA_CLI=/abs/path/to/v4-capable/llama-cli \
MODEL_SOURCE='<hf-repo-or-local-note>' \
MODEL_QUANT=Q2_K \
scripts/run_quantized_single_spark.sh spark0@aitopatom-9ab9.local
```

Notes:

- Prompts are passed to Spark as base64 (`PROMPT_B64`) to avoid shell quoting pitfalls; the report records prompt **hash + length**, not the prompt text.
- The Spark scripts do not install packages or fetch weights; they only run when `ALLOW_RUN=1`.
- Optional inventory: set `SPARK_INVENTORY=1` on the entrypoint to record a best-effort scan for candidate `*.gguf` files + runtime binaries (read-only).

## Next: External Runtime Baselines (llama.cpp / vLLM)

Use the same `scripts/run_baseline_existing_runtime.sh` entrypoint to capture:

- llama.cpp (Spark/CUDA) baseline behavior for known-good small GGUFs
- vLLM package presence + version probe, and (when a model dir is already present) a gated generation probe

Do not treat these as correctness proofs for V4 Flash; they are operational references (drivers, CUDA, memory envelope, throughput sanity).

## Later: Native `ds4_on_spark` Measurements

Only after the external-runtime quantized single-Spark run is repeatable and instrumented:

- run `ds4_on_spark` native benchmarks on Spark0 (then TP/dual-Spark as appropriate)
- compare baseline envelopes: TTFT, decode t/s, GPU memory growth, crash modes

Keep baseline reports using `docs/baseline-template.md` structure where committed.
