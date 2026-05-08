# Upstream: ggml-org/llama.cpp

## Source

- Repo: `https://github.com/ggml-org/llama.cpp`
- Ref: `refs/tags/b8833`
- Commit: `45cac7ca703fb9085eae62b9121fca01d20177f6`
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

- Install options: `https://github.com/ggml-org/llama.cpp/blob/b8833/docs/install.md`
- Build guide: `https://github.com/ggml-org/llama.cpp/blob/b8833/docs/build.md`
- Docker guide: `https://github.com/ggml-org/llama.cpp/blob/b8833/docs/docker.md`

## Build notes (Spark relevance, high level)

- CPU baseline: enable AVX2 (and consider NUMA pinning) for realistic Spark node behavior.
- GPU builds (when applicable): prefer explicit build flags (CUDA/HIP/Vulkan) and validate the device CC / backend at runtime.
- Example CUDA build invocation (from upstream build docs):
  - `cmake -B build -DGGML_CUDA=ON`
  - Optionally pin compute capabilities explicitly: `-DCMAKE_CUDA_ARCHITECTURES="86;89"` (set this for your Spark GPUs).
- Unified-memory fallback (Linux): upstream documents `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` as a way to swap to system RAM when VRAM is exhausted (often slower, but can avoid OOM crashes).
- Treat llama.cpp as a reference runtime for “no Python” deployments and for tooling patterns (convert + serve).

## Fetch

```bash
./scripts/fetch_upstreams.sh llama_cpp
```
