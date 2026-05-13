# Judge-ELO summary

## Inputs

- strict: true
- quality_mode: logistic
- quality_source: judge_elo_logistic_v1
- k: 32.000
- scale: 400.000
- sort_by_pair_id: false
- judge_out_target_tokens: 64

## Records

- records: 4
- parse_valid_true: 3
- parse_valid_false: 1
- parse_valid_fraction: 0.750
- matches_used: 3

## Judge-out budget

- judge_out_tokens_present: 4
- judge_out_le_target: 4
- judge_out_le_target_fraction: 1.000
- judge_out_tokens_present_parse_valid_true: 3
- judge_out_le_target_parse_valid_true: 3
- judge_out_le_target_fraction_parse_valid_true: 1.000

## Top models

| rank | model | elo | games | W | L | T | quality_score |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | model_slow | 1008.7 | 2 | 1 | 1 | 0 | 51.3 |
| 2 | model_mid | 999.9 | 1 | 0 | 0 | 1 | 50.0 |
| 3 | model_fast | 991.4 | 3 | 1 | 1 | 1 | 48.8 |
