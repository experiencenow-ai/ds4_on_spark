# Single-Spark DeepSeek-V4-Flash: runtime + artifact candidate matrix

This note ties together the pinned upstreams into concrete “one Spark produces tokens” candidates.

This repo does **not** vendor model weights. Any GGUF or official checkpoint download remains a human-approved fixture.

## Memory baseline (Spark0)

From [`docs/spark0-hardware-baseline-2026-05-09.md`](spark0-hardware-baseline-2026-05-09.md):

- Host RAM: ~119 GiB
- GPU VRAM (GB10): ~119.7 GiB

Rule of thumb: artifacts above ~100 GiB leave limited headroom for runtime + KV/cache.

## Candidates (GGUF path)

The sizes below are taken from Git LFS pointer metadata (no GGUF downloads), as documented in [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md).

| Candidate | Runtime (pinned) | Artifact (pinned) | License | Size (GiB) | Single-Spark plausibility | Notes |
| --- | --- | --- | --- | ---: | --- | --- |
| A | `ssweens/llama.cpp-deepseek-v4` (`bb648b31e137a44b1ee72907e20ad8fb1f21d644`) | `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` IQ1_M (`1387c955943485e273ba1b0f7564b4134cf0e3cb`) | MIT / MIT | 62.9 | Plausible | Most headroom for KV/cache among pinned GGUF candidates; runtime is a DeepSeek-V4-capable llama.cpp fork (CPU/CUDA/ROCm/Vulkan claimed). |
| B | `ssweens/llama.cpp-deepseek-v4` (`bb648b31e137a44b1ee72907e20ad8fb1f21d644`) | `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` IQ2_XXS shards (`1387c955943485e273ba1b0f7564b4134cf0e3cb`) | MIT / MIT | 72.6 | Plausible | Sharded; requires the same V4-capable llama.cpp fork; verify shard auto-load behavior + KV/cache sizing. |
| J | `ssweens/llama.cpp-deepseek-v4` (`bb648b31e137a44b1ee72907e20ad8fb1f21d644`) | `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` IQ3_XXS shards (`1387c955943485e273ba1b0f7564b4134cf0e3cb`) | MIT / MIT | 104.2 | Plausible but tight | Leaves limited headroom for KV/cache on Spark0 baseline; keep as a reference in case IQ1/2 variants regress. |
| C | `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` (`9222e55c13c965ccb7e9104fda58796edd84a732`) | `antirez/deepseek-v4-gguf` IQ2XXS (`9cb905d99321dbefb0e7c63fdb9bbd4d8aa7126a`) | MIT / MIT | 80.8 | Plausible | Reported running on a single GB10-class Spark: `https://forums.developer.nvidia.com/t/deepseek-v4-flash-iq2xxs-on-a-single-gb10/368970` |
| D | `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` (`9222e55c13c965ccb7e9104fda58796edd84a732`) | `teamblobfish/DeepSeek-V4-Flash-GGUF` IQ2_XXS-XL shards (`71c338a6503e888223f31be9589520bfad14e4a8`) | MIT / MIT | 73.1 | Plausible | Most Spark-targeted CUDA fork in manifest; shard auto-load behavior is documented upstream (point at shard 00001). |
| E | `cchuter/llama.cpp` `feat/v4-port` (`19b63dc368dfef6db6783e5ba3143927b7ed1c96`) | `teamblobfish/DeepSeek-V4-Flash-GGUF` IQ2_XS-XL shards (`71c338a6503e888223f31be9589520bfad14e4a8`) | MIT / MIT | 81.0 | Plausible | Popular “V4 loader + kernels” fork referenced by teamblobfish; more headroom than ~90–100 GiB options. |
| I | `cchuter/llama.cpp` `feat/v4-port` (`19b63dc368dfef6db6783e5ba3143927b7ed1c96`) | `teamblobfish/DeepSeek-V4-Flash-GGUF` IQ1_S-XL shards (`71c338a6503e888223f31be9589520bfad14e4a8`) | MIT / MIT | 57.3 | Plausible | Smaller teamblobfish quant (sharded) with the most KV/cache headroom among pinned GGUF options in that repo. |
| K | `cchuter/llama.cpp` `feat/v4-port` (`19b63dc368dfef6db6783e5ba3143927b7ed1c96`) | `teamblobfish/DeepSeek-V4-Flash-GGUF` IQ1_M-XL shards (`71c338a6503e888223f31be9589520bfad14e4a8`) | MIT / MIT | 63.2 | Plausible | Still significant headroom for KV/cache vs ~70–100 GiB candidates; sharded artifact. |
| F | `nisparks/llama.cpp` `wip/deepseek-v4-support` (`9d364087024da141510267e6b269ee495ca45176`) | `Preyazz/DeepSeek-V4-Flash-GGUF` Q2_K (`6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d`) | MIT / MIT | 96.2 | Plausible but tight | Leaves limited headroom for KV/cache; `wip/deepseek-v4-support` is explicitly “reference/WIP” upstream (PR `#22378` was closed). |
| G | `nisparks/llama.cpp` `wip/deepseek-v4-support` (`9d364087024da141510267e6b269ee495ca45176`) | `lovedheart/DeepSeek-V4-Flash-GGUF` Q2_K shards (`cd42deba41ac0536e68b125dfc367197b0ec3038`) | MIT / **UNKNOWN** | 93.6 | Plausible but tight (license blocker) | Treat as blocked until a human verifies licensing; also sharded. |
| H | `antirez/ds4` (`e88a51fdac110ca5c0e0da06f1a27d4c0313b563`) | `antirez/deepseek-v4-gguf` IQ2XXS (`9cb905d99321dbefb0e7c63fdb9bbd4d8aa7126a`) | MIT / MIT | 80.8 | Not Spark-ready (runtime mismatch) | `ds4` is Metal-first (macOS); useful for semantics/KV-cache reference, but not a direct Spark runtime today. |

