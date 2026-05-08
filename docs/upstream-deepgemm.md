# Upstream: deepseek-ai/DeepGEMM

## Source

- Repo: `https://github.com/deepseek-ai/DeepGEMM`
- Ref: `refs/tags/v2.1.1.post3`
- Commit: `c9f8b34dcdacc20aa746b786f983492c51072870`
- License: MIT (see upstream `LICENSE`)

## Why we track it

DeepGEMM provides optimized GEMM kernels and related CUDA plumbing that may be relevant for Spark GPU nodes when comparing kernel-level performance/behavior.

## Build notes (high level)

- Requirements (from upstream README, summarized):
  - NVIDIA SM90 or SM100 GPUs
  - CUDA Toolkit 12.3+ (SM90), and 12.9+ recommended for best performance
  - PyTorch 2.1+
  - C++20-capable compiler + Python 3.8+
- Upstream uses git submodules (e.g. CUTLASS + `{fmt}`); `./scripts/fetch_upstreams.sh deepgemm` does not initialize submodules.
  - If you actually need to build/test it locally, run `git submodule update --init --recursive` inside `upstreams/deepgemm/` (expect extra code downloads).
- Treat as a reference dependency: do not vendor; fetch pinned commit and build out-of-tree with a pinned CUDA/PyTorch toolchain tuple.

## Fetch

```bash
./scripts/fetch_upstreams.sh deepgemm
```
