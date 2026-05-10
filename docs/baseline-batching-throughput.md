# Baseline: llama-server Batching + Concurrency Throughput Sweep

Goal: for DeepSeek V4 Flash-family runs on Spark0, identify which batching level maximizes **aggregate** throughput under load.

This complements the prompt-size sweep (`scripts/benchmark_llamacpp_server_sweep.py`) by treating these knobs as **first-class** experiment variables:

- `--parallel` (server slot count)
- `-b` / `--batch-size` (batch size)
- `-ub` / `--ubatch-size` (micro-batch size)
- prompt size
- request concurrency (simultaneous client requests)

This sweep is expensive: it starts resident `llama-server` instances and may reload the model for each `(parallel,batch,ubatch)` combination. Do not automate large runs without an explicit human-approved plan.

## What It Produces

When run via `scripts/run_baseline_existing_runtime.sh`, the fetched artifacts directory contains:

- `throughput_sweep.jsonl`: one JSON row per concurrency “wave”
- `throughput_sweep.md`: Markdown table summary
- `throughput_best.json`: best-performing row (by aggregate prompt tok/s, then gen tok/s)
- `throughput_best_by_concurrency.json`: best row per `concurrency` (same scoring)
- per-combo directories like `p2_b1024_ub256/` containing:
  - `llama_server.log`, `server.cmd.json`, `server.pid`
  - `fattn_reservation_probe.json` (best-effort; see `docs/baseline-fattn-reservation.md`)
  - `multislot_reservation_probe.json` (best-effort; see `docs/baseline-multislot-parallel2.md`)
  - `metrics_start.prom` / `metrics_end.prom` when `/metrics` is enabled and scraping is requested

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

Notes:

- Pick a non-default `*_PORT` to avoid colliding with any resident server.
- The script uses `--parallel` / `-b` / `-ub` by default; for forks that use different flag spellings, set `PARALLEL_FLAG`, `BATCH_FLAG`, and `UBATCH_FLAG` on Spark by wrapping them into `LLAMA_SERVER_THROUGHPUT_SWEEP_SERVER_ARGS` (or by invoking the sweep script directly on Spark).
- If model reloads are too expensive, set `LLAMA_SERVER_THROUGHPUT_SWEEP_RESTART_PER_COMBO=0` and provide exactly one `(parallel,batch,ubatch)` combination (the script enforces this).

## Interpreting Results

Each sweep “wave” reports:

- `agg_prompt_tok_s`: aggregate prompt token throughput over the wave wall time
- `agg_generated_tok_s`: aggregate decode throughput over the wave wall time

Choose the best configuration based on your target:

- Prompt-heavy workloads → maximize `agg_prompt_tok_s`
- Decode-heavy workloads → maximize `agg_generated_tok_s`
- Mixed workloads → track both and report the Pareto frontier (do not hide tradeoffs)

Always cross-check:

- `fattn_reservation_probe.json` indicates whether Flash Attention was globally disabled during reservation (invalidates the run as a clean DS4 Flash baseline).
- `multislot_reservation_probe.json` indicates whether `--parallel 2` triggered known reservation/assert failure signatures.
