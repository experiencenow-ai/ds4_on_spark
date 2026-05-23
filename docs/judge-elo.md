# Judge ELO Loop (DSv4 verifier budget)

> Supersedes: `docs/judge-elo.md`, `docs/judge-elo-schema.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 2 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `judge-elo.md`: Judge ELO Loop (DSv4 verifier budget) (258 lines).
- `judge-elo-schema.md`: Compact DSv4 Pairwise Judge Schema (v5 record) (78 lines).

## Command Inventory

- `judge-elo.md`: `python3 scripts/pairwise_judge_prompt.py --schema-version v2 --decision-version v2 --format json --judge-out-target 64 --prompt fixtures/judge-elo/sample_prompt.txt --a fixtures/judge-elo/sample_a.txt --b fixtures/judge-elo/sample_b.txt`
- `judge-elo.md`: `python3 scripts/pairwise_judge_validate_decision.py --in fixtures/judge-elo/sample_decision_v2.txt --strict`
- `judge-elo.md`: `python3 scripts/judge_elo_update.py --in fixtures/judge-elo/sample_judge_records_v5.jsonl --out-dir /private/tmp/ds4_judge_elo_quickstart --strict`
- `judge-elo.md`: `python3 scripts/judge_elo_validate_outputs.py --out-dir /private/tmp/ds4_judge_elo_quickstart`
- `judge-elo.md`: `python3 scripts/judge_elo_validate.py --strict --in <records.jsonl>`
- `judge-elo.md`: `python3 scripts/judge_elo_validate_outputs.py --out-dir <elo_out_dir>`
- `judge-elo.md`: `python3 scripts/pairwise_judge_validate_decision.py --in <judge.txt>`
- `judge-elo.md`: `python3 scripts/pairwise_judge_validate_decision.py --strict --in <judge.txt>`
- `judge-elo.md`: `python3 scripts/pairwise_judge_record.py --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt>`
- `judge-elo.md`: `python3 scripts/pairwise_judge_record.py --record-schema v2 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tokens-a-out <n> --tokens-b-out <n> --tokens-judge-in <n> --tokens-judge-out <n> --latency-a-ms <n> --latency-b-ms <n> --latency-judge-ms <n>`
- `judge-elo.md`: `python3 scripts/pairwise_judge_record.py --record-schema v3 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tokens-a-out <n> --tokens-b-out <n> --tokens-judge-in <n> --tokens-judge-out <n> --latency-a-ms <n> --latency-b-ms <n> --latency-judge-ms <n>`
- `judge-elo.md`: `python3 scripts/pairwise_judge_record.py --record-schema v4 --pair-id <id> --model-a <a> --model-b <b> --judge-model ds4 --decision <judge.txt> --tokens-a-out <n> --tokens-b-out <n> --tokens-judge-in <n> --tokens-judge-out <n> --latency-a-ms <n> --latency-b-ms <n> --latency-judge-ms <n>`
- `judge-elo-schema.md`: `python3 scripts/judge_elo_update.py --in <judge_records.jsonl> --out-dir <out_dir> --strict`
- `judge-elo-schema.md`: `python3 scripts/judge_elo_join_quality.py --in <baseline.csv> --bundle <out_dir>/bundle.json --out <baseline_with_quality.csv>`
- `judge-elo-schema.md`: `python3 scripts/model_quality_speed_score.py <baseline_with_quality.csv> > <scored.md>`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/judge-elo.md` | 258 | Judge ELO Loop (DSv4 verifier budget) | Quickstart (offline; no APIs), Compact Pairwise Judge Output (decision object), Judge Record JSONL (envelope), Updater Output Schemas, Prompt Design (verifier budget) |
| `docs/judge-elo-schema.md` | 78 | Compact DSv4 Pairwise Judge Schema (v5 record) | Decision object (DSv4 output), JSONL record envelope (preferred: v5), Offline Elo updater outputs, Baseline integration (quality-adjusted tok/s) |
