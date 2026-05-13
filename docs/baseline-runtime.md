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

For llama.cpp-style runs, the Spark-side benchmark script also records the `llama_print_timings` wall-clock breakdown (when the runtime supports timings flags) into the baseline summary key/value block:

- `load_time_s`, `sample_time_s`, `prompt_eval_s`, `eval_time_s`, `total_time_s`

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
- `ds4_on_spark` commit hash (best-effort; prefers `DS4_GIT_DIR`/`DS4_GIT_WORK_TREE` when set, otherwise checks `.codex_git`, `git-local/baseline-runtime.git`, and `.git2/.git` when present)

If the Codex-provided worktree cannot write `FETCH_HEAD` during `git fetch`, use the local `.codex_git` shim helper: `docs/baseline-git-shim.md`.
- llama.cpp baseline (optional build/run depending on gates)
- vLLM presence/version probe (no installs); optional gated generate probe if a model dir is already present (TTFT is reported as `NA`; record load + generation wall time instead)
- optional OpenAI-compatible streaming benchmark (true TTFT + decode throughput) for endpoints that already exist on Spark (for example vLLM OpenAI server or AEON containers); gated via `SKIP_OPENAI_STREAM=0` and `REMOTE_OPENAI_STREAM_ENV`

Optional: append best-effort per-run rows to a local CSV for quality/speed scoring:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

When using `MODEL_RUNS_CSV`, you can also supply (optional) quality metadata:
`PUBLIC_QUALITY_PRIOR`, `PUBLIC_QUALITY_BASIS`, `PUBLIC_QUALITY_SOURCE`,
`PASSED_TASKS`, `TOTAL_TASKS`, `LOCAL_QUALITY_SCORE`, and `QUALITY_SCORE`.
When any of these fields are set, the local report includes a `Quality Metadata (Local)`
section to make it harder to forget which quality numbers were used for a comparison.

For vLLM runs, you can also set `SMOKE_EVAL=1` (and optionally `SMOKE_MAX_TOKENS_PER_TASK=64`) to run a tiny deterministic smoke-eval task set that emits `passed_tasks`, `total_tasks`, and `local_quality_score` into the remote baseline summary block; the baseline wrapper will ingest those values into `MODEL_RUNS_CSV` when the corresponding env vars are not set. See `docs/baseline-smoke-eval.md`.

When the remote baseline summary includes speculative-decoding metadata (for example from vLLM DFlash runs), the wrapper also records `speculative_method`, `speculative_draft_model`, and `speculative_num_speculative_tokens` into `MODEL_RUNS_CSV`.

When `LLAMA_SERVER_THROUGHPUT_SWEEP=1` is enabled (see `docs/baseline-batching-throughput.md`) and `MODEL_RUNS_CSV` is set, the wrapper appends an additional CSV row for the sweep’s **best decode** configuration (mapping `agg_generated_tok_s` → `decode_tps`, `agg_prompt_tok_s` → `prefill_tps`, `wave_wall_s` → `total_wall_s`, and `agg_generated_tokens` → `output_tokens`). Use `LLAMA_SERVER_THROUGHPUT_SCOPE` (default `llama_server_throughput`) to keep these rows separate from the single-prompt llama.cpp baseline.

When `MODEL_RUNS_CSV` is set, the report directory also gets best-effort
quality/speed scoring artifacts derived from the full CSV:

- `model_quality_speed_score.md` (markdown table)
- `model_quality_speed_score.json` (machine-readable rows, including Pareto `dominated_by`)
- `model_quality_speed_scored_summary.txt` (key=value block per run_id, for copy/paste into baseline reports)

To run a quantized V4 Flash smoke test through a V4-capable llama.cpp-compatible
binary that already exists on Spark:

