# Baseline: llama-server Batching + Concurrency Throughput Sweep

Goal: for DeepSeek V4 Flash-family runs on Spark0, identify which batching level maximizes **aggregate** throughput under load.

Status note: this document and the companion sweep scripts were rescued from
the superseded baseline-runtime PR #27 as standalone artifacts. The baseline
wrapper supports `LLAMA_SERVER_THROUGHPUT_SWEEP=1`, fetches a tarball of the
sweep output into the local report directory, and (when `MODEL_RUNS_CSV` is set)
appends a best-decode summary row for quality/speed scoring.

This complements the prompt-size sweep (`scripts/benchmark_llamacpp_server_sweep.py`) by treating these knobs as **first-class** experiment variables:

- `--parallel` (server slot count)
- `-b` / `--batch-size` (batch size)
- `-ub` / `--ubatch-size` (micro-batch size)
- prompt size
- request concurrency (simultaneous client requests)

This sweep is expensive: it starts resident `llama-server` instances and may reload the model for each `(parallel,batch,ubatch)` combination. Do not automate large runs without an explicit human-approved plan.

## Current Spark0 Snapshot (2026-05-11)

These numbers summarize the current **single-Spark Spark0** DeepSeek V4 Flash IQ2XXS llama.cpp-fork baseline status after the Flash-Attention reservation fix and the initial multi-slot reservation fixes.

- Stable batching point (current “usable” config): `--parallel 8 -b 2048 -ub 512`.
- Aggregate decode plateaus (generated tok/s, aggregate across the server):
  - short decode: ~13.5 tok/s (observed P8/P16 plateau region)
  - 64-word decode: ~12.5 tok/s
  - 256-word decode: ~8.6 tok/s
- Prefill throughput probe (measured with `n_predict=1`): ~220–286 prompt tok/s for ~64–384 word prompts.
- Larger batches did not help: `-b 4096 -ub 1024` became runnable after the `n_ctx_seq` reserve caps, but did not improve throughput.
- HTTP overhead is not the likely bottleneck: a high-concurrency server probe (`--parallel 128 -b 1024 -ub 64`, 16-word prompt, `n_predict=8`) degraded to ~9.6 aggregate output tok/s, while direct `llama-batched-bench` `-npl 1,8,32,64,128` plateaus at ~13.5–14.2 aggregate decode tok/s.

Decision gate reminder: do **not** recommend buying additional Sparks for this llama.cpp path until single-Spark proof shows ~50–100 aggregate output tok/s, or an alternative runtime path (vLLM / expert-parallel / MTP / DFlash) shows stable scaling with quality-adjusted scoring.

## What It Produces

When run directly, or via `scripts/run_baseline_existing_runtime.sh` after the
wrapper hook is wired, the artifacts directory contains:

- `throughput_sweep.jsonl`: one JSON row per concurrency “wave”
- `throughput_sweep.md`: Markdown table summary
- `throughput_best.json`: best-performing row (scoring=`prompt`, for backward compatibility)
- `throughput_best_by_concurrency.json`: best row per `concurrency` (scoring=`prompt`, for backward compatibility)
- `throughput_best_prompt.json`: best row (maximize `agg_prompt_tok_s`)
- `throughput_best_decode.json`: best row (maximize `agg_generated_tok_s`)
- `throughput_best_total.json`: best row (maximize `agg_prompt_tok_s + agg_generated_tok_s`)
- `throughput_best_prompt_by_concurrency.json`: best row per `concurrency` (prompt scoring)
- `throughput_best_decode_by_concurrency.json`: best row per `concurrency` (decode scoring)
- `throughput_best_total_by_concurrency.json`: best row per `concurrency` (total scoring)
- Each JSON row also embeds compact reservation probes:
  - `fattn_probe` (Flash Attention reservation / placement summary)
  - `multislot_probe` (multi-slot `sched_reserve()` failure summary)
- per-combo directories like `p2_b1024_ub256/` containing:
  - `llama_server.log`, `server.cmd.json`, `server.pid`
  - `fattn_reservation_probe.json` (best-effort; see `docs/baseline-fattn-reservation.md`)
  - `multislot_reservation_probe.json` (best-effort; see `docs/baseline-multislot-parallel2.md`)
  - `metrics_start.prom` / `metrics_end.prom` plus `metrics_delta.json` / `metrics_delta.md` when `/metrics` is enabled and scraping is requested

When `MODEL_RUNS_CSV` is set and you run the sweep via `scripts/run_baseline_existing_runtime.sh`, the wrapper also appends one extra CSV row capturing the **best decode** configuration:

