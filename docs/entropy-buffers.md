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
- `useful_novelty_flags` / `useful_novelty_flagged` are optional; `scripts/entropy_buffer_filter.py` can add them deterministically for auditability.
- Token/latency instrumentation can also be provided in nested form:
  - `tokens: {prompt, completion}` or `tokens: {in, out}` (aliases supported)
  - `latency_ms: {total}` or `latency_ms: {wall}` (best-effort)

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

- **Task diversity**: unique counts + Shannon entropy over `task_id` and `task_family` (also reports `hhi` concentration).
- **Task-template diversity**: unique counts + entropy over `task_id|prompt_template_id` pairs (useful for spotting repeated reruns of the same task+template).
- **Prompt template diversity**: unique counts + entropy over `prompt_template_id` (also reports `hhi` concentration).
- **Conditional diversity / coupling**: conditional entropy + mutual information between key axes (currently `prompt_template_id|task_family`, `prompt_template_id|task_id`, `prompt_template_id|model_id`, `task_family|model_id`, `prompt_template_id|answer`, and `task_family|answer` in both directions). Use `prompt_template_id_given_task_family.conditional_entropy_norm` to quantify “template variety within families” (low means each family collapses to a single template); use `mutual_info_norm` to quantify how tightly coupled the axes are.
- **Token / n-gram distribution** (approx): prompt/output word uni/bi/tri stats + top n-grams + repetition heuristics.
  - Reports both raw entropy (`*_entropy_bits`) and normalized entropy (`*_entropy_norm`) plus `*_effective_num` for easier cross-corpus comparisons.
- **Character n-gram distribution** (approx): prompt/output normalized char 3-grams (alnum-only) + entropy + tops.
- **Token distribution slices** (approx): hashed-bucket word + char-3gram entropy by `prompt_template_id` and by `model_id`, with “low entropy” tops to flag template/model lexical collapse even when outputs are not exact duplicates.
- **Distinct-n** (approx): `distinct_1/2/3` for prompt/output word n-grams (unique / total).
- **Length distributions**: prompt/output chars + words (min/max/mean/p50/p90).
- **Runtime / throughput** (optional): `input_tokens`, `output_tokens`, `wall_ms`, plus derived `output_tok_per_s`, `total_tok_per_s`, and `ms_per_output_token`.
  - Also reports instrumentation coverage rates: `input_tokens_present_task_run_rate`, `output_tokens_present_task_run_rate`, and `wall_ms_present_task_run_rate`.
- **Answer option diversity**: distribution/entropy over `answer` (or extracted answer) when present.
  - Also reports `answer.source_counts` and extraction rates to diagnose missing/ambiguous answers.
  - For MCQ-style tasks, `diversity.answer.letter` reports the same diversity stats restricted to single-letter answers (`A`-`Z`) plus `hhi` (concentration).
- **Judge label balance**: label histogram + entropy; includes `label_balance_ab` (1.0 is perfectly balanced A/B, 0.0 is fully one-sided) and `label_imbalance_ab` (the complement), plus `label_entropy_bits`/`label_entropy_norm`/`label_effective_num` and `label_hhi` for concentration; emits per-model-pair breakdowns (including per-pair disagreement when multiple judges rate the same items) plus per-`judge_id` balance summaries.
- **Judge slice diagnostics**: top imbalance/disagreement slices by `prompt_template_id`, `task_family`, and `task_family|prompt_template_id` to spot systemic judge skew or instability.
- **Tag diversity** (optional): entropy over `tags` when present on task/judge records.
- **Disagreement rate**: for each `item_id`, fraction of non-majority labels across judges; aggregated mean (all labels) plus `a/b`-only decided disagreement.
  - The report also includes `tie_rate` and `invalid_rate` to help debug judge stability.
  - Per-judge outlier detection: `judge_id_disagreement_vs_majority_rate_top` (and `*_decided_ab_top`) plus scalar maxima (`judge_id_disagreement_vs_majority_rate_max`, `judge_id_disagreement_vs_majority_rate_decided_ab_max`).
