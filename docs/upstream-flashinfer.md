# Upstream: flashinfer-ai/flashinfer

FlashInfer is a kernel library (attention + GEMM plumbing) used by modern local-inference stacks, including vLLM’s `flashinfer-cutlass` backend for NVFP4 GEMM paths.

## Source

- Repo: `https://github.com/flashinfer-ai/flashinfer`
- Ref: `refs/tags/v0.6.11`
- Commit: `f6717ff6bc6061c4eb0474576746ee1b42bd6325`
- License: Apache-2.0 (see upstream `LICENSE`)

## Why we track it (Spark relevance)

- Tracks Blackwell/SM121-relevant kernel plumbing that can affect end-to-end throughput for vLLM/Transformers stacks.
- Helps interpret upstream runtime knobs that reference FlashInfer (for example `VLLM_NVFP4_GEMM_BACKEND=flashinfer-cutlass` in AEON-7 docs).
- Provides a provenance anchor when runtime releases cite “FlashInfer” changes without pinning exact commits.

## Notes / guardrails

- Treat FlashInfer as a **runtime/kernel reference** only; it does not imply a claim about any particular model family (DeepSeek V4 Flash vs Qwen vs Ling) unless we reproduce numbers locally.
- This repo should not vendor FlashInfer sources; fetch on-demand via `./scripts/fetch_upstreams.sh`.

## Fetch

```bash
./scripts/fetch_upstreams.sh flashinfer
```

