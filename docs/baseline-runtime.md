# Baseline Runtime

Goal: define **reproducible** baseline runs for:

- `antirez/ds4` (Mac / Metal reference)
- `llama.cpp` on Spark (CUDA baseline)
- vLLM on Spark (reference)
- quantized DeepSeek V4 Flash on one Spark (first real token stream)
- later: `ds4_on_spark` (native DS4 Flash measurements)

This baseline track is designed to capture **exact command lines**, **model artifact requirements**, and the key metrics:

- TTFT (time to first token)
- tokens/sec (prefill + generation where possible)
- memory usage (CPU RSS + GPU memory snapshot)
- optional GPU polling during runs (`nvidia_smi_poll.csv` when `GPU_SAMPLE=1`)
- best-effort per-token trace capture when the runtime emits JSON `process_token` events (`token_trace.jsonl`)
- failure modes (exact stderr / return codes)

## Safety Gates (non-negotiable)

- Scripts **do not download model weights**.
- Scripts **do not build** upstream runtimes unless explicitly enabled.
- Scripts **do not run** inference unless explicitly enabled.
- The quantized single-Spark path is still gated: model files must already exist
  on Spark, and runtime builds/downloads need explicit approval.

Enable gates with environment variables:

- `ALLOW_FETCH=1` to `git clone` upstream repos (small; still explicit)
- `ALLOW_BUILD=1` to compile (can take minutes)
- `ALLOW_RUN=1` to run inference (can be long / expensive)

## One-command entrypoint (Mac → Spark)

Run from the Mac:

```sh
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Optional: include a **read-only** Spark inventory pass (best-effort scan for
candidate `*.gguf` files + common runtime binaries) in the same report:

```sh
SPARK_INVENTORY=1 scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Optionally include the local `antirez/ds4` Mac/Metal probe in the same report:

```sh
RUN_DS4_MACOS=1 scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

This writes a markdown report to a local output directory and includes:

- Spark identity + `nvidia-smi` snapshot
- best-effort Spark host metadata (`lscpu`, `free`, `df`, etc.)
- the exact remote `ssh` invocations used (copy/pasteable)
- (default) a copy of the remote benchmark output directories (including `nvidia_smi_poll.csv`) under `spark_llamacpp_artifacts/` and `spark_vllm_artifacts/` within the same local report directory (disable with `FETCH_REMOTE_ARTIFACTS=0`)
- llama.cpp baseline (optional build/run depending on gates)
- vLLM presence/version probe (no installs); optional gated generate probe if a model dir is already present (TTFT is best-effort via async streaming when available; otherwise reported as `NA` and you should rely on load + generation wall time)
- quantized single-Spark milestone guidance: see `docs/quantized-single-spark.md` (no downloads are automated)
- performance path narrative: see `docs/quantized-performance-path.md`

To run a quantized V4 Flash smoke test through a V4-capable llama.cpp-compatible
binary that already exists on Spark:

```sh
REMOTE_LLAMA_ENV='ALLOW_RUN=1 RUNTIME_LABEL=v4-capable-llama MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli CTX=2048 N_TOKENS=32 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

If you prefer a wrapper that enforces the canonical low-cost Milestone 0 run
shape (still no downloads/builds), use:

```sh
MODEL_GGUF=/abs/path/to/model.gguf \
LLAMA_CLI=/abs/path/to/v4-capable/llama-cli \
MODEL_SOURCE='<hf-repo-or-local-note>' \
MODEL_QUANT=Q2_K \
scripts/run_quantized_single_spark.sh spark0@aitopatom-9ab9.local
```

Use `REMOTE_BENCH_ENV` for env vars shared by both Spark benchmark scripts, or
`REMOTE_LLAMA_ENV` / `REMOTE_VLLM_ENV` to target one runtime.

These strings are parsed on the **Mac** side as `KEY=VALUE` tokens (quotes
allowed) and override the corresponding `scripts/run_baseline_existing_runtime.sh`
env vars before the SSH call. Unknown keys are ignored.

Recognized keys (non-exhaustive):