Fixture provenance note:

- If a human approves a GGUF download, record and verify the artifact `sha256` against the HF API `lfs.sha256` values listed in [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md). This lets us validate fixtures without trusting filenames.
- For `antirez/deepseek-v4-gguf`, there is also a separate MTP sidecar GGUF (~3.5 GiB). Only fetch it if the chosen runtime needs MTP; verify its `sha256` the same way (see `docs/mtp-ds4-reference.md` and `docs/llamacpp-mtp-sidecar-probe.md`).

## Candidates (native checkpoint path)

These are Spark/GB10 bring-up references that operate on the “official” checkpoint layout rather than GGUF, but they all require large human-approved downloads.

Footprint note (no download): as of the pinned commits in [`docs/upstream-manifest.md`](upstream-manifest.md), the HF API reports:

- Flash `deepseek-ai/DeepSeek-V4-Flash` (`6976c7ff1b30a1b2cb7805021b8ba4684041f136`): 148.66 GiB total `*.safetensors`
- Flash-Base `deepseek-ai/DeepSeek-V4-Flash-Base` (`8855555deef230a27a21a8d6f294b7b7497759b6`): 274.44 GiB total `*.safetensors`

Reproduce:

```bash
./scripts/upstream_hf_api_report.sh deepseek-ai/DeepSeek-V4-Flash --sum-safetensors
./scripts/upstream_hf_api_report.sh deepseek-ai/DeepSeek-V4-Flash-Base --sum-safetensors
```

| Candidate | Runtime (pinned) | Checkpoint source | License | Single-Spark plausibility | Notes |
| --- | --- | --- | --- | --- | --- |
| F | `devid791/dsv4-flash-gb10-runtime` (`244cb11d3ee3adfd96bd0f95d6a91649af7af45d`) | HF `deepseek-ai/DeepSeek-V4-Flash` (BF16 + routed expert quantize to MXFP4 at load) | Apache-2.0 | Unknown (requires on-hardware validation) | Most directly GB10/Spark-focused “native layout” proof-of-life; requires a large HF snapshot download. |
| G | `Mockingjay1316/deepseek-v4-flash-spark` (`08045f89d9716d3249ce834be1a1b1d91fd40859`) | Official checkpoint + prune pipeline | MIT | Plausible only after pruning | Upstream README claims unpruned FP4 checkpoint does not fit on 128 GB unified memory; pruning to fewer experts can reduce size (~85 GB claimed). |
| H | `bigs/deepseek-v4-flash-dgx-spark` (`4410e814a76a1a9d662576e2a35fa4a8965d2edc`) | Official checkpoint | **UNKNOWN** | Unknown (license blocker) | Treat as blocked until licensing is clarified; also out-of-scope for non-hardware automation. |

## Candidates (quantized safetensors snapshots)

These are community conversions distributed as `*.safetensors` shards. This repo treats them as **fixtures only** (no downloads by automation).

| Candidate | Artifact (pinned) | License | Size (GiB) | Single-Spark plausibility | Runtime status |
| --- | --- | --- | ---: | --- | --- |
| L | `bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target` (`4ce0d4ac6bd35b63b68dfc813d0ae07497c4bf49`) | MIT | 82.34 | Plausible | Blocked: runtime/loader support not yet pinned; see `docs/upstream-quantized-v4-flash-safetensors.md`. |

## What this repo should do next (intake posture)

- Keep the manifest pins current and reproducible (`./scripts/upstream_verify_pins.sh`).
- Keep GGUF candidates metadata-only (HF LFS pointer/HTTP API reports only).
- For “one Spark produces tokens”, prioritize GGUF artifacts in the ~70–85 GiB range paired with a Spark-targeted V4-capable runtime fork.

## References

- Pinned upstreams: [`docs/upstream-manifest.md`](upstream-manifest.md)
- GGUF candidates + sizes: [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md)
- Spark bring-up refs: [`docs/upstream-spark-v4-bringup.md`](upstream-spark-v4-bringup.md)
- llama.cpp forks: [`docs/upstream-llama-cpp.md`](upstream-llama-cpp.md)
