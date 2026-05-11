# Upstream: model comparison candidates

This note tracks Qwen, Ling, and DFlash speculative-decoding candidates for the
Spark0 evaluation matrix. It is metadata-only: no model weights were downloaded
while preparing this document.

- Pinned-at: 2026-05-11 (UTC)
- Primary goal: compare DeepSeek V4 Flash against runnable Ling and Qwen
  baselines on one Spark, then test DFlash only where an exact target/draft pair
  exists.
- Safety policy: use `GIT_LFS_SKIP_SMUDGE=1`, Hugging Face API metadata, or local
  Spark paths first; large weight fetches require explicit human approval.

## Core Comparison Matrix

| Priority | Target | Target ref | Target commit / SHA | Target license | Target safetensors | Draft / accelerator | Draft commit / SHA | Draft license | Draft safetensors | Single Spark? | Why test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | `refs/heads/main` | `dcaee4d4dfc5ee71ad501f01f530e5652438fde0` | `apache-2.0` | 29.03 GiB | `z-lab/Qwen3-Coder-30B-A3B-DFlash` | `98ca0e3e2e6a372f2789d3a5e146566194084317` | `mit` | 0.88 GiB | likely | Smallest strong coding target with an official DFlash drafter. Good first Qwen smoke test. |
| 2 | `Qwen/Qwen3.6-35B-A3B-FP8` | `refs/heads/main` | `95a723d08a9490559dae23d0cff1d9466213d989` | `apache-2.0` | 34.89 GiB | `z-lab/Qwen3.6-35B-A3B-DFlash` | `42d3b34d588423cdae7ba8f53a8cf7789346a719` | `mit` | 0.88 GiB | likely | Spark-sized FP8 target, 3B active params, and DFlash pair. Best near-term latency/throughput comparison. |
| 3 | `Qwen/Qwen3.5-27B` | `refs/heads/main` | `fc05daec18b0a78c049392ed2e771dde82bdf654` | `apache-2.0` | 51.75 GiB | `z-lab/Qwen3.5-27B-DFlash` | `b0400439c04be32c24e04d9dce3821b582c1a68a` | `mit` | 3.22 GiB | likely | User-requested Qwen 27B comparator; DFlash card says it is paired with this exact target and trained at 4096 context. |
| 4 | `Qwen/Qwen3.6-27B` | `refs/heads/main` | `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` | `apache-2.0` | 51.75 GiB | `z-lab/Qwen3.6-27B-DFlash` | `0919688658996800f86b895034249700e9481106` | `mit` | 3.22 GiB | likely | Newer 27B comparator; DFlash card warns inference support may still be incomplete because of architecture changes. |
| 5 | `inclusionAI/Ling-2.6-flash-int4` | `refs/heads/main` | `1bff63aa1f869e89499d52363790a119fd282edf` | `mit` | 60.38 GiB | none found | n/a | n/a | n/a | maybe | Ling 2.6 comparison baseline; smallest official Ling-2.6-flash precision found so far. |
| 6 | `inclusionAI/Ling-2.6-flash-fp8` | `refs/heads/main` | `8bc416b60fe28be33303d57bb77dd826445a1eb1` | `mit` | 101.48 GiB | none found | n/a | n/a | n/a | maybe | Higher-precision Ling 2.6 comparator if Spark0 has enough memory headroom (tight); test after INT4. |
| 7 | `Qwen/Qwen3-Coder-Next-FP8` | `refs/heads/main` | `da6e2ed27304dd39abadd9c82ef50e8de67bdd4c` | `apache-2.0` | 74.86 GiB | `z-lab/Qwen3-Coder-Next-DFlash` | `6d741db11b89d7ea80a423b109f0424817ce8f1b` | `mit` | 0.88 GiB | maybe | Larger 80B/3B-active coding-agent target; plausible on Spark0, but should run after the smaller candidates. |
| 8 | `Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8` | `refs/heads/main` | `003f183a92fbe5b9a8325aaa8b2ae797c91dd90f` | `apache-2.0` | not measured here | none selected | n/a | n/a | n/a | no | Dual-Spark or future reference only unless a smaller local quantized artifact appears. |

The DFlash implementation reference is `z-lab/dflash`
`94e4abc5e0c31b67bc1a9d30f1cc34ece28a8756` on `refs/heads/main` (`MIT`).

Draft model cards (at the pinned draft commits) reference:

- vLLM: `vllm-project/vllm` at `refs/pull/40898/head`
- SGLang: `sgl-project/sglang` at `refs/pull/20547/head`

## Model-card Requirements (DFlash)

- Each DFlash draft checkpoint must be paired with the **exact** named target checkpoint.
- Treat DFlash drafts as `trust_remote_code` until proven otherwise; do not enable this in a shared runtime without review.
- Do not compare DFlash speedup against a target run that falls back to CPU or uses a mismatched quantization/stack.

