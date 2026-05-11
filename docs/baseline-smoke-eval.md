# Baseline: vLLM Smoke Eval (Deterministic)

This note defines a tiny, deterministic local-quality smoke eval that can be run through the existing vLLM baseline probe script.

Goal: produce **automatic** `passed_tasks`, `total_tasks`, and `local_quality_score` values that can be ingested into `MODEL_RUNS_CSV` without hand-entering quality metadata for every target/DFlash run.

Non-goals:

- This is not a full benchmark suite.
- This does not measure TTFT (vLLM Python API returns after generation completes).
- This does not replace a real task set for model selection; it is a cheap correctness sanity check for “plumbing works” comparisons.

## How To Run (Mac → Spark)

Run target-only vLLM with the smoke eval enabled:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
REMOTE_VLLM_ENV='ALLOW_RUN=1 VLLM_MODEL=/abs/path/to/target_model MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 VLLM_TRUST_REMOTE_CODE=1 SMOKE_EVAL=1 SMOKE_MAX_TOKENS_PER_TASK=64' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Paired DFlash probe (target-only then DFlash under the same prompt/token knobs), with smoke eval on both:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
RUN_LABEL=qwen35-27b \
VLLM_SCOPE_TARGET=qwen_target \
VLLM_SCOPE_DFLASH=qwen_dflash \
VLLM_TARGET_ID=Qwen/Qwen3.5-27B \
VLLM_TARGET_MODEL=/abs/path/to/Qwen3.5-27B \
VLLM_DRAFT_MODEL=/abs/path/to/Qwen3.5-27B-DFlash \
MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 \
ALLOW_RUN=1 VLLM_TRUST_REMOTE_CODE=1 \
SMOKE_EVAL=1 SMOKE_MAX_TOKENS_PER_TASK=64 \
scripts/run_baseline_vllm_dflash_pair.sh spark0@aitopatom-9ab9.local
```

Notes:

- `SMOKE_EVAL=1` switches `scripts/benchmark_vllm_spark.sh` from the single-prompt probe to the deterministic smoke-eval task set.
- The smoke eval writes two extra Spark-side files under `OUT_DIR` (and they get captured in the baseline report):
  - `vllm_generate_probe.txt.smoke.jsonl` (per-task records)
  - `vllm_generate_probe.txt.smoke.md` (mini summary table)

## Task Set (Current)

The current built-in tasks are intentionally tiny and deterministic:

- `arith_23x17`: exact integer answer
- `reverse_stressed`: exact string reverse
- `kv_recall`: exact value from a short key/value list
- `json_obj`: exact JSON object match (`{"a":1,"b":[2,3]}`)
- `sort_json_array`: exact JSON array sort match (`[1,1,4,9]`)
- `kib_1024`: exact unit conversion (`1024 bytes == 1 KiB`)

Treat `local_quality_score` from this task set as a smoke signal (“did the runtime/model produce sane outputs under deterministic decoding?”), not as a ranking metric.

## CSV Ingestion Behavior

`scripts/run_baseline_existing_runtime.sh` now prefers explicit quality metadata from env vars, but if those are missing it will also ingest:

- `passed_tasks`
- `total_tasks`
- `local_quality_score`

from the remote baseline summary block (`== baseline summary (approx) ==`) when present. This lets vLLM smoke-eval runs automatically populate quality fields in `MODEL_RUNS_CSV`.

If you want to incorporate public priors into a combined `quality_score`, still set:

- `PUBLIC_QUALITY_PRIOR`
- `PUBLIC_QUALITY_BASIS`
- `PUBLIC_QUALITY_SOURCE`

and then run `scripts/model_quality_speed_score.py` on the aggregated CSV.
