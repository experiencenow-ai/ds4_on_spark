# Compact DSv4 Pairwise Judge Schema (v5 record)

This doc is the **implementation contract** for the judge-ELO loop: a compact pairwise judge decision plus a compact JSONL record envelope that includes parse validity and speed/size accounting.

DSv4 is treated as a **verifier**: it emits only a minified decision JSON (no prose). A harness (or offline wrapper) attaches token/latency metadata and emits JSONL records for offline Elo updates.

Reference examples (offline fixtures):
- Decision (v2 keys): `fixtures/judge-elo/sample_decision_v2.txt`
- Prompt (v2): `fixtures/judge-elo/sample_pairwise_prompt_v2.json`
- Record JSONL (v5): `fixtures/judge-elo/sample_judge_records_v5.jsonl`

## Decision object (DSv4 output)

DSv4 should emit **exactly one minified JSON object on one line** with **compact keys**:

```json
{"w":"A|B|tie","m":0,"sa":0,"sb":0,"r":"...","h":"","t":[]}
```

Required fields:
- `w`: `"A" | "B" | "tie"`
- `m`: integer `0..3` (preference strength; tie ⇒ `m=0`)
- `sa`, `sb`: integers `0..10` (numeric scores for A/B)
- `r`: **non-empty** string, **≤ 18 words**, single-line (≤ 200 chars)
- `h`: string, **≤ 18 words**, single-line (≤ 200 chars); may be empty (especially on ties)
- `t`: array of `0..3` short strings (each ≤ 24 chars), single-line strings

Machine schema: `fixtures/judge-elo/schemas/ds4_pairwise_judge_decision_v2.schema.json`

Prompt builder (offline): `scripts/pairwise_judge_prompt.py`

## JSONL record envelope (preferred: v5)

Offline tooling consumes **one JSON object per line** with:

Required fields:
- `schema`: `"ds4_pairwise_judge_record_v5"`
- `pair_id`: stable id for this comparison
- `model_a`, `model_b`: model identifiers (strings)
- `parse_valid`: boolean
- `tk`: `[a_out, b_out, judge_in, judge_out]` token counts (all ints ≥ 0)
- `lt`: `[a_ms, b_ms, judge_ms]` latencies in ms (all ints ≥ 0)

If `parse_valid=true`, these are also required:
- decision keys: `w,m,sa,sb,r,h,t` (as above)

If `parse_valid=false`, include at least one:
- `raw`: compacted original judge text (≤ 512 chars)
- `parse_error`: short parse/validation error (≤ 128 chars)

Machine schema: `fixtures/judge-elo/schemas/ds4_pairwise_judge_record_v5.schema.json`

Offline wrapper (build records from DSv4 output): `scripts/pairwise_judge_record.py --record-schema v5`

## Offline Elo updater outputs

Elo updater (offline): `scripts/judge_elo_update.py`

Outputs (all deterministic for the same input JSONL order):
- `bundle.json` (meta + budget + leaderboard + quality_map)
- `leaderboard.{json,csv,md}`
- `quality_map.json`
- `meta.json`, `budget.json`
- `summary.md` (stable grep-friendly)

Output validator (offline): `scripts/judge_elo_validate_outputs.py`

## Baseline integration (quality-adjusted tok/s)

Join `quality_score` (judge-only signal) onto baseline runtime CSV rows via:

```bash
python3 scripts/judge_elo_update.py --in <judge_records.jsonl> --out-dir <out_dir> --strict
python3 scripts/judge_elo_join_quality.py --in <baseline.csv> --bundle <out_dir>/bundle.json --out <baseline_with_quality.csv>
python3 scripts/model_quality_speed_score.py <baseline_with_quality.csv> > <scored.md>
```

This keeps **judge quality** separate from **model speed**: judge-ELO never consumes speed fields; speed scoring happens only after joining.