- **Judge budget / stability stats** (when present): `parse_valid_rate`, `judge_in_tokens`, `judge_out_tokens`, `judge_latency_ms`, plus `judge_out_budget_le_target_rate` (default target = 64).
  - Also reports slice-join coverage rates for judge records: `task_family_nonempty_judge_pair_rate`, `prompt_template_id_nonempty_judge_pair_rate`, and `task_family_template_pair_nonempty_judge_pair_rate`.
- **Duplicate-output rate**: exact + normalized output duplicates (and prompt duplicates when present), plus per-`task_id|prompt_template_id` duplicate rates (summary + top repeated pairs).
  - Includes cross-model collapse diagnostics: `task_template_model_collapse_top` flags `task_id|prompt_template_id` groups where multiple `model_id`s produced too-few unique normalized outputs.
- **Duplicate-output concentration**: top normalized-output dup rates by `prompt_template_id`, by `task_family|prompt_template_id`, and by `buffer_item_id` to spot template-level collapse or buffer-item degeneracy.
- **Per-model degeneracy**: top normalized-output duplicate rates and useful-novelty flagged rates by `model_id`.
- **Buffer reuse**: how often `buffer_item_id` repeats (and how concentrated usage is).
  - Also reports logging coverage rates (`buffer_id_nonempty_task_run_rate`, `buffer_item_id_nonempty_task_run_rate`) plus `buffer_id` concentration (`buffer_id_hhi`, `buffer_id_entropy_bits`, `buffer_id_top`).
- **Useful-novelty filters**: deterministic heuristics that flag “novel but useless” outputs (e.g., extreme repetition). If `task_run` records include `useful_novelty_flags`, the metrics + recommender treat them as authoritative (else they recompute).
  - Includes prompt-echo and line-repetition heuristics to catch “coverage” that is actually noise.
  - Also reports top flagged-rate slices by `prompt_template_id`, `task_family`, and `task_family|prompt_template_id`.
- **Useful coverage (clean outputs)**: recomputes diversity + duplicate rates after excluding task-runs flagged by useful-novelty filters (a quick “effective coverage” view).
- **Run slices** (optional): if `run_id` is present on `task_run` records, the report includes per-run coverage/duplicate/noise summaries and “top runs” to quickly spot regressions.
- **Field coverage**: per-record-type presence rates for the key fields required by slices (task IDs/templates/models, judge IDs/labels, buffer IDs, and optional token/latency instrumentation). This helps validate baseline-runtime and judge-ELO ingestion.

### Useful-novelty flag definitions (deterministic)

`scripts/entropy_buffer_filter.py` annotates `task_run` records using `scripts/entropy_buffer_lib.useful_novelty_flags()` (unless `useful_novelty_flags` is already present and `--preserve-existing` is set).

Current flag set:

- `empty_output`: output is empty after normalization.
- `no_words`: output contains no alnum “words” after normalization.
- `very_long_output_ge_4096_chars`: normalized output length ≥ 4096 chars.
- `very_short_output_le_2_words`: ≤ 2 words and ≤ 16 chars (fast “too short” heuristic).
- `ai_disclaimer`: contains “as an ai” or “as a language model”.
- `refusal_like`: contains “i can't”, “i cannot”, or “unable to”.
- `word_repetition_ge_0.65`: most common word accounts for ≥ 65% of output words (requires ≥ 8 words).
- `word_unique_frac_le_0.25`: unique-word fraction ≤ 25% (requires ≥ 8 words).
- `many_urls`: output length ≥ 200 chars and contains ≥ 3 `http` substrings.
- `echo_prompt_overlap_ge_0.90`: ≥ 90% of output words are also present in the prompt (requires ≥ 12 output words and ≥ 8 prompt words).
- `line_repetition_ge_6`: a single normalized line repeats ≥ 6 times (requires ≥ 12 non-empty lines).
- `few_unique_lines_le_4`: ≤ 4 unique normalized lines (requires ≥ 12 non-empty lines).

Notes:

- If an answer is extractable (single-letter / numeric) via `extract_answer()`, or if the output is a bare JSON object/array, the heuristic currently emits no flags (treated as “likely structured / answer-only OK”).

## Tools

### Summarize entropy from JSONL

