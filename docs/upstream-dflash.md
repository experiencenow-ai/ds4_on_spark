# Upstream: DFlash candidate pairs (non-Qwen)

This note tracks DFlash speculative decoding candidate pairs beyond the Qwen
family. It is metadata-only: no model weights were downloaded while preparing
this document.

- Pinned-at: 2026-05-11 (UTC)
- Safety policy: use `GIT_LFS_SKIP_SMUDGE=1`, Hugging Face API metadata, or local
  Spark paths first; large weight fetches require explicit human approval.

Qwen-family target/draft pairs are tracked separately in
[`docs/upstream-qwen-dflash.md`](upstream-qwen-dflash.md).

## Candidate Matrix

| Priority | Target | Target ref | Target commit / SHA | Target license | Target safetensors | Draft / accelerator | Draft commit / SHA | Draft license | Draft safetensors | Single Spark? | Why test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `openai/gpt-oss-20b` | `refs/heads/main` | `6cee5e81ee83917806bbde320786a8fb61efebee` | `apache-2.0` | 25.63 GiB | `z-lab/gpt-oss-20b-DFlash` | `d53f6551543204c859e8bbaaddbd15d11b447af9` | `mit` | 1.46 GiB | likely | Small open target with an official DFlash drafter; cheapest non-Qwen DFlash plumbing test. |
| 2 | `meta-llama/Llama-3.1-8B-Instruct` | `refs/heads/main` | `0e9e39f249a16976918f6564b8830bc894c89659` | `llama3.1` | 14.96 GiB | `z-lab/LLaMA3.1-8B-Instruct-DFlash-UltraChat` | `d3af30def9601abdd10810aba220d692f0e803f0` | `mit` | 1.95 GiB | likely | Small paired DFlash target/draft under the Llama 3.1 license; good low-cost target to compare against the open GPT-OSS baseline when license terms/approval allow. |
| 3 | `google/gemma-4-26B-A4B-it` | `refs/heads/main` | `462a98a12e28e2cbcfccaf78fe41e3e50235e6ae` | `apache-2.0` | 48.07 GiB | `z-lab/gemma-4-26B-A4B-it-DFlash` | `77d4202772dfe50b2396ec7bac9cfffc7b9e7057` | `apache-2.0` | 0.80 GiB | likely | Open, single-Spark-sized instruction-tuned baseline with an official DFlash drafter. |
| 4 | `google/gemma-4-31B-it` | `refs/heads/main` | `ba74f5b6c647c0911554e50278d6f6f4477f9010` | `apache-2.0` | 58.25 GiB | `z-lab/gemma-4-31B-it-DFlash` | `eabd648301ce28583cc14757912e5e0f84e152e1` | `apache-2.0` | 2.86 GiB | likely | Larger Gemma comparator with a bigger drafter; useful to check scaling behavior vs 26B class. |
| 5 | `openai/gpt-oss-120b` | `refs/heads/main` | `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` | `apache-2.0` | 121.54 GiB | `z-lab/gpt-oss-120b-DFlash` | `1278df34f0a7bd2c8588a27f49048aaa05c7db00` | `mit` | 1.46 GiB | no (very tight) | Target weights exceed the Spark0 ~119.7 GiB VRAM baseline; keep as a long-horizon reference only. |
| 6 | `MiniMaxAI/MiniMax-M2.7` | `refs/heads/main` | `d494266a4affc0d2995ba1fa35c8481cbd84294b` | `other` | 214.33 GiB | `z-lab/MiniMax-M2.7-DFlash` | `c36fb6e5ad86afc64ecc9824ab5a80d2ae640df3` (HF API) | `UNKNOWN` | 1.04 GiB | no | Target weights are not single-Spark plausible. Draft metadata is visible via HF API, but raw model card fetch returned HTTP 401 at the pinned SHA; treat license as unknown until verified. |
| 7 | `moonshotai/Kimi-K2.5` | `refs/heads/main` | `4d01dfe0332d63057c186e0b262165819efb6611` | `modified-mit` | 554.30 GiB | `z-lab/Kimi-K2.5-DFlash` | `e2db14df8337367b5eae8a6c206ea0d7d01a42a8` | `mit` | 6.48 GiB | no | Target weights are far beyond single-Spark; keep as a paired DFlash provenance reference only. |
| 8 | `moonshotai/Kimi-K2.6` | `refs/heads/main` | `b5aabbfb20227ed42becbf5541dbffd213942c58` | `other` | 554.30 GiB | `z-lab/Kimi-K2.6-DFlash` | `c1462ef46589f6ccb3eca424bffef94d72354ea9` | `mit` | 6.48 GiB | no | Target weights are far beyond single-Spark; keep as a paired DFlash provenance reference only. |

