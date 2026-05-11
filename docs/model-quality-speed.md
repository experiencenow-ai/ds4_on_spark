# Model Quality And Speed

Multi-model testing needs a quality axis before speed numbers are actionable.
Use three layers of evidence:

1. Public quality prior: model-card or benchmark-leaderboard results gathered
   before spending Spark time.
2. Local Spark quality: deterministic prompts/tasks run through the exact
   runtime, quantization, context length, prompt template, and decoding settings.
3. Quality/speed tradeoff: local speed plus quality, shown as quality-adjusted
   throughput and Pareto frontier status.

## Public Quality Prior

Public priors are useful for deciding what to stage, but they are not enough to
declare a winner because benchmark methods vary across vendors. Keep each source
and date in the report.

Recommended prior fields:

- `public_quality_prior`: 0-100 composite, only if enough comparable public
  numbers exist.
- `public_quality_basis`: short note, for example
  `SWE-bench Verified + Terminal-Bench 2 + MMLU-Pro`.
- `public_quality_source`: model card, leaderboard, or paper URL.

Default public-prior recipe for coding/agent use:

```text
public_quality_prior =
  average(available normalized scores from:
    SWE-bench Verified,
    Terminal-Bench 2,
    BFCL / tool calling,
    TAU / agent benchmark,
    MMLU-Pro or GPQA as a general sanity check)
```

If only one public score is available, keep it as `public_prior_only` and mark
the confidence as weak in the report.

## Local Spark Quality

Local quality is the decision score. It should be deterministic and cheap enough
to run for every serious model/quant/runtime pair.

Minimum local eval set:

- Code synthesis: small functions with unit tests.
- Patch/repo task: apply a tiny change and run the provided test.
- Tool/JSON task: produce schema-valid JSON/function-call arguments.
- Long-context retrieval: exact answer from a long prompt.
- Instruction efficiency: correct answer with a token budget cap.

Record:

- `passed_tasks`
- `total_tasks`
- `local_quality_score = 100 * passed_tasks / total_tasks`
- prompt set revision
- max input/output tokens
- temperature/top-p/top-k/repetition penalty
- exact runtime and model artifact

Do not compare a DFlash run against target-only unless both use the same prompt
set and the target-only run passed without CPU fallback or runtime errors.

## Combined Score

When no explicit `quality_score` is supplied, use:

```text
quality_score = 0.70 * local_quality_score + 0.30 * public_quality_prior
```

Fallbacks:

- local only: `quality_score = local_quality_score`
- public only: `quality_score = public_quality_prior`, marked
  `public_prior_only`
- explicit: use `quality_score` as provided and document the basis

Speed fields:

- `decode_tps`: generated tokens per second
- `prefill_tps`: prompt tokens per second
- `ttft_s`: time to first token
- `total_wall_s`: end-to-end wall time for the local eval set
- `output_tokens`: generated tokens for the eval set

Tradeoff fields:

```text
quality_adjusted_decode_tps = decode_tps * quality_score / 100
correct_task_rate = passed_tasks / total_wall_s
tokens_per_success = output_tokens / passed_tasks
wall_s_per_success = total_wall_s / passed_tasks
```

Use Pareto frontier checks for decisions: a model is dominated if another model
has both equal-or-better quality and equal-or-better speed, with one strictly
better. Keep dominated models only when they have operational advantages such as
much lower memory, simpler runtime, or better stability.

## Scorer

Use `scripts/model_quality_speed_score.py` on a CSV assembled from baseline
reports:

```sh
scripts/model_quality_speed_score.py results/model_runs.csv
scripts/model_quality_speed_score.py results/model_runs.csv --json
scripts/model_quality_speed_score.py results/model_runs.csv --speed-field correct_task_rate
```

Example CSV:

```csv
model,run_id,public_quality_prior,passed_tasks,total_tasks,decode_tps,total_wall_s,output_tokens
Ling-2.6-flash-int4,sglang-int4,61.2,8,10,40,120,1800
Qwen3.5-27B,target-only,72.4,9,10,24,160,2200
Qwen3.5-27B,DFlash,72.4,9,10,58,95,2200
```

The scorer emits:

- `quality_score`
- `quality_source`
- `quality_adjusted_decode_tps`
- `correct_task_rate`
- `tokens_per_success`
- Pareto dominated-by status

## Reporting Rule

Every multi-model baseline report should include a quality block before the speed
claim:

```text
Quality:
  public_quality_prior:
  public_quality_basis:
  local_quality_score:
  passed_tasks:
  total_tasks:
  quality_score:

Speed:
  ttft_s:
  prefill_tps:
  decode_tps:
  total_wall_s:

Tradeoff:
  quality_adjusted_decode_tps:
  correct_task_rate:
  tokens_per_success:
  dominated_by:
```

This keeps Ling token-efficiency wins, Qwen quality wins, DFlash speedups, and
DeepSeek MTP improvements on the same decision surface without pretending they
are the same mechanism.
