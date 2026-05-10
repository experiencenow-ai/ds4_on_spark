# Upstream: DFlash candidate pairs (non-Qwen)

This note tracks DFlash speculative decoding candidate pairs beyond the Qwen
family. It is metadata-only: no model weights were downloaded while preparing
this document.

- Pinned-at: 2026-05-10 (UTC)
- Safety policy: use `GIT_LFS_SKIP_SMUDGE=1`, Hugging Face API metadata, or local
  Spark paths first; large weight fetches require explicit human approval.

Qwen-family target/draft pairs are tracked separately in
[`docs/upstream-qwen-dflash.md`](upstream-qwen-dflash.md).

## Candidate Matrix

| Priority | Target | Target ref | Target commit / SHA | Target license | Target safetensors | Draft / accelerator | Draft commit / SHA | Draft license | Draft safetensors | Single Spark? | Why test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `google/gemma-4-26B-A4B-it` | `refs/heads/main` | `462a98a12e28e2cbcfccaf78fe41e3e50235e6ae` | `apache-2.0` | 48.07 GiB | `z-lab/gemma-4-26B-A4B-it-DFlash` | `77d4202772dfe50b2396ec7bac9cfffc7b9e7057` | `apache-2.0` | 0.80 GiB | likely | Open, single-Spark-sized instruction-tuned baseline with an official DFlash drafter. |
| 2 | `google/gemma-4-31B-it` | `refs/heads/main` | `ba74f5b6c647c0911554e50278d6f6f4477f9010` | `apache-2.0` | 58.25 GiB | `z-lab/gemma-4-31B-it-DFlash` | `eabd648301ce28583cc14757912e5e0f84e152e1` | `apache-2.0` | 2.86 GiB | likely | Larger Gemma comparator with a bigger drafter; useful to check scaling behavior vs 26B class. |

## Model-card requirements (DFlash)

- Each DFlash draft checkpoint must be paired with the **exact** named target checkpoint.
- Do not compare DFlash speedup against a target run that falls back to CPU or uses a mismatched quantization/stack.

## Metadata commands (no downloads)

```sh
./scripts/upstream_hf_api_report.sh google/gemma-4-26B-A4B-it --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/gemma-4-26B-A4B-it-DFlash --sum-safetensors
./scripts/upstream_hf_api_report.sh google/gemma-4-31B-it --sum-safetensors
./scripts/upstream_hf_api_report.sh z-lab/gemma-4-31B-it-DFlash --sum-safetensors
```

