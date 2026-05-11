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
| 2 | `google/gemma-4-26B-A4B-it` | `refs/heads/main` | `462a98a12e28e2cbcfccaf78fe41e3e50235e6ae` | `apache-2.0` | 48.07 GiB | `z-lab/gemma-4-26B-A4B-it-DFlash` | `77d4202772dfe50b2396ec7bac9cfffc7b9e7057` | `apache-2.0` | 0.80 GiB | likely | Open, single-Spark-sized instruction-tuned baseline with an official DFlash drafter. |
| 3 | `google/gemma-4-31B-it` | `refs/heads/main` | `ba74f5b6c647c0911554e50278d6f6f4477f9010` | `apache-2.0` | 58.25 GiB | `z-lab/gemma-4-31B-it-DFlash` | `eabd648301ce28583cc14757912e5e0f84e152e1` | `apache-2.0` | 2.86 GiB | likely | Larger Gemma comparator with a bigger drafter; useful to check scaling behavior vs 26B class. |
| 4 | `openai/gpt-oss-120b` | `refs/heads/main` | `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` | `apache-2.0` | 121.54 GiB | `z-lab/gpt-oss-120b-DFlash` | `1278df34f0a7bd2c8588a27f49048aaa05c7db00` | `mit` | 1.46 GiB | no (very tight) | Target weights exceed the Spark0 ~119.7 GiB VRAM baseline; keep as a long-horizon reference only. |
| 5 | `MiniMaxAI/MiniMax-M2.7` | `refs/heads/main` | `d494266a4affc0d2995ba1fa35c8481cbd84294b` | `other` | 214.33 GiB | `z-lab/MiniMax-M2.7-DFlash` | `0b9e26e35d991dc03f6b4198fb9681a1ab053e70` (HF API) | `UNKNOWN` | 1.04 GiB | no | Target weights are not single-Spark plausible. Draft metadata is visible via HF API, but raw model card fetch returned HTTP 401 at the pinned SHA; treat license as unknown until verified. |
| 6 | `moonshotai/Kimi-K2.5` | `refs/heads/main` | `4d01dfe0332d63057c186e0b262165819efb6611` | `modified-mit` | 554.30 GiB | `z-lab/Kimi-K2.5-DFlash` | `e2db14df8337367b5eae8a6c206ea0d7d01a42a8` | `mit` | 6.48 GiB | no | Target weights are far beyond single-Spark; keep as a paired DFlash provenance reference only. |
| 7 | `moonshotai/Kimi-K2.6` | `refs/heads/main` | `2755962d07cb42aa2d988a35bcb65cd4a9c2de82` | `modified-mit` | 554.30 GiB | `z-lab/Kimi-K2.6-DFlash` | `c1462ef46589f6ccb3eca424bffef94d72354ea9` | `mit` | 6.48 GiB | no | Target weights are far beyond single-Spark; keep as a paired DFlash provenance reference only. |

## Model-card requirements (DFlash)

- Each DFlash draft checkpoint must be paired with the **exact** named target checkpoint.
- Do not compare DFlash speedup against a target run that falls back to CPU or uses a mismatched quantization/stack.

## Metadata commands (no downloads)

```sh
./scripts/upstream_hf_api_report.sh openai/gpt-oss-20b --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/gpt-oss-20b-DFlash --sum-safetensors
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
