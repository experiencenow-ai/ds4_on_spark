# Entropy Buffers (Centaur/DS4 metrics track)

This track defines **measurable entropy metrics** for the Centaur/DS4 multi-model workflow and provides **deterministic** tools that summarize entropy from mixed JSONL benchmark + judge logs.

Goals:

- Quantify *coverage* (task/prompt diversity) and *degeneracy* (duplicates/reuse).
- Detect judge/pairwise imbalance (label skew, disagreement).
- Recommend the **next task batch** that increases *useful* coverage without injecting random noise.

Non-goals:

- No model downloads or inference. This is analysis-only tooling.
- No tokenizer dependencies; token/n-gram metrics are whitespace/regex based.

## Canonical record schema (JSONL)

The tools accept loosely-shaped records, but work best with these canonical forms.

### Task runs (`type="task_run"`)

One record per model output for a task.

```json
{
  "type": "task_run",
  "run_id": "baseline-20260511-spark0",
  "task_id": "math.add.001",
  "task_family": "math",
  "prompt_template_id": "cot.v1",
  "model_id": "dsv4-flash",
  "prompt": "…",
  "output": "…",
  "answer": "C",
  "buffer_id": "entropy.v1",
  "buffer_item_id": "entropy.v1:math.add.001:cot.v1",
  "input_tokens": 1234,
  "output_tokens": 128,
  "wall_ms": 2500
}
```

Notes:

- `answer` is optional but unlocks answer-option diversity metrics.
- `buffer_id` / `buffer_item_id` are optional but unlock reuse metrics.

### Pairwise judge records (`type="judge_pair"`)

One record per judge decision comparing two candidates.

```json
{
  "type": "judge_pair",
  "judge_id": "gpt-judge.v1",
  "item_id": "math.add.001|cot.v1|a=dsv4|b=ling",
  "task_id": "math.add.001",
  "task_family": "math",
  "prompt_template_id": "cot.v1",
  "a_model_id": "dsv4-flash",
  "b_model_id": "ling-2.6",
  "label": "a",
  "rationale": "…",
  "buffer_id": "entropy.v1"
}
```

`label` is one of:

- `"a"`, `"b"` (winner)
- `"tie"`
- `"invalid"` (judge could not evaluate; still tracked for imbalance)

To measure **disagreement**, multiple `judge_pair` records may share the same `item_id` (different `judge_id`).

### Compact judge-elo records (`schema="ds4_pairwise_judge_record_v1"`)

The entropy tools also accept the compact record envelope used by the judge-ELO loop:

```json
{
  "schema": "ds4_pairwise_judge_record_v1",
  "pair_id": "pair.mini.001",
  "model_a": "dsv4-flash",
  "model_b": "ling-2.6",
  "parse_valid": true,
  "winner": "A",
  "margin": 2,
  "score_a": 8,
  "score_b": 6,
  "reason": "A follows instructions and is more correct.",
  "train_hint": "Fix key factual errors; keep the format strict.",
  "tags": ["format","factuality"],
  "judge_model": "judge.v1",
  "tokens": { "judge_in": 128, "judge_out": 64 },
  "latency_ms": { "judge": 1500 }
}
```

Mapping:

- `pair_id` -> `item_id`
- `model_a` / `model_b` -> `a_model_id` / `b_model_id`
- `parse_valid=false` -> `label="invalid"`

Optional but recommended:

- `task_id`, `task_family`, `prompt_template_id` (improves slice reports; disagreement-by-task is otherwise coarse)
- `tokens.judge_in` / `tokens.judge_out` and `latency_ms.judge` (tracks judge budget compliance + latency distribution)

## Entropy metrics

The scripts compute:

- **Task diversity**: unique counts + Shannon entropy over `task_id` and `task_family`.
- **Task-template diversity**: unique counts + entropy over `task_id|prompt_template_id` pairs (useful for spotting repeated reruns of the same task+template).
- **Prompt template diversity**: unique counts + entropy over `prompt_template_id`.
- **Token / n-gram distribution** (approx): prompt/output word uni/bi/tri stats + top n-grams + repetition heuristics.
- **Character n-gram distribution** (approx): prompt/output normalized char 3-grams (alnum-only) + entropy + tops.
- **Distinct-n** (approx): `distinct_1/2/3` for prompt/output word n-grams (unique / total).
- **Length distributions**: prompt/output chars + words (min/max/mean/p50/p90).
- **Runtime / throughput** (optional): `input_tokens`, `output_tokens`, `wall_ms`, plus derived `output_tok_per_s`, `total_tok_per_s`, and `ms_per_output_token`.
  - Also reports instrumentation coverage rates: `input_tokens_present_task_run_rate`, `output_tokens_present_task_run_rate`, and `wall_ms_present_task_run_rate`.
- **Answer option diversity**: distribution/entropy over `answer` (or extracted answer) when present.
  - Also reports `answer.source_counts` and extraction rates to diagnose missing/ambiguous answers.
- **Judge label balance**: label histogram + entropy; includes `label_balance_ab` (1.0 is perfectly balanced A/B, 0.0 is fully one-sided) and `label_imbalance_ab` (the complement) plus per-model-pair breakdowns.
- **Judge slice diagnostics**: top imbalance/disagreement slices by `prompt_template_id`, `task_family`, and `task_family|prompt_template_id` to spot systemic judge skew or instability.
- **Tag diversity** (optional): entropy over `tags` when present on task/judge records.
- **Disagreement rate**: for each `item_id`, fraction of non-majority labels across judges; aggregated mean (all labels) plus `a/b`-only decided disagreement.
  - The report also includes `tie_rate` and `invalid_rate` to help debug judge stability.