## Public quality prior (metadata-only pointers)

These priors are meant for *staging decisions*, not “winner” claims. Model-card
tables can differ in prompt formats, tool availability, contamination policy,
and scoring. Keep the exact pinned model-card revision when referencing any
numbers.

### Gemma 4 (instruction-tuned)

The pinned `google/gemma-4-26B-A4B-it` model card includes a benchmark table
covering (non-exhaustive): `MMLU Pro`, `GPQA Diamond`, `LiveCodeBench v6`,
`Codeforces ELO`, `Tau2`, and `BigBench Extra Hard`, plus multimodal rows like
`MMMU Pro`, `OmniDocBench 1.5`, and `MATH-Vision`. The table includes a row
named `AIME 2026 no tools`, so treat the card as at-least-2026-era evaluation.

Selected table entries (model card, vendor-reported; keep comparability limits
in mind):

- `Gemma 4 26B A4B` (the DFlash target family):
  - `MMLU Pro`: 82.6%
  - `GPQA Diamond`: 82.3%
  - `LiveCodeBench v6`: 77.1%
- The same card also reports `Gemma 4 31B` numbers (e.g. `MMLU Pro`: 85.2%).

Pinned source:

- `https://huggingface.co/google/gemma-4-26B-A4B-it/blob/462a98a12e28e2cbcfccaf78fe41e3e50235e6ae/README.md`

### GPT-OSS

The pinned `openai/gpt-oss-20b` model card does not embed a numeric benchmark
table in plain text at the pinned revision, but it links to an arXiv model card
and an OpenAI blog post. It also states that “all evals were performed with the
same MXFP4 quantization”.

Pinned sources:

- `https://huggingface.co/openai/gpt-oss-20b/blob/6cee5e81ee83917806bbde320786a8fb61efebee/README.md`
- The README links `https://arxiv.org/abs/2508.10925` (model card) and `https://openai.com/index/introducing-gpt-oss/` (blog).

## Model-card requirements (DFlash)

- Each DFlash draft checkpoint must be paired with the **exact** named target checkpoint.
- Do not compare DFlash speedup against a target run that falls back to CPU or uses a mismatched quantization/stack.

## Metadata commands (no downloads)

```sh
./scripts/upstream_hf_api_report.sh openai/gpt-oss-20b --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/gpt-oss-20b-DFlash --sum-safetensors
./scripts/upstream_hf_api_report.sh meta-llama/Llama-3.1-8B-Instruct --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/LLaMA3.1-8B-Instruct-DFlash-UltraChat --sum-safetensors
./scripts/upstream_hf_api_report.sh openai/gpt-oss-120b --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/gpt-oss-120b-DFlash --sum-safetensors
./scripts/upstream_hf_api_report.sh google/gemma-4-26B-A4B-it --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/gemma-4-26B-A4B-it-DFlash --sum-safetensors
./scripts/upstream_hf_api_report.sh google/gemma-4-31B-it --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/gemma-4-31B-it-DFlash --sum-safetensors
./scripts/upstream_hf_api_report.sh MiniMaxAI/MiniMax-M2.7 --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/MiniMax-M2.7-DFlash --sum-safetensors
./scripts/upstream_hf_api_report.sh moonshotai/Kimi-K2.5 --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/Kimi-K2.5-DFlash --sum-safetensors
./scripts/upstream_hf_api_report.sh moonshotai/Kimi-K2.6 --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/Kimi-K2.6-DFlash --sum-safetensors
```