- `decode_tps`: `agg_generated_tok_s` from `throughput_best_decode.json`
- `prefill_tps`: `agg_prompt_tok_s` from `throughput_best_decode.json`
- `total_wall_s`: `wave_wall_s`
- `output_tokens`: `agg_generated_tokens`

Defaults:

- CSV scope: `llama_server_throughput` (override with `LLAMA_SERVER_THROUGHPUT_SCOPE`)
- CSV model label: `MODEL_SOURCE` (override with `LLAMA_SERVER_MODEL_ID`)

## Canonical Run Shape (Mac → Spark0)

```sh
ALLOW_RUN=1 \
MODEL_GGUF=/abs/path/on/spark/to/model.gguf \
LLAMA_SERVER=/abs/path/on/spark/to/llama-server \
LLAMA_SERVER_THROUGHPUT_SWEEP=1 \
LLAMA_SERVER_THROUGHPUT_SWEEP_PORT=18082 \
LLAMA_SERVER_THROUGHPUT_SWEEP_CTX=8192 \
LLAMA_SERVER_THROUGHPUT_SWEEP_PROMPT_WORDS="4096" \
LLAMA_SERVER_THROUGHPUT_SWEEP_N_PREDICT=64 \
LLAMA_SERVER_THROUGHPUT_SWEEP_CONCURRENCY="1 2 4 8" \
LLAMA_SERVER_THROUGHPUT_SWEEP_PARALLEL_VALUES="1 2" \
LLAMA_SERVER_THROUGHPUT_SWEEP_BATCH_VALUES="512 1024 2048" \
LLAMA_SERVER_THROUGHPUT_SWEEP_UBATCH_VALUES="128 256 512" \
LLAMA_SERVER_THROUGHPUT_SWEEP_SERVER_ARGS="--cache-ram -1 --fit off --no-warmup --no-webui --cache-prompt --log-verbosity 2 --metrics" \
LLAMA_SERVER_THROUGHPUT_SWEEP_SCRAPE_METRICS=1 \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Standalone Spark-side shape if the wrapper hook is not wired yet:

```sh
ALLOW_RUN=1 \
MODEL_GGUF=/abs/path/on/spark/to/model.gguf \
LLAMA_SERVER=/abs/path/on/spark/to/llama-server \
OUT_DIR=/tmp/ds4_throughput_sweep \
python3 /tmp/benchmark_llamacpp_server_throughput_sweep.py
```

Notes:

- Pick a non-default `*_PORT` to avoid colliding with any resident server.
- The script uses `--parallel` / `-b` / `-ub` by default; for forks that use different flag spellings, set `PARALLEL_FLAG`, `BATCH_FLAG`, and `UBATCH_FLAG` on Spark by wrapping them into `LLAMA_SERVER_THROUGHPUT_SWEEP_SERVER_ARGS` (or by invoking the sweep script directly on Spark).
- If model reloads are too expensive, set `LLAMA_SERVER_THROUGHPUT_SWEEP_RESTART_PER_COMBO=0` and provide exactly one `(parallel,batch,ubatch)` combination (the script enforces this).

### Presets (Convenience)

If you want a quick starting grid without typing `*_BATCH_VALUES` / `*_UBATCH_VALUES`, set:

- `LLAMA_SERVER_THROUGHPUT_SWEEP_PRESET=quick` (small grid)
- `LLAMA_SERVER_THROUGHPUT_SWEEP_PRESET=highbatch` (the documented “high batching” grid)

The preset only fills in values you did not explicitly set (so you can still override `*_BATCH_VALUES` / `*_UBATCH_VALUES` by providing them directly).

## Interpreting Results

Each sweep “wave” reports:

- `agg_prompt_tok_s`: aggregate prompt token throughput over the wave wall time
- `agg_generated_tok_s`: aggregate decode throughput over the wave wall time
- `agg_total_tok_s`: aggregate total token throughput (`prompt + decode`) over the wave wall time

Choose the best configuration based on your target:

- Prompt-heavy workloads → maximize `agg_prompt_tok_s`
- Decode-heavy workloads → maximize `agg_generated_tok_s`
- Mixed workloads → track both and report the Pareto frontier (do not hide tradeoffs); `throughput_best_total*.json` is a coarse first pass.

Always cross-check:

- `fattn_reservation_probe.json` indicates whether Flash Attention was globally disabled during reservation (invalidates the run as a clean DS4 Flash baseline).
- `multislot_reservation_probe.json` indicates whether `--parallel 2` triggered known reservation/assert failure signatures.

The sweep summary table also includes quick per-wave flags:

- `fattn_disabled` (`Y` means the server logged “Flash Attention … disabled” during reservation)
- `multislot_sched_reserve_fail` (`Y` means the server log matches known `sched_reserve()` failure signatures)
