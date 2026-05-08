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

## Upstream build/docs pointers

- Install options: `https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md`
- Build guide: `https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md`
- Docker guide: `https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md`

## Build notes (Spark relevance, high level)

- CPU baseline: enable AVX2 (and consider NUMA pinning) for realistic Spark node behavior.
- GPU builds (when applicable): prefer explicit build flags (CUDA/HIP/Vulkan) and validate the device CC / backend at runtime.
- Treat llama.cpp as a reference runtime for “no Python” deployments and for tooling patterns (convert + serve).

## Fetch

```bash
./scripts/fetch_upstreams.sh llama_cpp
```
