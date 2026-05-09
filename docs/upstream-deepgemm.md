# Upstream: deepseek-ai/DeepGEMM

## Source

- Repo: `https://github.com/deepseek-ai/DeepGEMM`
- Ref: `refs/tags/v2.1.1.post3`
- Commit: `c9f8b34dcdacc20aa746b786f983492c51072870`
- License: MIT (see upstream `LICENSE`)

## Why we track it

DeepGEMM provides optimized GEMM kernels and related CUDA plumbing that may be relevant for Spark GPU nodes when comparing kernel-level performance/behavior.

## Pinning notes

- Prefer release tags over `main` for reproducibility when they exist.

## Build notes (upstream, summarized)

- Requirements (from upstream README, summarized):
  - NVIDIA SM90 or SM100 GPUs
  - CUDA Toolkit 12.3+ (SM90), and 12.9+ recommended for best performance
  - PyTorch 2.1+
  - C++20-capable compiler + Python 3.8+
- DeepGEMM uses a lightweight JIT module and compiles kernels at runtime (installation does not require compiling kernels up front).

Spark relevance / architecture warning:

- DGX Spark / GB10 is SM121-class, which is **not** listed in DeepGEMM's upstream support matrix (SM90/SM100 only). Treat DeepGEMM as a learning/reference repo unless/until upstream adds SM12x support or a Spark-specific fork exists.
- Upstream uses git submodules (e.g. CUTLASS + `{fmt}`); `./scripts/fetch_upstreams.sh deepgemm` does not initialize submodules.
  - If you actually need to build/test it locally, run `git submodule update --init --recursive` inside `upstreams/deepgemm/` (expect extra code downloads).
- Upstream includes `develop.sh` / `install.sh`; use those as the canonical entry points if you choose to build the pinned upstream out-of-tree.

## Fetch

```bash
./scripts/fetch_upstreams.sh deepgemm
```