- **Judge budget / stability stats** (when present): `parse_valid_rate`, `judge_in_tokens`, `judge_out_tokens`, `judge_latency_ms`, plus `judge_out_budget_le_target_rate` (default target = 64).
  - Also reports slice-join coverage rates for judge records: `task_family_nonempty_judge_pair_rate`, `prompt_template_id_nonempty_judge_pair_rate`, and `task_family_template_pair_nonempty_judge_pair_rate`.
- **Duplicate-output rate**: exact + normalized output duplicates (and prompt duplicates when present), plus per-`task_id|prompt_template_id` duplicate rates (summary + top repeated pairs).
- **Duplicate-output concentration**: top normalized-output dup rates by `prompt_template_id` and by `task_family|prompt_template_id` to spot template-level collapse.
- **Per-model degeneracy**: top normalized-output duplicate rates and useful-novelty flagged rates by `model_id`.
- **Buffer reuse**: how often `buffer_item_id` repeats (and how concentrated usage is).
  - Also reports logging coverage rates (`buffer_id_nonempty_task_run_rate`, `buffer_item_id_nonempty_task_run_rate`) plus `buffer_id` concentration (`buffer_id_hhi`, `buffer_id_entropy_bits`, `buffer_id_top`).
- **Useful-novelty filters**: deterministic heuristics that flag “novel but useless” outputs (e.g., extreme repetition).
  - Includes prompt-echo and line-repetition heuristics to catch “coverage” that is actually noise.
  - Also reports top flagged-rate slices by `prompt_template_id`, `task_family`, and `task_family|prompt_template_id`.
- **Run slices** (optional): if `run_id` is present on `task_run` records, the report includes per-run coverage/duplicate/noise summaries and “top runs” to quickly spot regressions.

## Tools

### Summarize entropy from JSONL

```bash
python3 scripts/entropy_buffer_metrics.py \
  --in-jsonl fixtures/entropy-buffer/records_mini.jsonl \
  --out-json /tmp/entropy_metrics.json \
  --out-md /tmp/entropy_metrics.md
```

### Recommend next tasks (coverage maximization)

```bash
python3 scripts/entropy_buffer_recommend.py \
  --history-jsonl fixtures/entropy-buffer/records_mini.jsonl \
  --candidates-jsonl fixtures/entropy-buffer/candidates_mini.jsonl \
  --avoid-seen-task-id \
  --max-per-family 10 \
  --max-per-template 10 \
  --out-json /tmp/entropy_recommendations.json
```

Notes:

- If candidate records include `tags`, the recommender gives a small bonus to underrepresented tags in addition to `task_family`/`prompt_template_id` coverage.
- If candidate records include an `answer`/`final_answer` (or an `output` with an extractable answer), the recommender can reward **answer-option diversity** via `--answer-weight` (set to `0` to disable).
- If candidate records include `prompt`, the recommender can reward **input lexical diversity** (approx) via:
  - `--prompt-word-weight` (word unigram entropy gain) and `--prompt-trigram-weight` (word 3-gram entropy gain).
  - `--prompt-word-limit` / `--prompt-trigram-limit` to cap per-record feature fanout (set to `0` to disable limits).
- If candidate records include `buffer_item_id`, the recommender can reward **new buffer items** to avoid reuse concentration:
  - Use `--avoid-seen-buffer-item-id` to hard-exclude previously-used `buffer_item_id`s.
  - Tune weighting with `--buffer-id-weight` / `--buffer-item-weight` (set to `0` to disable).
- The recommender also applies a small **penalty** for candidates whose `prompt_template_id` (or `task_family|prompt_template_id`) has a high historical useful-novelty flagged rate or a high historical normalized-output duplicate rate.
  - Tune with `--noise-weight` / `--dup-weight`, or hard-filter with `--max-noise-rate` / `--max-dup-rate`.
- If history includes `judge_pair` / `ds4_pairwise_judge_record_v1` records with `task_family` + `prompt_template_id`, the recommender can optionally penalize slices that are historically unstable for judging:
  - Tune with `--judge-disagree-weight`, `--judge-invalid-weight`, `--judge-tie-weight`, and `--judge-imbalance-weight` (all default to `0`/disabled).
- The output JSON includes a `predicted` block showing:
  - `coverage_before` / `coverage_after`: entropy stats if you add the selected batch to history (count-only; deterministic).
  - `coverage_delta`: entropy deltas per dimension (useful for comparing parameter sweeps).
  - `selected_history_noise_rate_mean` / `selected_history_dup_rate_mean`: expected slice-level penalties for the chosen batch.
  - `selected_history_judge_*_mean`: expected judge-stability penalty components for the chosen batch (rates only; weights are in `meta`).

## Integration notes

- **Judge ELO loop**: should emit `judge_pair` records with stable `item_id`, `a_model_id`, `b_model_id`, and `label`. The entropy tools do not compute ELO; they compute *balance* and *disagreement* that affect ELO stability.
- **Baseline runtime loop**: should emit `task_run` records with `task_id`, `prompt_template_id`, and `output` (plus optional token/time fields). The entropy tools treat token/time as optional metadata and focus on coverage/degeneracy.
  - If you have `tags`, include them for better coverage accounting.

## Risks / limitations

- Token/n-gram metrics are approximate (not model-tokenizer accurate).
- “Useful novelty” is heuristic; treat flags as triage signals, not ground truth.
