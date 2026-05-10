# Upstream: Qwen and DFlash candidates

This note adds Qwen-family comparison targets and DFlash speculative decoding to
the Spark0 evaluation matrix. It is metadata-only: no model weights were
downloaded while preparing this document.

- Pinned-at: 2026-05-10 (UTC)
- Primary goal: compare DeepSeek V4 Flash against runnable Qwen baselines on one
  Spark, then test DFlash only where an exact target/draft pair exists.
- Safety policy: use `GIT_LFS_SKIP_SMUDGE=1`, Hugging Face API metadata, or local
  Spark paths first; large weight fetches require explicit human approval.

## Candidate Matrix

| Priority | Target | Target ref | Target commit / SHA | Target safetensors | Draft / accelerator | Draft commit / SHA | Draft safetensors | Why test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | `refs/heads/main` | `dcaee4d4dfc5ee71ad501f01f530e5652438fde0` | 29.03 GiB | `z-lab/Qwen3-Coder-30B-A3B-DFlash` | `98ca0e3e2e6a372f2789d3a5e146566194084317` | 0.88 GiB | Smallest strong coding target with an official DFlash drafter. Good first Qwen smoke test. |
| 2 | `Qwen/Qwen3.6-35B-A3B-FP8` | `refs/heads/main` | `95a723d08a9490559dae23d0cff1d9466213d989` | 34.89 GiB | `z-lab/Qwen3.6-35B-A3B-DFlash` | `42d3b34d588423cdae7ba8f53a8cf7789346a719` | 0.88 GiB | Spark-sized FP8 target, 3B active params, and DFlash pair. Best near-term latency/throughput comparison. |
| 3 | `Qwen/Qwen3.6-27B` | `refs/heads/main` | `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` | 51.75 GiB | `z-lab/Qwen3.6-27B-DFlash` | `0919688658996800f86b895034249700e9481106` | 3.22 GiB | Dense-ish 27B reference with a larger drafter; useful if FP8 MoE behavior hides bottlenecks. |
| 4 | `Qwen/Qwen3-Coder-Next-FP8` | `refs/heads/main` | `da6e2ed27304dd39abadd9c82ef50e8de67bdd4c` | 74.86 GiB | `z-lab/Qwen3-Coder-Next-DFlash` | `6d741db11b89d7ea80a423b109f0424817ce8f1b` | 0.88 GiB | Larger 80B/3B-active coding-agent target; plausible on Spark0, but should run after the smaller candidates. |
| 5 | `Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8` | `refs/heads/main` | `003f183a92fbe5b9a8325aaa8b2ae797c91dd90f` | not measured here | none selected | n/a | n/a | Dual-Spark or future reference only unless a smaller local quantized artifact appears. |

The DFlash implementation reference is `z-lab/dflash`
`94e4abc5e0c31b67bc1a9d30f1cc34ece28a8756` on `refs/heads/main`.

## Measurement Order

1. Run a no-download vLLM package/CUDA probe on Spark0.
2. If a target is already present on Spark0, run a short non-DFlash generation
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

If the model is not already on Spark0, set `ALLOW_FETCH=1` only after approving
the large download. Reports record the `REMOTE_*` env values, so do not place
tokens or secrets there.

## Automation Ownership

- Upstream loop: refresh this document, exact commits, licenses, file sizes, and
  runtime requirements for Qwen/DFlash candidates.
- Baseline loop: run target-only Qwen and paired DFlash probes on Spark0 when
  artifacts are already present or a download has been approved.
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
