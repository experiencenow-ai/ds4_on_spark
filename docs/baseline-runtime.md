# Baseline Runtime

Goal: define **reproducible** baseline runs for:

- `antirez/ds4` (Mac / Metal reference)
- `llama.cpp` on Spark (CUDA baseline)
- vLLM on Spark (reference)
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

Enable gates with environment variables:

- `ALLOW_FETCH=1` to `git clone` upstream repos (small; still explicit)
- `ALLOW_BUILD=1` to compile (can take minutes)
- `ALLOW_RUN=1` to run inference (can be long / expensive)

## One-command entrypoint (Mac → Spark)

Run from the Mac:

```sh
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Optionally include the local `antirez/ds4` Mac/Metal probe in the same report:

```sh
RUN_DS4_MACOS=1 scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

This writes a markdown report to a local output directory and includes:

- Spark identity + `nvidia-smi` snapshot
- best-effort Spark host metadata (`lscpu`, `free`, `df`, etc.)
- llama.cpp baseline (optional build/run depending on gates)
- vLLM presence/version probe (no installs); optional gated generate probe if a model dir is already present (TTFT is reported as `NA`; record load + generation wall time instead)

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

Per-script useful env vars:

- `scripts/run_baseline_existing_runtime.sh`: `OUT_ROOT`, `SSH_OPTS`
- `scripts/benchmark_llamacpp_spark.sh`: `LLAMA_DIR`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `N_GPU_LAYERS`, `EXTRA_ARGS`, `OUT_DIR`
- `scripts/benchmark_vllm_spark.sh`: `VLLM_MODEL`, `PROMPT`, `MAX_TOKENS`, `TENSOR_PARALLEL_SIZE`, `OUT_DIR`
- `scripts/benchmark_ds4_macos.sh`: `DS4_DIR`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `EXTRA_ARGS`, `OUT_DIR`

## Required Fixtures

See `docs/baseline-fixtures.md` for artifact handling and the fixture manifest template.

## Baseline Report Format

Use `docs/baseline-template.md` as the canonical structure for reports committed to this repo.