- Shared: `ALLOW_FETCH`, `ALLOW_BUILD`, `ALLOW_RUN`, `GPU_SAMPLE`, `GPU_SAMPLE_INTERVAL_S`
- Inventory: `SPARK_INVENTORY`, `INVENTORY_DIRS`, `INVENTORY_MAX_DEPTH`, `INVENTORY_MAX_FILES`
- llama.cpp: `LLAMA_DIR`, `MODEL_GGUF`, `LLAMA_CLI`, `RUNTIME_LABEL`, `MODEL_SOURCE`, `MODEL_QUANT`, `LLAMA_PROMPT`, `CTX`, `N_TOKENS`, `N_GPU_LAYERS`, `EXTRA_ARGS`
- vLLM: `VLLM_MODEL`, `VLLM_PROMPT`, `MAX_TOKENS`, `TENSOR_PARALLEL_SIZE`, `MEASURE_TTFT`

These env strings are recorded in the generated report, so do not put tokens or
other secrets in them.

## One-command entrypoint (Mac local: antirez/ds4)

Run from the Mac:

```sh
scripts/benchmark_ds4_macos.sh
```

Notes:

- If `DS4_DIR` is missing, set `ALLOW_FETCH=1` to clone `antirez/ds4` into `./upstreams/ds4` (ignored by git).
- The ds4 upstream model download step is intentionally **not** automated here; see `docs/baseline-fixtures.md`.

## Script knobs (common)

All baseline scripts share the same safety gates (these are passed through by `scripts/run_baseline_existing_runtime.sh` to remote runs for the duration of the SSH session):

- `ALLOW_FETCH=1` to clone upstream repos (code only; still explicit)
- `ALLOW_BUILD=1` to compile (can take minutes)
- `ALLOW_RUN=1` to run inference (can be long / expensive)

When using `scripts/run_baseline_existing_runtime.sh`, the model path inputs (`MODEL_GGUF`, `VLLM_MODEL`, and `LLAMA_DIR`) are also passed through to the remote benchmark scripts.

Per-script useful env vars:
- `scripts/run_baseline_existing_runtime.sh`: `OUT_ROOT`, `SSH_OPTS`, `GPU_SAMPLE`, `GPU_SAMPLE_INTERVAL_S`
- `scripts/run_baseline_existing_runtime.sh`: `FETCH_REMOTE_ARTIFACTS` (default `1`)
- `scripts/run_baseline_existing_runtime.sh`: `REMOTE_BENCH_ENV`, `REMOTE_LLAMA_ENV`, `REMOTE_VLLM_ENV`
- `scripts/run_baseline_existing_runtime.sh`: `LLAMA_DIR`, `MODEL_GGUF`, `VLLM_MODEL`, `DS4_DIR`, `DS4_MODEL_GGUF`
- `scripts/run_baseline_existing_runtime.sh`: `LLAMA_CLI`, `RUNTIME_LABEL`, `MODEL_SOURCE`, `MODEL_QUANT`, `LLAMA_PROMPT`, `CTX`, `N_TOKENS`, `N_GPU_LAYERS`, `EXTRA_ARGS`
- `scripts/run_baseline_existing_runtime.sh`: `VLLM_PROMPT`, `MAX_TOKENS`, `TENSOR_PARALLEL_SIZE`, `MEASURE_TTFT`
- `scripts/benchmark_llamacpp_spark.sh`: `GPU_SAMPLE`, `GPU_SAMPLE_INTERVAL_S`, `LLAMA_DIR`, `MODEL_GGUF`, `LLAMA_CLI`, `RUNTIME_LABEL`, `MODEL_SOURCE`, `MODEL_QUANT`, `PROMPT`, `CTX`, `N_TOKENS`, `N_GPU_LAYERS`, `EXTRA_ARGS`, `OUT_DIR`
- `scripts/benchmark_vllm_spark.sh`: `GPU_SAMPLE`, `GPU_SAMPLE_INTERVAL_S`, `VLLM_MODEL`, `PROMPT`, `MAX_TOKENS`, `TENSOR_PARALLEL_SIZE`, `MEASURE_TTFT`, `OUT_DIR`
- `scripts/benchmark_ds4_macos.sh`: `DS4_DIR`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `EXTRA_ARGS`, `OUT_DIR`

## Required Fixtures

See `docs/baseline-fixtures.md` for artifact handling and the fixture manifest template.

## Baseline Report Format

Use `docs/baseline-template.md` as the canonical structure for reports committed to this repo.