```bash
python3 scripts/entropy_buffer_metrics.py \
  --in-jsonl fixtures/entropy-buffer/records_mini.jsonl \
  --out-json /tmp/entropy_metrics.json \
  --out-md /tmp/entropy_metrics.md
```

### Diff two JSONL corpora (before/after)

Use this when you want to measure how a new batch changes coverage/degeneracy without re-reading full reports.

```bash
python3 scripts/entropy_buffer_diff.py \
  --before-jsonl fixtures/entropy-buffer/records_diff_before_mini.jsonl \
  --after-jsonl fixtures/entropy-buffer/records_diff_after_mini.jsonl \
  --out-json /tmp/entropy_diff.json \
  --out-md /tmp/entropy_diff.md
```

### Canonicalize mixed logs to a stable JSONL schema

Use this as a bridge when upstream logs are loosely-shaped or when you need stable `item_id` generation for judge records.

```bash
python3 scripts/entropy_buffer_canonicalize.py \
  --in-jsonl fixtures/entropy-buffer/records_canonicalize_mini.jsonl \
  --out-jsonl /tmp/entropy_canonical.jsonl
```

### Suggest next-batch targets (coverage gaps)

Use this when you want a deterministic “what should we run next?” view from history only (no candidate list required). It highlights:

- Underrepresented `task_family` / `prompt_template_id` / `task_family|prompt_template_id` keys (low-count).
- Underrepresented single-letter answers (`A`-`Z`) when present (`underrepresented_answer_letter_top`).
- Families with low within-family template entropy (template collapse).
- Families missing templates relative to templates seen elsewhere (cross-family template coverage).
- Underrepresented judge model-pairs and judge `task_family|prompt_template_id` slices (when present).

```bash
python3 scripts/entropy_buffer_gaps.py \
  --in-jsonl fixtures/entropy-buffer/records_gaps_mini.jsonl \
  --out-json /tmp/entropy_gaps.json \
  --out-md /tmp/entropy_gaps.md
```

### Annotate or filter useful-novelty flagged outputs

Use this when you want to persist heuristic flags (for pipeline auditability) or to drop obviously noisy `task_run` records before computing downstream diversity metrics.

```bash
python3 scripts/entropy_buffer_filter.py \
  --in-jsonl fixtures/entropy-buffer/records_filter_mini.jsonl \
  --out-jsonl /tmp/entropy_filter_annotated.jsonl
```

To drop flagged task runs:

```bash
python3 scripts/entropy_buffer_filter.py \
  --in-jsonl fixtures/entropy-buffer/records_filter_mini.jsonl \
  --drop-flagged-task-runs \
  --out-jsonl /tmp/entropy_filter_clean.jsonl
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
  - Use `--answer-letter-only` to treat answer diversity as single-letter options only (recommended for mixed corpora where many answers are numeric/freeform).
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
  - `selected_expected_clean_rate_mean`: shorthand for `1 - selected_history_noise_rate_mean` (clamped to `[0,1]`).
  - `selected_history_judge_*_mean`: expected judge-stability penalty components for the chosen batch (rates only; weights are in `meta`).

## Integration notes

- **Judge ELO loop**: should emit `judge_pair` records with stable `item_id`, `a_model_id`, `b_model_id`, and `label`. The entropy tools do not compute ELO; they compute *balance* and *disagreement* that affect ELO stability.
- If the judge loop emits compact envelopes or missing `item_id`, run `scripts/entropy_buffer_canonicalize.py` to normalize and generate a stable `item_id` (from `task_id|prompt_template_id|a_model_id|b_model_id`).
- **Baseline runtime loop**: should emit `task_run` records with `task_id`, `prompt_template_id`, and `output` (plus optional token/time fields). The entropy tools treat token/time as optional metadata and focus on coverage/degeneracy.
  - If you have `tags`, include them for better coverage accounting.
  - If token/time fields are nested or inconsistently named, `scripts/entropy_buffer_canonicalize.py` can lift them into `input_tokens`/`output_tokens`/`wall_ms`.

## Risks / limitations

- Token/n-gram metrics are approximate (not model-tokenizer accurate).
- Token slice entropy uses hashed buckets for bounded memory; treat values as relative signals, not exact vocab entropy.
- “Useful novelty” is heuristic; treat flags as triage signals, not ground truth.
