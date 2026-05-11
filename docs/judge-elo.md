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
- `reason`: string, **≤ 18 words**
- `train_hint`: string, **≤ 18 words** (actionable improvement hint for the loser; empty allowed)
- `tags`: array of short strings (0..8); e.g. `["format","factuality"]`

This object is what the judge model returns. A harness may then wrap it into a JSONL record by attaching metadata (models, tokens, latency, etc.).

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
- `judge_model`: string
- `task_id`, `sample_id`: strings
- `raw`: original judge text (when `parse_valid=false`, keep this short)
- `parse_error`: short string when `parse_valid=false`

## Prompt Design (verifier budget)

Use a strict system instruction:
- "Return minified JSON only; no explanation."
- "Keep `reason` and `train_hint` under 18 words each."
- "Use scores to justify the margin; do not add extra keys."

The reference prompt builder lives at `scripts/pairwise_judge_prompt.py`.

## Offline ELO

`scripts/judge_elo_update.py`:
- validates input JSONL (optional strict mode)
- filters to `parse_valid=true`
- performs deterministic Elo updates (order = input order; optionally stable-sorted by `pair_id` only)
- writes JSON/CSV/Markdown leaderboard summaries

Elo math:
- expected score: `E_A = 1 / (1 + 10^((R_B - R_A)/400))`
- outcome: win=1, tie=0.5, loss=0
- update: `R_A += K_eff * (S_A - E_A)` and `R_B -= K_eff * (S_A - E_A)`
- `K_eff` is scaled by `margin` (close wins update less than decisive wins)

## Baseline Integration Notes

The leaderboard CSV emitted by `scripts/judge_elo_update.py` contains an Elo-derived `quality_score` (0..100) **derived only from judge results** (no speed fields). The baseline runtime loop can join this `quality_score` onto its speed measurements and compute quality-adjusted tok/s without mixing speed signals into judge quality.
