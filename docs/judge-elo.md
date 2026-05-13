# Judge ELO Loop (DSv4 verifier budget)

This track defines a compact pairwise judge contract intended for slow/high-quality DSv4 runs, plus an offline deterministic ELO updater that produces leaderboards consumable by the baseline runtime loop.

If you only need the **schema contract** (decision + record v5 + outputs), start with `docs/judge-elo-schema.md`.

Goals:
- DSv4 is used as a **verifier** (compact, structured output), not a verbose author.
- Judge quality (pairwise preference) is tracked separately from model speed (tok/s).
- Outputs are JSONL-first, with stable parsing/validation and deterministic ELO updates.

## Compact Pairwise Judge Output (decision object)

DSv4 should emit **exactly one minified JSON object on one line** (no prose/markdown).

Preferred (compact keys; smallest judge_out):

```json
{"w":"A|B|tie","m":0,"sa":0,"sb":0,"r":"...","h":"","t":[]}
```

Fields:
- `w`: `"A" | "B" | "tie"`
- `m`: integer `0..3` (strength of preference; `0` == near-tie; tie ⇒ `m=0`)
- `sa`, `sb`: integers `0..10` (numeric scores for A/B)
- `r`: string, **non-empty**, **≤ 18 words** (prefer ≤ 12), **single-line**
- `h`: string, **≤ 18 words** (prefer ≤ 12; actionable improvement hint for the loser; empty allowed), **single-line**
- `t`: array of short strings (0..3); e.g. `["format","factuality"]`
- No extra keys: the decision validator rejects unknown fields.
- Strict-mode consistency rule: keep `m` consistent with `abs(sa-sb)`:
  - diff=1 ⇒ `m` ∈ {0,1}
  - diff=2 ⇒ `m` ∈ {1,2}
  - diff=3 ⇒ `m` = 2
  - diff≥4 ⇒ `m` = 3
  - strict mode also enforces that non-tie winners use `sa!=sb`

This object is what the judge model returns. A harness may then wrap it into a JSONL record by attaching metadata (models, tokens, latency, etc.).

Machine-readable schema:
- Preferred: `fixtures/judge-elo/schemas/ds4_pairwise_judge_decision_v2.schema.json` with keys `w,m,sa,sb,r,h,t`
- Legacy (more verbose keys): `fixtures/judge-elo/schemas/ds4_pairwise_judge_decision_v1.schema.json`
- `scripts/pairwise_judge_validate_decision.py` and `scripts/pairwise_judge_record.py` accept both and canonicalize to v1 keys internally

## Judge Record JSONL (envelope)

The offline tools in `scripts/judge_elo_*.py` expect one JSON object per line with:

Required fields:
- `schema`: `"ds4_pairwise_judge_record_v1" | "ds4_pairwise_judge_record_v2" | "ds4_pairwise_judge_record_v3" | "ds4_pairwise_judge_record_v4" | "ds4_pairwise_judge_record_v5"`
- `pair_id`: stable identifier for this comparison
- `model_a`, `model_b`: model identifiers (strings)
- `parse_valid`: boolean (whether the judge decision JSON was parsed successfully)
- No extra keys: unknown top-level fields are invalid (keep metadata in the defined optional fields).

If `parse_valid` is `true`, these must also be present:
- For record schemas v1/v2/v3: `winner`, `margin`, `score_a`, `score_b`, `reason`, `train_hint`, `tags`
- For record schemas v4/v5 (compact decision keys): `w`, `m`, `sa`, `sb`, `r`, `h`, `t`

Preferred schema (smallest JSONL; strict-by-schema):
- `schema="ds4_pairwise_judge_record_v5"`: compact decision keys `w/m/sa/sb/r/h/t` plus compact budget arrays:
  - `tk`: `[a_out, b_out, judge_in, judge_out]` (all required; ints >= 0)
  - `lt`: `[a_ms, b_ms, judge_ms]` (all required; ints >= 0)

Optional but recommended in legacy schemas (for speed/quality separation and budgeting):
- `tokens`: `{ "a_out": int, "b_out": int, "judge_in": int, "judge_out": int }`
- `latency_ms`: `{ "a": int, "b": int, "judge": int }`
- In `schema="ds4_pairwise_judge_record_v1"`, these may be omitted or partially populated; strict validation requires all keys.
- In `schema="ds4_pairwise_judge_record_v2"` and `schema="ds4_pairwise_judge_record_v3"`, these are required (all keys required).
- In `schema="ds4_pairwise_judge_record_v4"`, these are required (all keys required).
- `schema="ds4_pairwise_judge_record_v3"` is strict-by-schema: it also enforces strict decision consistency (margin/score mapping + `tags<=3`) via `scripts/judge_elo_schema.py`.
- `schema="ds4_pairwise_judge_record_v4"` is strict-by-schema and stores **compact decision keys** (`w,m,sa,sb,r,h,t`) to reduce JSONL size; offline tools accept v4 and canonicalize it internally.
- `schema="ds4_pairwise_judge_record_v5"` is strict-by-schema and stores **compact decision keys** plus compact budget arrays (`tk`/`lt`) to further reduce JSONL size.
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
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_record_v2.schema.json` (tokens/latency required)
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_record_v3.schema.json` (tokens/latency required; tags<=3)
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_record_v4.schema.json` (compact decision keys; tokens/latency required; tags<=3)
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_record_v5.schema.json` (compact decision keys; tk/lt required; tags<=3)

## Updater Output Schemas

The offline updater emits additional machine-readable outputs intended for downstream joins (baseline runtime scoring, dashboards, etc.):

