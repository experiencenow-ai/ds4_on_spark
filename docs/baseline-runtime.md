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

This writes a markdown report to a local output directory and includes:

- Spark identity + `nvidia-smi` snapshot
- llama.cpp baseline (optional build/run depending on gates)
- vLLM presence/version probe (no installs); optional gated generate probe if a model dir is already present (TTFT is reported as `NA`; record load + generation wall time instead)

To run a quantized V4 Flash smoke test through a V4-capable llama.cpp-compatible
binary that already exists on Spark:

```sh
REMOTE_LLAMA_ENV='ALLOW_RUN=1 RUNTIME_LABEL=v4-capable-llama MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli CTX=2048 N_TOKENS=32 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Use `REMOTE_BENCH_ENV` for env vars shared by both remote benchmark scripts, or
`REMOTE_LLAMA_ENV` / `REMOTE_VLLM_ENV` to target one runtime. See
`docs/quantized-single-spark.md` for the milestone definition and failure
triage. These env strings are recorded in the generated report, so do not put
tokens or other secrets in them.

To validate a DS4-tuned MTP sidecar GGUF that already exists on Spark (no trunk
model load, and no tensor payload reads), set `REMOTE_MTP_SIDECAR_ENV` on the
Mac and `MTP_SIDECAR_GGUF` on Spark:

```sh
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

The report includes a `## MTP sidecar contract probe (Spark)` section with the
JSON output from `scripts/model_contract_probe_mtp_sidecar.py`.

After the first successful quantized run, prefer instrumentation over immediate
optimization. The next useful report should say whether the runtime can expose:

- per-token decode latency
- routed expert IDs and top-k scores
- expert batch sizes / queue depth
- MTP draft, accepted, and rejected token counters

Those fields feed the quantized high-performance path in
`docs/quantized-performance-path.md` and the replay work in
`docs/scheduler-simulator.md`.

## One-command entrypoint (Mac local: antirez/ds4)

Run from the Mac:

```sh
scripts/benchmark_ds4_macos.sh
```

Notes:

- If `DS4_DIR` is missing, set `ALLOW_FETCH=1` to clone `antirez/ds4` into `./upstreams/ds4` (ignored by git).
- The ds4 upstream model download step is intentionally **not** automated here; see `docs/baseline-fixtures.md`.

## Script knobs (common)

All baseline scripts share the same safety gates:

- `ALLOW_FETCH=1` to clone upstream repos (code only; still explicit)
- `ALLOW_BUILD=1` to compile (can take minutes)
- `ALLOW_RUN=1` to run inference (can be long / expensive)

Per-script useful env vars:

- `scripts/run_baseline_existing_runtime.sh`: `OUT_ROOT`, `SSH_OPTS`
- `scripts/run_baseline_existing_runtime.sh`: `REMOTE_BENCH_ENV`, `REMOTE_LLAMA_ENV`, `REMOTE_VLLM_ENV`, `REMOTE_MTP_SIDECAR_ENV`, `REMOTE_MTP_SIDECAR_ARGS`
- `scripts/benchmark_llamacpp_spark.sh`: `LLAMA_DIR`, `LLAMA_CLI`, `RUNTIME_LABEL`, `MODEL_SOURCE`, `MODEL_QUANT`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `N_GPU_LAYERS`, `EXTRA_ARGS`, `OUT_DIR`
- `scripts/benchmark_vllm_spark.sh`: `VLLM_MODEL`, `PROMPT`, `MAX_TOKENS`, `TENSOR_PARALLEL_SIZE`, `OUT_DIR`
- `scripts/benchmark_ds4_macos.sh`: `DS4_DIR`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `EXTRA_ARGS`, `OUT_DIR`

## Required Fixtures

See `docs/baseline-fixtures.md` for artifact handling and the fixture manifest template.

## Baseline Report Format

Use `docs/baseline-template.md` as the canonical structure for reports committed to this repo.
