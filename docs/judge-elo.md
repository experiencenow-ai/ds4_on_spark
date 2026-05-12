# Judge ELO Loop (DSv4 verifier budget)

This track defines a compact pairwise judge contract intended for slow/high-quality DSv4 runs, plus an offline deterministic ELO updater that produces leaderboards consumable by the baseline runtime loop.

Goals:
- DSv4 is used as a **verifier** (compact, structured output), not a verbose author.
- Judge quality (pairwise preference) is tracked separately from model speed (tok/s).
- Outputs are JSONL-first, with stable parsing/validation and deterministic ELO updates.

## Compact Pairwise Judge Output (decision object)

DSv4 should emit **exactly one JSON object** (minified; no prose) with:

- `winner`: `"A" | "B" | "tie"`
- `margin`: integer `0..3` (strength of preference; `0` == near-tie)
- `score_a`: integer `0..10`
- `score_b`: integer `0..10`
- `reason`: string, **non-empty**, **≤ 18 words** (prefer ≤ 12), **single-line**
- `train_hint`: string, **≤ 18 words** (prefer ≤ 12; actionable improvement hint for the loser; empty allowed), **single-line**
- `reason`/`train_hint` should also be kept short in characters (schemas cap at 200 chars).
- `tags`: array of short strings (0..8; prefer ≤ 3); e.g. `["format","factuality"]`

This object is what the judge model returns. A harness may then wrap it into a JSONL record by attaching metadata (models, tokens, latency, etc.).

Machine-readable schema:
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_decision_v1.schema.json`

## Judge Record JSONL (envelope)

The offline tools in `scripts/judge_elo_*.py` expect one JSON object per line with:

Required fields:
- `schema`: `"ds4_pairwise_judge_record_v1"`
- `pair_id`: stable identifier for this comparison
- `model_a`, `model_b`: model identifiers (strings)
- `parse_valid`: boolean (whether the judge decision JSON was parsed successfully)

If `parse_valid` is `true`, these must also be present:
- decision fields: `winner`, `margin`, `score_a`, `score_b`, `reason`, `train_hint`, `tags`

Optional but recommended (for speed/quality separation and budgeting):
- `tokens`: `{ "a_out": int, "b_out": int, "judge_in": int, "judge_out": int }`
- `latency_ms`: `{ "a": int, "b": int, "judge": int }`
- `tokens` / `latency_ms` may be partially populated; strict validation requires all keys.
- `judge_model`: string
- `task_id`, `sample_id`: strings
- `raw`: original judge text (when `parse_valid=false`, keep this short)
- `parse_error`: short string when `parse_valid=false`
  - When `parse_valid=false`, include `raw` and/or `parse_error` (at least one is required; both is recommended).
  - `raw` is capped at 512 chars; `parse_error` at 128 chars.

For baseline-quality joins, treat `tokens` and `latency_ms` as required and validate with:

```bash
python3 scripts/judge_elo_validate.py --strict --in <records.jsonl>
```

Machine-readable schema:
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_record_v1.schema.json`

## Updater Output Schemas

The offline updater emits additional machine-readable outputs intended for downstream joins (baseline runtime scoring, dashboards, etc.):

- `meta.json`: `fixtures/judge-elo/schemas/ds4_judge_elo_meta_v1.schema.json`
- `budget.json`: `fixtures/judge-elo/schemas/ds4_judge_elo_budget_v1.schema.json`
- `quality_map.json`: `fixtures/judge-elo/schemas/judge_elo_quality_map_v1.schema.json`
- `leaderboard.json`: `fixtures/judge-elo/schemas/judge_elo_leaderboard_v1.schema.json`

To validate a produced output directory (without any paid API calls):

```bash
python3 scripts/judge_elo_validate_outputs.py --out-dir <elo_out_dir>
```

## Prompt Design (verifier budget)

Use a strict system instruction:
- "Return minified JSON only; no explanation."
- "Keep `reason` and `train_hint` under 18 words each."
- "All string values must be single-line (no newlines)."
- "Use scores to justify the margin; do not add extra keys."
- Keep the JSON short: target `judge_out <= ~64 tokens` (reason/hint are the budget drivers).

The reference prompt builder lives at `scripts/pairwise_judge_prompt.py`.
It supports `--judge-out-target` (default 64) to keep prompt budgeting aligned with `scripts/judge_elo_update.py --judge-out-target`.
For harnesses, use `--format json` to emit a single JSON object with `{system,user}` fields.

To wrap raw judge text into a JSONL record envelope (and set `parse_valid`), use:

```bash
python3 scripts/pairwise_judge_record.py --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt>
```

## Offline ELO

`scripts/judge_elo_update.py`:
- validates input JSONL (optional strict mode)
- filters to `parse_valid=true`
- performs deterministic Elo updates (order = input order; optionally stable-sorted by `pair_id` only)
- writes JSON/CSV/Markdown leaderboard summaries plus:
  - `quality_map.json` (model -> `quality_score`)
  - `meta.json` (record/match counts and updater parameters)
  - `budget.json` (token/latency/parse-validity summary over the input JSONL)
    - includes `judge_out_budget` (how often judge outputs meet the compact token target)
      - reports both overall and `parse_valid=true`-only fractions when `tokens.judge_out` is present
    - compact target is configurable via `--judge-out-target` (default 64)

Quality mapping defaults to `--quality-mode logistic` (anchored: Elo 1000 -> quality_score 50). Use `--quality-mode minmax` only for quick relative comparisons within a single closed set of models.

Elo math:
- expected score: `E_A = 1 / (1 + 10^((R_B - R_A)/400))`
- outcome: win=1, tie=0.5, loss=0
- update: `R_A += K_eff * (S_A - E_A)` and `R_B -= K_eff * (S_A - E_A)`
- `K_eff` is scaled by `margin` (close wins update less than decisive wins)

## Baseline Integration Notes

The leaderboard CSV emitted by `scripts/judge_elo_update.py` contains an Elo-derived `quality_score` (0..100) **derived only from judge results** (no speed fields). The baseline runtime loop can join this `quality_score` onto its speed measurements and compute quality-adjusted tok/s without mixing speed signals into judge quality.

For a CSV-first workflow, use `scripts/judge_elo_join_quality.py` to attach `quality_score` onto baseline rows before scoring:

```bash
python3 scripts/judge_elo_update.py --in <judge_records.jsonl> --out-dir <elo_out_dir> --strict
python3 scripts/judge_elo_join_quality.py --in <baseline.csv> --quality-map <elo_out_dir>/quality_map.json --meta <elo_out_dir>/meta.json --out <baseline_with_quality.csv>
python3 scripts/model_quality_speed_score.py --in <baseline_with_quality.csv> --out-md <scored.md>
```
