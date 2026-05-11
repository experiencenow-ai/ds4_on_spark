# Baseline Runtime

Goal: define **reproducible** baseline runs for:

- `antirez/ds4` (Mac / Metal reference)
- `llama.cpp` on Spark (CUDA baseline)
- vLLM on Spark (reference)
- quantized DeepSeek V4 Flash on one Spark (first real token stream)
- Ling 2.6 Flash and Qwen-family Spark comparisons
- paired DFlash speculative probes where exact draft checkpoints exist
- later: `ds4_on_spark` (native DS4 Flash measurements)

This baseline track is designed to capture **exact command lines**, **model artifact requirements**, and the key metrics:

- TTFT (time to first token)
- tokens/sec (prefill + generation where possible)
- memory usage (CPU RSS + GPU memory snapshot)
- failure modes (exact stderr / return codes)

For multi-model comparisons (Ling/Qwen/DFlash/etc), add a quality axis before
interpreting speed. See `docs/model-quality-speed.md` and run
`scripts/model_quality_speed_score.py` on the aggregated CSV.

## Safety Gates (non-negotiable)

- Scripts **do not download model weights**.
- Scripts **do not build** upstream runtimes unless explicitly enabled.
- Scripts **do not run** inference unless explicitly enabled.
- The quantized single-Spark path is still gated: model files must already exist
  on Spark, and runtime builds/downloads need explicit approval.

Enable gates with environment variables:

- `ALLOW_FETCH=1` to `git clone` upstream repos (small; still explicit)
- `ALLOW_BUILD=1` to compile (can take minutes)
- `ALLOW_MODEL_INSPECT=1` to run a metadata-only GGUF header + tensor-key inspection pass (no model load)
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

Optional: append best-effort per-run rows to a local CSV for quality/speed scoring:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

When using `MODEL_RUNS_CSV`, you can also supply (optional) quality metadata:
`PUBLIC_QUALITY_PRIOR`, `PUBLIC_QUALITY_BASIS`, `PUBLIC_QUALITY_SOURCE`,
`PASSED_TASKS`, `TOTAL_TASKS`, `LOCAL_QUALITY_SCORE`, and `QUALITY_SCORE`.

When `MODEL_RUNS_CSV` is set, the report directory also gets best-effort
quality/speed scoring artifacts derived from the full CSV:

- `model_quality_speed_score.md` (markdown table)
- `model_quality_speed_score.json` (machine-readable rows, including Pareto `dominated_by`)

To run a quantized V4 Flash smoke test through a V4-capable llama.cpp-compatible
binary that already exists on Spark:

```sh
REMOTE_LLAMA_ENV='ALLOW_MODEL_INSPECT=1 ALLOW_RUN=1 RUNTIME_LABEL=v4-capable-llama MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli CTX=2048 N_TOKENS=32 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Use `REMOTE_BENCH_ENV` for env vars shared by both remote benchmark scripts, or
`REMOTE_LLAMA_ENV` / `REMOTE_VLLM_ENV` to target one runtime. See
`docs/quantized-single-spark.md` for the milestone definition and failure
triage. These env strings are recorded in the generated report, so do not put
tokens or other secrets in them.

If you need different `MODEL_GGUF` / `ALLOW_MODEL_INSPECT` wiring for the
inspector phase, use `REMOTE_GGUF_INSPECT_ENV` (defaults to `REMOTE_LLAMA_ENV`).

To validate a DS4-tuned MTP sidecar GGUF that already exists on Spark (no trunk
model load, and no tensor payload reads), set `REMOTE_MTP_SIDECAR_ENV` on the
Mac and `MTP_SIDECAR_GGUF` on Spark:

```sh
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

The report includes a `## MTP sidecar contract probe (Spark)` section with the
JSON output from `scripts/model_contract_probe_mtp_sidecar.py`.

If you also want a llama.cpp-side **loader gate** (optionally loads the sidecar
tensor blob into RAM via `--load-weights`, still without loading the trunk),
use the combined runner:

```sh
REMOTE_MTP_SIDECAR_ENV='ALLOW_RUN=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV='ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1 LOAD_WEIGHTS=1 MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf' \
scripts/run_mtp_sidecar_loader_probe_spark.sh spark0@aitopatom-9ab9.local
```

