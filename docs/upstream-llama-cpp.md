# Upstream: ggml-org/llama.cpp

## Source

- Repo: `https://github.com/ggml-org/llama.cpp`
- Ref: `refs/tags/b9085`
- Commit: `046e2844370208007c116fab448ed4033d77653f`
- License: MIT (see upstream `LICENSE`)

## Why we track it (Spark relevance)

llama.cpp is a useful Spark reference point for:

- ggml tooling (format conversion utilities),
- CPU baselines (AVX2, NUMA considerations),
- GPU build paths (CUDA/HIP/Vulkan), and
- server/runtime ergonomics for quick deployment comparisons.

## Additional Spark references

- NVIDIA DGX Spark playbook: `https://build.nvidia.com/spark/llama-cpp` (end-to-end build + run notes).

## DeepSeek-V4-Flash-specific forks (Spark relevance)

DeepSeek-V4-Flash support is not merged into the pinned `ggml-org/llama.cpp` release tag above. Track these forks as references for V4 bring-up, and pin exact commits for reproducibility.

### antirez/llama.cpp-deepseek-v4-flash

- Repo: `https://github.com/antirez/llama.cpp-deepseek-v4-flash`
- Ref: `refs/heads/main`
- Commit: `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f`
- License: MIT

### nisparks/llama.cpp (wip/deepseek-v4-support)

- Repo: `https://github.com/nisparks/llama.cpp`
- Ref: `refs/heads/wip/deepseek-v4-support`
- Commit: `9d364087024da141510267e6b269ee495ca45176`
- License: MIT
- Notes: WIP branch adding `F8_E4M3_B128` + `MXFP4` types + V4 loader/converter support, referenced by “native FP4/FP8” V4 GGUF artifacts.
  - Upstream PR reference: `ggml-org/llama.cpp` PR `#22378` (“Wip/deepseek v4 support”) was closed and marked “purely for reference”; it pointed at this branch. Some community GGUF repos still reference that PR URL.

### cchuter/llama.cpp (feat/v4-port)

- Repo: `https://github.com/cchuter/llama.cpp`
- Ref: `refs/heads/feat/v4-port`
- Commit: `19b63dc368dfef6db6783e5ba3143927b7ed1c96`
- License: MIT
- Notes: V4-aware fork referenced by `teamblobfish/DeepSeek-V4-Flash-GGUF`; includes V4 loader + V4-specific kernel paths not merged into the pinned `ggml-org/llama.cpp` release tag.

### kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark

- Repo: `https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark`
- Ref: `refs/heads/master`
- Commit: `9222e55c13c965ccb7e9104fda58796edd84a732`
- License: MIT
- Notes: Community fork reportedly running DeepSeek-V4-Flash IQ2XXS GGUF on a single DGX Spark/GB10; validate performance and memory headroom on the actual Spark target.
  - Provenance (report, 2026-05-05): `https://forums.developer.nvidia.com/t/deepseek-v4-flash-iq2xxs-on-a-single-gb10/368970`

## Upstream build/docs pointers

- Install options: `https://github.com/ggml-org/llama.cpp/blob/b9085/docs/install.md`
- Build guide: `https://github.com/ggml-org/llama.cpp/blob/b9085/docs/build.md`
- Docker guide: `https://github.com/ggml-org/llama.cpp/blob/b9085/docs/docker.md`

## Build notes (Spark relevance, high level)

- CPU baseline: enable AVX2 (and consider NUMA pinning) for realistic Spark node behavior.
- GPU builds (when applicable): prefer explicit build flags (CUDA/HIP/Vulkan) and validate the device CC / backend at runtime.
- Example CUDA build invocation (from upstream build docs):
  - `cmake -B build -DGGML_CUDA=ON`
  - Optionally pin compute capabilities explicitly: `-DCMAKE_CUDA_ARCHITECTURES="121"` (Spark GB10 / SM121).
- Unified-memory fallback (Linux): upstream documents `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` as a way to swap to system RAM when VRAM is exhausted (often slower, but can avoid OOM crashes).
- Treat llama.cpp as a reference runtime for “no Python” deployments and for tooling patterns (convert + serve).

## Fetch

```bash
./scripts/fetch_upstreams.sh llama_cpp
```

To fetch the pinned DeepSeek-V4 forks into `./upstreams`:

```bash
./scripts/fetch_upstreams.sh llama_cpp_deepseek_v4_flash
./scripts/fetch_upstreams.sh llama_cpp_deepseek_v4_support_wip
./scripts/fetch_upstreams.sh llama_cpp_deepseek_v4_port_cchuter
./scripts/fetch_upstreams.sh llama_cpp_cuda_spark
```
