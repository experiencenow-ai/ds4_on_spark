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