## Metadata Commands (No Downloads)

The table above is derived from Hugging Face API metadata:

```sh
./scripts/upstream_hf_api_report.sh Qwen/Qwen3.6-35B-A3B-FP8
./scripts/upstream_hf_api_report.sh Qwen/Qwen3.6-35B-A3B-FP8 --sum-safetensors
```

## DFlash Expansion Candidates

Use this table after the core rows above or when a target is already staged on
Spark0. A DFlash row is only valid when the draft checkpoint matches the exact
target checkpoint named by its model card.

| Target | Target commit / SHA | Target safetensors | DFlash draft | Draft commit / SHA | Draft safetensors | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `Qwen/Qwen3.5-9B` | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | 17.98 GiB | `z-lab/Qwen3.5-9B-DFlash` | `492f4b532a957a50561e1418e5a3f31690f127f4` | 1.95 GiB | Best cheap DFlash plumbing test if 27B downloads are not staged yet. |
| `Qwen/Qwen3.5-4B` | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | 8.68 GiB | `z-lab/Qwen3.5-4B-DFlash` | `96899cc270945f554998309580b08a04a05a3187` | 1.00 GiB | Lowest-cost target/draft sanity check for DFlash launch syntax and counters. |
| `Qwen/Qwen3.5-35B-A3B` | `59d61f3ce65a6d9863b86d2e96597125219dc754` | 66.97 GiB | `z-lab/Qwen3.5-35B-A3B-DFlash` | `a6ab3a277f856d91c43f28711611e7929073d56d` | 0.88 GiB | MoE A3B target; likely single-Spark plausible but less headroom than FP8 A3B. Stage after smaller DFlash plumbing tests. |
| `google/gemma-4-26B-A4B-it` | `462a98a12e28e2cbcfccaf78fe41e3e50235e6ae` | 48.07 GiB | `z-lab/gemma-4-26B-A4B-it-DFlash` | `77d4202772dfe50b2396ec7bac9cfffc7b9e7057` | 0.80 GiB | Promising non-Qwen DFlash pair; multimodal IT target (not directly comparable to DS4/Ling/Qwen text-only runs). |
| `google/gemma-4-31B-it` | `ba74f5b6c647c0911554e50278d6f6f4477f9010` | 58.25 GiB | `z-lab/gemma-4-31B-it-DFlash` | `eabd648301ce28583cc14757912e5e0f84e152e1` | 2.86 GiB | Larger non-Qwen DFlash pair; multimodal IT target (not directly comparable to DS4/Ling/Qwen text-only runs). |
| `openai/gpt-oss-20b` | `6cee5e81ee83917806bbde320786a8fb61efebee` | 25.63 GiB | `z-lab/gpt-oss-20b-DFlash` | `d53f6551543204c859e8bbaaddbd15d11b447af9` | 1.46 GiB | Open target/draft pair; good generic DFlash smoke test when Qwen artifacts are not staged. |
| `moonshotai/Kimi-K2.5` | `4d01dfe0332d63057c186e0b262165819efb6611` | 554.30 GiB | `z-lab/Kimi-K2.5-DFlash` | `e2db14df8337367b5eae8a6c206ea0d7d01a42a8` | 6.48 GiB | **Not single-Spark** (target is 554 GiB); keep as paired DFlash provenance reference only. |
| `meta-llama/Llama-3.1-8B-Instruct` | gated target | not measured here | `z-lab/LLaMA3.1-8B-Instruct-DFlash-UltraChat` | `d3af30def9601abdd10810aba220d692f0e803f0` | 1.95 GiB | Exploratory; gated target and not directly comparable to DS4/Ling/Qwen. |

No Ling-2.6-flash DFlash drafter was found in the checked Z Lab/Hugging Face
search results as of 2026-05-11. Keep Ling in the target-only comparison set and
watch for a paired drafter later.

## Public quality prior (model cards, metadata-only)

These priors are taken from **vendor/author model cards** and are not directly comparable across different benchmark harnesses. Use them only to decide what to stage first; prefer local Spark quality runs for decisions.

### Qwen3.6 family (Qwen model cards)

From `Qwen/Qwen3.6-27B` model card (`6a9e13bd6fc8f0983b9b99948120bc37f49c13e9`, `last_modified=2026-04-24T02:39:16Z`), the “Benchmark Results → Language → Coding Agent” table reports:

- `Qwen3.6-27B`: SWE-bench Verified `77.2`, Terminal-Bench 2.0 `59.3`, MMLU‑Pro `86.2`, GPQA Diamond `87.8`, LiveCodeBench v6 `83.9`.

From `Qwen/Qwen3.6-35B-A3B-FP8` model card (`95a723d08a9490559dae23d0cff1d9466213d989`, `last_modified=2026-04-24T02:39:23Z`), the analogous table reports:

- `Qwen3.6-35B-A3B`: SWE-bench Verified `73.4`, Terminal-Bench 2.0 `51.5`, MMLU‑Pro `85.2`, LiveCodeBench v6 `80.4`.
- `Qwen3.5-27B` (included in the same comparison table): SWE-bench Verified `75.0`, Terminal-Bench 2.0 `41.6`, MMLU‑Pro `86.1`, LiveCodeBench v6 `80.7`.

Sources (pinned revisions):

- `https://huggingface.co/Qwen/Qwen3.6-27B/blob/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/README.md`
- `https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8/blob/95a723d08a9490559dae23d0cff1d9466213d989/README.md`

### Qwen3-Coder (Qwen model card pointers)

The `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` model card (`dcaee4d4dfc5ee71ad501f01f530e5652438fde0`, `last_modified=2025-12-03T08:20:23Z`) points to external benchmark writeups rather than embedding a numeric table in the README at that revision:

- Blog: `https://qwenlm.github.io/blog/qwen3-coder/`
- GitHub: `https://github.com/QwenLM/Qwen3-Coder`

Treat these as sources for later manual prior extraction (do not cherry-pick vendor numbers into a “winner” claim without noting harness differences).

## Measurement Order

1. Run a no-download vLLM package/CUDA probe on Spark0.
2. If a target is already present on Spark0, run a short target-only generation
   probe first: fixed prompt, `MAX_TOKENS=64`, `TENSOR_PARALLEL_SIZE=1`.
3. Record artifact path, total bytes, sha256, vLLM/SGLang version, CUDA driver,
   load time, generated tokens, wall time, approximate tok/s, and GPU memory.
4. Only after a clean target-only run, test the matching DFlash drafter with the
   same target, prompt, context, and token count.
5. Compare target-only vs DFlash on the same software stack before changing
   quantization, runtime branch, or prompt length.

## vLLM Probe Examples

Target-only, using local paths already staged on Spark:

```sh
REMOTE_VLLM_ENV='ALLOW_RUN=1 VLLM_MODEL=/abs/path/Qwen3-Coder-30B-A3B-Instruct-FP8 MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 VLLM_TRUST_REMOTE_CODE=1' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

DFlash, using the exact paired draft model:

```sh
REMOTE_VLLM_ENV='ALLOW_RUN=1 VLLM_MODEL=/abs/path/Qwen3-Coder-30B-A3B-Instruct-FP8 MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 VLLM_TRUST_REMOTE_CODE=1 VLLM_SPECULATIVE_CONFIG_JSON='\''{"method":"dflash","model":"/abs/path/Qwen3-Coder-30B-A3B-DFlash","num_speculative_tokens":15}'\''' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

For paired runs, prefer the wrapper so target-only and DFlash share the same
prompt/token settings and are labeled consistently in `MODEL_RUNS_CSV`:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
RUN_LABEL=qwen3-coder-30b-a3b \
VLLM_SCOPE_TARGET=qwen_target \
VLLM_SCOPE_DFLASH=qwen_dflash \
VLLM_TARGET_ID=Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8 \
VLLM_TARGET_MODEL=/abs/path/Qwen3-Coder-30B-A3B-Instruct-FP8 \
VLLM_DRAFT_MODEL=/abs/path/Qwen3-Coder-30B-A3B-DFlash \
MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 \
scripts/run_baseline_vllm_dflash_pair.sh spark0@aitopatom-9ab9.local
```

If the model is not already on Spark0, set `ALLOW_FETCH=1` only after approving
the large download. Reports record the `REMOTE_*` env values, so do not place
tokens or secrets there.

## Automation Ownership

- Upstream loop: refresh this document, exact commits, licenses, file sizes, and
  runtime requirements for Ling/Qwen/DFlash candidates.
- Baseline loop: run target-only Ling/Qwen and paired DFlash probes on Spark0
  when artifacts are already present or a download has been approved.
- Model-contract loop: document config/tokenizer/runtime assumptions for any
  Qwen model that becomes a serious performance comparator.
- Scheduler loop: reuse DFlash accept/reject counters as a speculative decoding
  baseline when available; keep DeepSeek MTP and Qwen DFlash metrics separate.

## Gating Notes

- DFlash draft repos are not standalone chat targets; each must match the exact
  target checkpoint named by the model card.
- Do not compare DFlash speedup against a failed or CPU-fallback target-only run.
- Do not mix Qwen DFlash results into DeepSeek V4 Flash MTP claims; both are
  speculative paths, but their draft contracts are different.
- Keep Ling, Qwen, DeepSeek V4 Flash, and native `ds4_on_spark` reports separate
  until the baseline template has enough fields to join them safely.