```sh
REMOTE_LLAMA_ENV='ALLOW_MODEL_INSPECT=1 ALLOW_RUN=1 RUNTIME_LABEL=v4-capable-llama MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli CTX=512 N_TOKENS=8 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Equivalent milestone wrapper (same run shape, fewer knobs to type):

```sh
MODEL_SOURCE=<hf-repo-or-local-note> MODEL_QUANT=Q2_K MODEL_GGUF=/abs/path/to/model.gguf LLAMA_CLI=/abs/path/to/llama-cli RUNTIME_LABEL=v4flash-external \
scripts/run_quantized_single_spark.sh spark0@aitopatom-9ab9.local
```

Smallest-staged V4 Flash GGUF wrapper (Spark0; auto-selects the smallest trunk
GGUF by file size, excluding MTP/DFlash sidecars):

```sh
ALLOW_RUN=1 \
scripts/run_quantized_single_spark0_smallest_v4flash_external.sh spark0@aitopatom-9ab9.local
```

Smallest-credible V4 Flash GGUF wrapper (Spark0; same auto-selection, but also
defaults an include filter to avoid selecting `IQ1_*` tiers):

```sh
ALLOW_RUN=1 \
scripts/run_quantized_single_spark0_smallest_credible_v4flash_external.sh spark0@aitopatom-9ab9.local
```

Set `MODEL_GGUF_INCLUDE_EGREP=""` to disable the include filter.

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

## Ling/Qwen/DFlash ladder (Spark0; vLLM)

Once vLLM is available on Spark0 (or you are using a pinned container that
bundles it), use the ladder matrix runner so Ling/Qwen target-only and paired
DFlash probes share the same prompt/token settings and a single scored summary.

Entry point (recommended; runs an env probe first, then the ladder bundle):

```sh
ALLOW_RUN=1 ALLOW_FETCH=0 \
scripts/run_baseline_vllm_ling_qwen_dflash_ladder_spark0.sh spark0@aitopatom-9ab9.local
```

See `docs/baseline-vllm-matrix.md` and `docs/upstream-qwen-dflash.md` for the
TSV format, pinned candidate order, and metric separation (`scope` labels).
- expert batch sizes / queue depth
- MTP draft, accepted, and rejected token counters

Those fields feed the quantized high-performance path in
`docs/quantized-performance-path.md` and the replay work in
`docs/scheduler-simulator.md`.

## One-command entrypoint (Mac local: antirez/ds4)

Run from the Mac:

```sh
scripts/run_baseline_ds4_macos.sh
```

Notes:

- If `DS4_DIR` is missing, set `ALLOW_FETCH=1` to clone `antirez/ds4` into `./upstreams/ds4` (ignored by git).
- The ds4 upstream model download step is intentionally **not** automated here; see `docs/baseline-fixtures.md`.

## One-command entrypoint (Spark remote: antirez/ds4)

Run from the Mac after `antirez/ds4` and a DS4-compatible GGUF are already
staged on the Spark host:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
DS4_DIR=/remote/path/to/ds4 \
MODEL_GGUF=/remote/path/to/ds4flash.gguf \
PROMPT="Explain Redis streams in one paragraph." \
CTX=32768 \
N_TOKENS=256 \
EXTRA_ARGS="--nothink" \
ALLOW_RUN=1 \
scripts/run_baseline_antirez_ds4_spark.sh spark0@aitopatom-9ab9.local
```

Use this to compare native `antirez/ds4` CUDA/Spark performance against the
current llama.cpp/vLLM Spark rows. Keep `PROMPT`, `CTX`, `N_TOKENS`, thinking
mode, fixture hash, and quality-task metadata aligned before making a
quality/speed claim.

## Script knobs (common)

All baseline scripts share the same safety gates:

- `ALLOW_FETCH=1` to clone upstream repos (code only; still explicit)
- `ALLOW_BUILD=1` to compile (can take minutes)
- `ALLOW_RUN=1` to run inference (can be long / expensive)

Per-script useful env vars:

