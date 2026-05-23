# vLLM MXFP4 TP=2 ds4-eval Comparison

vLLM MXFP4 TP=2 quality is better than antirez IQ2XXS PP=1 by 5.43 percentage points on ds4-eval, p-value 0.179688.

| Run | Pass | Total | Pass rate |
| --- | ---: | ---: | ---: |
| antirez IQ2XXS PP=1 | 73 | 92 | 0.793 |
| vLLM MXFP4 TP=2 | 78 | 92 | 0.848 |

| Source | Domain | Baseline | Candidate |
| --- | --- | ---: | ---: |
| AIME2025 | Algebra | 5/7 | 7/7 |
| AIME2025 | Algebra, Geometry | 1/1 | 1/1 |
| AIME2025 | Combinatorics | 3/7 | 5/7 |
| AIME2025 | Combinatorics, Number Theory | 0/1 | 1/1 |
| AIME2025 | Geometry | 4/5 | 5/5 |
| AIME2025 | Number Theory | 2/4 | 2/4 |
| COMPSEC | Botan | 2/3 | 2/3 |
| COMPSEC | Firebird | 2/2 | 2/2 |
| COMPSEC | FreeBSD / librpcsec_gss | 1/1 | 1/1 |
| COMPSEC | GNU Inetutils telnetd | 1/1 | 1/1 |
| COMPSEC | Linux kernel | 1/1 | 1/1 |
| COMPSEC | Linux kernel AppArmor | 1/1 | 1/1 |
| COMPSEC | Linux kernel USB gadget storage | 1/1 | 1/1 |
| COMPSEC | Mbed TLS | 3/3 | 3/3 |
| COMPSEC | PHP | 1/1 | 1/1 |
| COMPSEC | PHP PDO Firebird | 1/1 | 1/1 |
| COMPSEC | libexpat | 1/1 | 1/1 |
| COMPSEC | uds-c | 1/1 | 1/1 |
| GPQA Diamond | Biology | 1/3 | 1/3 |
| GPQA Diamond | Chemistry | 9/12 | 10/12 |
| GPQA Diamond | Physics | 10/10 | 10/10 |
| SuperGPQA | Agronomy | 2/2 | 2/2 |
| SuperGPQA | Engineering | 8/8 | 7/8 |
| SuperGPQA | Law | 1/1 | 1/1 |
| SuperGPQA | Literature and Arts | 1/1 | 1/1 |
| SuperGPQA | Medicine | 2/2 | 2/2 |
| SuperGPQA | Military Science | 0/1 | 0/1 |
| SuperGPQA | Science | 6/7 | 5/7 |
| SuperGPQA | Sociology | 2/3 | 2/3 |

Discordant pairs: baseline-only pass 2, candidate-only pass 7.

## Discordant Cases

| # | Case | Source | Domain | Baseline | Candidate |
| ---: | --- | --- | --- | --- | --- |
| 5 | b7e20eac98764fb0bf30e8366d951daa | SuperGPQA | Engineering | J (pass) | B (fail) |
| 24 | aime2025-05 | AIME2025 | Combinatorics, Number Theory | 1 (fail) | 279 (pass) |
| 33 | aime2025-07 | AIME2025 | Combinatorics | 10395 (fail) | 821 (pass) |
| 44 | 8483667a25e74fdfa3188de4ea734f03 | SuperGPQA | Science | A (pass) | E (fail) |
| 49 | recZWeueB7lSPR6wN | GPQA Diamond | Chemistry | C (fail) | B (pass) |
| 51 | aime2025-25 | AIME2025 | Combinatorics | 13 (fail) | 907 (pass) |
| 57 | aime2025-12 | AIME2025 | Algebra | ? (fail) | 510 (pass) |
| 60 | aime2025-27 | AIME2025 | Geometry | 9 (fail) | 19 (pass) |
| 75 | aime2025-30 | AIME2025 | Algebra | 4 (fail) | 240 (pass) |

## Length Cap Review

Candidate rows at the 16000-token cap: 10.
Capped rows without an explicit `Answer:` marker: 10.
Capped rows that changed the baseline/candidate pass delta: 0.
Length-cap verdict: `no_comparison_delta_but_grading_risk`.

| # | Case | Status | Observed | Expected | Answer marker |
| ---: | --- | --- | --- | --- | --- |
| 13 | recDytVnNYZe2HuUU | both_pass | A | A | False |
| 28 | recb80OwMgNnceA9t | both_fail | C | D | False |
| 31 | recA1i5ZAh0Uzclxp | both_pass | C | C | False |
| 48 | aime2025-10 | both_fail | 1680 | 81 | False |
| 52 | recVvpD8miVjmmyfe | both_fail | A | C | False |
| 63 | aime2025-13 | both_fail | 36 | 204 | False |
| 64 | recFaL6j8UMhutXrc | both_pass | A | A | False |
| 66 | aime2025-28 | both_fail | 1 | 248 | False |
| 70 | recWxGU8Q4YReJ1tb | both_fail | A | C | False |
| 72 | aime2025-15 | both_fail | 27 | 735 | False |

Recommendations:
- Record length_capped and answer_marker_present on future pipeline-quality question rows.
- Treat length-capped rows without an explicit Answer: marker as grading-risk cases even when fallback extraction happens to match.
- Add a stop policy or answer-line extraction mode before using long max_tokens runs for quality deltas.
