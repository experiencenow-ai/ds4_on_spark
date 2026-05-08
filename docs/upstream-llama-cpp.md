# Upstream: ggml-org/llama.cpp

## Source

- Repo: `https://github.com/ggml-org/llama.cpp`
- Ref: `refs/heads/master`
- Commit: `b46812de78f8fbcb6cf0154947e8633ebc78d9ac`
- License: MIT (see upstream `LICENSE`)

## Why we track it (Spark relevance)

llama.cpp is a useful Spark reference point for:

- ggml tooling (format conversion utilities),
- CPU baselines (AVX2, NUMA considerations),
- GPU build paths (CUDA/HIP/Vulkan), and
- server/runtime ergonomics for quick deployment comparisons.

## Additional Spark references

- NVIDIA DGX Spark playbook: `https://build.nvidia.com/spark/llama-cpp` (end-to-end build + run notes).

## Fetch

```bash
./scripts/fetch_upstreams.sh llama_cpp
```
