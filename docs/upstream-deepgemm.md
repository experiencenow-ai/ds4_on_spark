# Upstream: deepseek-ai/DeepGEMM

## Source

- Repo: `https://github.com/deepseek-ai/DeepGEMM`
- Ref: `refs/tags/v2.1.1.post3`
- Commit: `c9f8b34dcdacc20aa746b786f983492c51072870`
- License: MIT (see upstream `LICENSE`)

## Why we track it

DeepGEMM provides optimized GEMM kernels and related CUDA plumbing that may be relevant for Spark GPU nodes when comparing kernel-level performance/behavior.

## Build notes (high level)

- Expect a CUDA toolchain requirement and architecture-specific tuning.
- Treat as a reference dependency: do not vendor; fetch pinned commit and build out-of-tree.

## Fetch

```bash
./scripts/fetch_upstreams.sh deepgemm
```