- `meta.json`: `fixtures/judge-elo/schemas/ds4_judge_elo_meta_v1.schema.json`
  - includes `strict` flag when `scripts/judge_elo_update.py --strict` is used
- `budget.json`: `fixtures/judge-elo/schemas/ds4_judge_elo_budget_v1.schema.json`
- `quality_map.json`: `fixtures/judge-elo/schemas/judge_elo_quality_map_v1.schema.json`
- `leaderboard.json`: `fixtures/judge-elo/schemas/judge_elo_leaderboard_v1.schema.json`
- `bundle.json`: `fixtures/judge-elo/schemas/ds4_judge_elo_bundle_v1.schema.json`
  - single-file bundle for downstream loops that want one JSON to ingest
- `summary.md`: compact human-readable summary (parse validity + judge-out budget + top models)

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
By default it uses `--decision-version v2` to request the compact-key decision object (`w,m,sa,sb,r,h,t`) and let the offline tools canonicalize it; use `--decision-version v1` to request verbose keys.
For lower judge **input** token overhead, use `--schema-version v2` (default; it avoids embedding the JSON shape in the user message).
Prompt schema v2 also includes the strict margin/score consistency + `tags<=3` constraints in the system message to reduce `parse_valid=false` rates under strict validation.
For harnesses, use `--format json` to emit a single JSON object with `{system,user}` fields.
Machine-readable schema:
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_prompt_v1.schema.json`
- `fixtures/judge-elo/schemas/ds4_pairwise_judge_prompt_v2.schema.json`

To validate raw judge output (extracting the first JSON object if wrapped in extra text), use:

```bash
python3 scripts/pairwise_judge_validate_decision.py --in <judge.txt>
```

To enforce strict margin/score consistency + compact tags during validation, add `--strict`:

```bash
python3 scripts/pairwise_judge_validate_decision.py --strict --in <judge.txt>
```

To wrap raw judge text into a JSONL record envelope (and set `parse_valid`), use:

```bash
python3 scripts/pairwise_judge_record.py --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt>
```

To emit `schema="ds4_pairwise_judge_record_v2"` (tokens/latency required), add `--record-schema v2` and provide all budget fields:

```bash
python3 scripts/pairwise_judge_record.py --record-schema v2 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tokens-a-out <n> --tokens-b-out <n> --tokens-judge-in <n> --tokens-judge-out <n> --latency-a-ms <n> --latency-b-ms <n> --latency-judge-ms <n>
```

To emit `schema="ds4_pairwise_judge_record_v3"` (tokens/latency required; strict-by-schema), use `--record-schema v3` and provide all budget fields:

```bash
python3 scripts/pairwise_judge_record.py --record-schema v3 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tokens-a-out <n> --tokens-b-out <n> --tokens-judge-in <n> --tokens-judge-out <n> --latency-a-ms <n> --latency-b-ms <n> --latency-judge-ms <n>
```

To emit `schema="ds4_pairwise_judge_record_v4"` (compact decision keys; tokens/latency required; strict-by-schema), use `--record-schema v4`:

```bash
python3 scripts/pairwise_judge_record.py --record-schema v4 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tokens-a-out <n> --tokens-b-out <n> --tokens-judge-in <n> --tokens-judge-out <n> --latency-a-ms <n> --latency-b-ms <n> --latency-judge-ms <n>
```

To emit `schema="ds4_pairwise_judge_record_v5"` (compact decision keys; compact budget arrays `tk`/`lt`; strict-by-schema), use `--record-schema v5`:

```bash
python3 scripts/pairwise_judge_record.py --record-schema v5 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tokens-a-out <n> --tokens-b-out <n> --tokens-judge-in <n> --tokens-judge-out <n> --latency-a-ms <n> --latency-b-ms <n> --latency-judge-ms <n>
```

If your harness already tracks compact budget arrays, you can pass them directly:

```bash
python3 scripts/pairwise_judge_record.py --record-schema v5 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tk "[<a_out>,<b_out>,<judge_in>,<judge_out>]" --lt "[<a_ms>,<b_ms>,<judge_ms>]"
```

To enforce strict margin/score consistency + compact tags while wrapping for schema v1/v2, add `--strict`:

```bash
python3 scripts/pairwise_judge_record.py --strict --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt>
```

To compact existing judge record JSONL into the strict compact record schema v5 (decision keys `w/m/sa/sb/r/h/t` and budget arrays `tk/lt`), use:

```bash
python3 scripts/judge_elo_compact_records.py --in <records.jsonl> --out <records_v5.jsonl>
```

If you need best-effort compaction (skip invalid/uncompactable lines), add `--skip-invalid` and monitor stderr for `records_skipped`:

```bash
python3 scripts/judge_elo_compact_records.py --skip-invalid --in <records.jsonl> --out <records_v5.jsonl>
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
python3 scripts/judge_elo_join_quality.py --in <baseline.csv> --bundle <elo_out_dir>/bundle.json --out <baseline_with_quality.csv>
python3 scripts/model_quality_speed_score.py <baseline_with_quality.csv> > <scored.md>
```

If the baseline CSV includes models that are not yet present in the judge-ELO quality map, you can optionally fill them with a neutral default (e.g. 50) so downstream scoring has a value:

```bash
python3 scripts/judge_elo_join_quality.py --in <baseline.csv> --bundle <elo_out_dir>/bundle.json --missing-default 50 --missing-quality-source judge_elo_default_v1 --out <baseline_with_quality.csv>
```