- `scripts/run_baseline_existing_runtime.sh`: `OUT_ROOT`, `OUT_DIR_OVERRIDE` (optional: force a deterministic local output directory), `SSH_OPTS`
- `scripts/run_baseline_existing_runtime.sh`: `REMOTE_BENCH_ENV`, `REMOTE_LLAMA_ENV`, `REMOTE_VLLM_ENV`, `REMOTE_OPENAI_STREAM_ENV`, `REMOTE_MTP_SIDECAR_ENV`, `REMOTE_MTP_SIDECAR_ARGS`
- `scripts/run_baseline_existing_runtime.sh`: `VLLM_MODEL_ID` (CSV label override; avoids absolute Spark paths)
- `scripts/run_baseline_existing_runtime.sh`: `LLAMA_SCOPE`, `VLLM_SCOPE`, `OPENAI_STREAM_SCOPE` (CSV `scope` labels; use to keep DeepSeek/Ling/Qwen/DFlash rows separate)
- `scripts/run_baseline_existing_runtime.sh`: `OPENAI_STREAM_MODEL_ID` (CSV label override; avoids server-specific model aliases)
- `scripts/run_baseline_existing_runtime.sh`: `SKIP_GGUF_INSPECT`, `SKIP_LLAMA`, `SKIP_MTP_SIDECAR`, `SKIP_VLLM`, `SKIP_OPENAI_STREAM` (skip irrelevant probes for faster multi-model loops)
- `scripts/run_baseline_existing_runtime.sh`: `REQUIRE_GGUF_TRUNK_COMPLETE=1` (optional: fail unless `remote_gguf_inspect_stdout.txt` reports `trunk_contract.complete=true`)
- `scripts/run_baseline_existing_runtime.sh`: `FETCH_LLAMA_OUT_DIR=1` (opt-in: fetch the remote llama.cpp runner `out_dir` tarball to preserve `fattn_cli_probe.json` + raw logs locally)
- `scripts/run_baseline_ds4_macos.sh`: `OUT_ROOT`, `RUN_LABEL`, `MODEL_RUNS_CSV`, `DS4_SCOPE`, `DS4_MODEL_ID`, `ALLOW_FETCH`, `ALLOW_BUILD`, `ALLOW_RUN`, `DS4_DIR`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `EXTRA_ARGS`
- `scripts/run_baseline_antirez_ds4_spark.sh`: `OUT_ROOT`, `RUN_LABEL`, `MODEL_RUNS_CSV`, `DS4_SCOPE`, `DS4_MODEL_ID`, `ALLOW_FETCH`, `ALLOW_BUILD`, `ALLOW_RUN`, remote `DS4_DIR`, remote `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `EXTRA_ARGS`, `SSH_OPTS`
- `scripts/benchmark_llamacpp_spark.sh`: `LLAMA_DIR`, `LLAMA_CLI`, `RUNTIME_LABEL`, `MODEL_SOURCE`, `MODEL_QUANT`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `N_GPU_LAYERS`, `EXTRA_ARGS`, `OUT_DIR`
- `scripts/benchmark_vllm_spark.sh`: `ALLOW_FETCH`, `VLLM_MODEL`, `PROMPT`, `MAX_TOKENS`, `TENSOR_PARALLEL_SIZE`, `VLLM_TRUST_REMOTE_CODE`, `VLLM_SPECULATIVE_CONFIG_JSON`, `VLLM_EXTRA_LLM_KWARGS_JSON`, `VLLM_EXTRA_SAMPLING_KWARGS_JSON`, `OUT_DIR`
- `scripts/benchmark_openai_chat_stream.py`: `OPENAI_CHAT_ENDPOINT`, `OPENAI_MODEL`, `OPENAI_API_KEY`, `BENCH_THINKING`, `OPENAI_STREAM_CONCURRENCY`, `OPENAI_STREAM_TIMEOUT_S`, `OPENAI_STREAM_MAX_PROMPTS`, `OUT_DIR`
- `scripts/benchmark_ds4_macos.sh`: `DS4_DIR`, `MODEL_GGUF`, `PROMPT`, `CTX`, `N_TOKENS`, `EXTRA_ARGS`, `OUT_DIR`
- `scripts/run_baseline_vllm_dflash_pair.sh`: `VLLM_SCOPE_TARGET`, `VLLM_SCOPE_DFLASH` (CSV `scope` labels for target-only vs DFlash)
- `scripts/run_baseline_vllm_matrix.sh`: tab-separated matrix file runner for repeated target-only + DFlash probes with shared prompt/token settings

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

### vLLM matrix runner (recommended for Qwen/Ling ladders)

If you have multiple targets already staged on Spark0 and want the same prompt,
token budget, and CSV labeling across all runs, use the matrix wrapper:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
PROMPT='Explain Redis streams in one paragraph.' \
MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 \
scripts/run_baseline_vllm_matrix.sh spark0@aitopatom-9ab9.local /path/to/vllm_matrix.tsv
```

The matrix runner defaults to `SKIP_LLAMA=1`, `SKIP_GGUF_INSPECT=1`, and
`SKIP_MTP_SIDECAR=1` because Ling/Qwen/DFlash comparisons do not benefit from
DeepSeek-specific probes. See `docs/baseline-vllm-matrix.md` for a template and
the recommended measurement order.

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
