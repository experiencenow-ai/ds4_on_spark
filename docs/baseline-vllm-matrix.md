# Baseline: vLLM Matrix Runner (Ling/Qwen/DFlash)

Use this when you have multiple Ling/Qwen target checkpoints staged on Spark0
and want to run target-only and paired DFlash probes with:

- the same prompt
- the same token budget
- consistent `MODEL_RUNS_CSV` labeling (`scope`, `run_id`)

The entrypoint is:

```sh
scripts/run_baseline_vllm_matrix.sh <spark-ssh-target> <matrix.tsv>
```

If you want a single local output directory with per-row reports plus a single
scored summary, use:

```sh
scripts/run_baseline_vllm_matrix_bundle.sh <spark-ssh-target> <matrix.tsv>
```

This wrapper calls `scripts/run_baseline_vllm_dflash_pair.sh` for each row.
Spark-side gates still apply (`ALLOW_RUN`, `ALLOW_FETCH`).
It also writes a self-contained bundle report (`baseline_vllm_matrix_bundle.md`)
into the output directory with the exact command line and a copy/paste-ready
scored summary block.

Matrix error handling:

- Default: `MATRIX_CONTINUE_ON_ERROR=1` continues after a failing row (records the row rc in stdout/stderr).
- Set `MATRIX_CONTINUE_ON_ERROR=0` to fail fast on the first non-zero row.

## Defaults (cost control)

The matrix runner defaults these to keep Ling/Qwen runs clean:

- `SKIP_LLAMA=1`
- `SKIP_GGUF_INSPECT=1`
- `SKIP_MTP_SIDECAR=1`

Override any of them if you intentionally want the extra sections in the report.

Quality defaults (recommended for multi-model comparisons):

- `SMOKE_EVAL=1` (default): run the deterministic smoke task set so `passed_tasks`, `total_tasks`, and `local_quality_score` are populated for scoring.
- `SMOKE_MAX_TOKENS_PER_TASK=64` (default): token cap per task in the smoke set.

Set `SMOKE_EVAL=0` to run the single-prompt probe only (speed plumbing, no automatic local quality).

## Example invocation

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
PROMPT='Explain Redis streams in one paragraph.' \
MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 \
SMOKE_EVAL=1 SMOKE_MAX_TOKENS_PER_TASK=64 \
ALLOW_RUN=1 ALLOW_FETCH=0 \
scripts/run_baseline_vllm_matrix.sh spark0@aitopatom-9ab9.local /path/to/vllm_matrix.tsv
```

Bundle (recommended for multi-row comparisons; creates its own `model_runs.csv`
inside the bundle dir):

```sh
BUNDLE_LABEL=qwen-ling-ladder \
PROMPT='Explain Redis streams in one paragraph.' \
MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 \
SMOKE_EVAL=1 SMOKE_MAX_TOKENS_PER_TASK=64 \
ALLOW_RUN=1 ALLOW_FETCH=0 \
scripts/run_baseline_vllm_matrix_bundle.sh spark0@aitopatom-9ab9.local /path/to/vllm_matrix.tsv
```

Notes:

- Keep `PROMPT`, `MAX_TOKENS`, and `TENSOR_PARALLEL_SIZE` constant across the matrix.
- The vLLM probe emits best-effort speculative-decoding counters (accepted/draft tokens, mean accept length) when `VLLM_SPECULATIVE_CONFIG_JSON` is set and the installed vLLM exposes `llm.get_metrics()`.
- For multi-model comparisons, fill out quality metadata (`PUBLIC_QUALITY_PRIOR`,
  `PUBLIC_QUALITY_BASIS`, `PUBLIC_QUALITY_SOURCE`, `PASSED_TASKS`, `TOTAL_TASKS`,
  `LOCAL_QUALITY_SCORE`, `QUALITY_SCORE`) and run `scripts/model_quality_speed_score.py`.
- The bundle wrapper also emits `model_quality_speed_scored_summary.txt` (per-run `key=value` blocks including Pareto `dominated_by`) for copy/paste into baseline docs.
- If your checkout is a worktree that cannot write `FETCH_HEAD`, create a local git shim (`scripts/run_baseline_git_shim.sh`) and pass `DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=.` so the bundle report records the correct `ds4_on_spark` commit.
- Do not download large model weights unless explicitly approved.
- These wrappers default to `ALLOW_RUN=0` so nothing executes on Spark unless you opt in.

## Matrix TSV format

Tab-separated values with 6 required columns plus 3 optional per-row quality-metadata columns:

```text
run_label	scope_target	scope_dflash	target_id	target_model_dir	draft_model_dir	public_quality_prior	public_quality_basis	public_quality_source
```

Rules:

- Lines starting with `#` are ignored.
- A header row starting with `run_label` is ignored.
- `draft_model_dir` may be empty to run target-only.
- `scope_target` and `scope_dflash` may be empty; defaults are `vllm_target` and `vllm_dflash`.
- Use absolute Spark paths for `target_model_dir` / `draft_model_dir`.
- Optional `public_quality_*` columns override the global `PUBLIC_QUALITY_*` env vars for that row.

Template:

```text
# run_label	scope_target	scope_dflash	target_id	target_model_dir	draft_model_dir	public_quality_prior	public_quality_basis	public_quality_source
ling26-int4	ling_target		inclusionAI/Ling-2.6-flash-int4	/abs/path/to/Ling-2.6-flash-int4			
qwen35-4b	qwen_target	qwen_dflash	Qwen/Qwen3.5-4B	/abs/path/to/Qwen3.5-4B	/abs/path/to/z-lab/Qwen3.5-4B-DFlash			
qwen35-9b	qwen_target	qwen_dflash	Qwen/Qwen3.5-9B	/abs/path/to/Qwen3.5-9B	/abs/path/to/z-lab/Qwen3.5-9B-DFlash			
qwen35-27b	qwen_target	qwen_dflash	Qwen/Qwen3.5-27B	/abs/path/to/Qwen3.5-27B	/abs/path/to/z-lab/Qwen3.5-27B-DFlash			
qwen36-27b	qwen_target	qwen_dflash	Qwen/Qwen3.6-27B	/abs/path/to/Qwen3.6-27B	/abs/path/to/z-lab/Qwen3.6-27B-DFlash			
qwen3-coder-30b-a3b	qwen_target	qwen_dflash	Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8	/abs/path/to/Qwen3-Coder-30B-A3B-Instruct-FP8	/abs/path/to/z-lab/Qwen3-Coder-30B-A3B-DFlash			
qwen36-35b-a3b	qwen_target	qwen_dflash	Qwen/Qwen3.6-35B-A3B-FP8	/abs/path/to/Qwen3.6-35B-A3B-FP8	/abs/path/to/z-lab/Qwen3.6-35B-A3B-DFlash			
```

Repo template file: `fixtures/baseline/vllm_matrix_template.tsv`.

Spark0 ladder template (recommended starting point; fill in staged paths):

- `fixtures/baseline/vllm_ling_qwen_dflash_ladder_spark0.tsv`

## Recommended measurement order

Follow `docs/upstream-qwen-dflash.md` for the pinned target/draft commits and
the staging ladder. After any Ling result, ensure the `Ling-2.6-flash-int4`
target-only row exists (staged or explicitly approved download) before moving
to Qwen 27B or larger targets.