This combined runner also runs the pinned antirez payload fingerprint gate locally
and records it next to the report as `contract_probe_fingerprint_gate.json`.

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
- `scripts/run_baseline_existing_runtime.sh`: `VLLM_MODEL_ID` (CSV label override; avoids absolute Spark paths)
- `scripts/run_baseline_existing_runtime.sh`: `LLAMA_SCOPE`, `VLLM_SCOPE` (CSV `scope` labels; use to keep DeepSeek/Ling/Qwen/DFlash rows separate)
- `scripts/benchmark_llamacpp_spark.sh`: `LLAMA_DIR`, `LLAMA_CLI`, `RUNTIME_LABEL`, `MODEL_SOURCE`, `MODEL_QUANT`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `N_GPU_LAYERS`, `EXTRA_ARGS`, `OUT_DIR`
- `scripts/benchmark_vllm_spark.sh`: `ALLOW_FETCH`, `VLLM_MODEL`, `PROMPT`, `MAX_TOKENS`, `TENSOR_PARALLEL_SIZE`, `VLLM_TRUST_REMOTE_CODE`, `VLLM_SPECULATIVE_CONFIG_JSON`, `VLLM_EXTRA_LLM_KWARGS_JSON`, `VLLM_EXTRA_SAMPLING_KWARGS_JSON`, `OUT_DIR`
- `scripts/benchmark_ds4_macos.sh`: `DS4_DIR`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `EXTRA_ARGS`, `OUT_DIR`
- `scripts/run_baseline_vllm_dflash_pair.sh`: `VLLM_SCOPE_TARGET`, `VLLM_SCOPE_DFLASH` (CSV `scope` labels for target-only vs DFlash)

See `docs/upstream-qwen-dflash.md` for Ling, Qwen, and DFlash candidate order,
artifact sizes, and example vLLM env strings.

### vLLM target-only + DFlash wrapper

For paired Qwen+DFlash probes (and Ling/Qwen target-only runs), prefer the
wrapper script so the target-only and DFlash runs share the same prompt, token
budget, and CSV labeling:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
RUN_LABEL=qwen35-27b \
VLLM_SCOPE_TARGET=qwen_target \
VLLM_SCOPE_DFLASH=qwen_dflash \
VLLM_TARGET_ID=Qwen/Qwen3.5-27B \
VLLM_TARGET_MODEL=/abs/path/to/Qwen3.5-27B \
VLLM_DRAFT_MODEL=/abs/path/to/Qwen3.5-27B-DFlash \
scripts/run_baseline_vllm_dflash_pair.sh spark0@aitopatom-9ab9.local
```

If `VLLM_DRAFT_MODEL` is omitted, the wrapper runs target-only and exits.

Recommended first comparison order (after DeepSeek V4 Flash can generate on Spark0):

- Ling target-only (ensure `Ling-2.6-flash-int4` exists first if staged/approved)
- Qwen3.5-27B target-only, then its exact `*-DFlash` paired run
- Qwen3.6-27B target-only, then its exact `*-DFlash` paired run (watch the engine-support warning)
- Qwen3-Coder-30B-A3B-Instruct-FP8 target-only, then paired DFlash
- Qwen3.6-35B-A3B-FP8 target-only, then paired DFlash

Example: Ling target-only (no DFlash drafter known as of 2026-05-11):

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
RUN_LABEL=ling26-int4 \
VLLM_SCOPE_TARGET=ling_target \
VLLM_TARGET_ID=inclusionAI/Ling-2.6-flash-int4 \
VLLM_TARGET_MODEL=/abs/path/to/Ling-2.6-flash-int4 \
MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 \
scripts/run_baseline_vllm_dflash_pair.sh spark0@aitopatom-9ab9.local
```

Use `docs/model-quality-speed.md` and `scripts/model_quality_speed_score.py`
when comparing multiple model families. Speed claims should include
`quality_score`, `quality_adjusted_decode_tps`, and Pareto status once local
quality rows exist.

## Required Fixtures

See `docs/baseline-fixtures.md` for artifact handling and the fixture manifest template.

## Baseline Report Format

Use `docs/baseline-template.md` as the canonical structure for reports committed to this repo.
