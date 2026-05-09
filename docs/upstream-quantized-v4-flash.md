# Upstream: DeepSeek-V4-Flash quantized single-Spark candidates (GGUF)

This repo does **not** vendor model weights. The entries below are **references only** for (a) provenance + licensing and (b) a quick “could this plausibly fit on one Spark?” filter. Any GGUF download remains a human-approved fixture.

## Single-Spark memory baseline (Spark0)

Based on [`docs/spark0-hardware-baseline-2026-05-09.md`](spark0-hardware-baseline-2026-05-09.md), Spark0 has:

- Host RAM: ~119 GiB
- GPU VRAM (GB10): ~119.7 GiB

Treat this as the practical upper bound for “single Spark” artifacts; anything above ~100 GB leaves limited headroom for KV/cache + runtime overhead.

## Candidates (pinned)

Quick scan for “single Spark produces tokens” candidates (Spark0 baseline ~119 GiB host RAM / ~119.7 GiB VRAM):

| Source | Artifact | Size (bytes) | Size (GiB) | Single-Spark plausibility |
| --- | --- | ---: | ---: | --- |
| `antirez/deepseek-v4-gguf` | `...IQ2XXS...chat-v2.gguf` | 86720111200 | 80.8 | Plausible (headroom for KV/cache still required) |
| `Preyazz/DeepSeek-V4-Flash-GGUF` | `DeepSeek-V4-Flash-Q2_K.gguf` | 103283751520 | 96.2 | Plausible but tight (limited KV/cache headroom) |
| `cyberneurova/...-abliterated-GGUF` | `...-Q2_K.gguf` | 98810926400 | 92.0 | Plausible but tight (limited KV/cache headroom) |
| `lovedheart/DeepSeek-V4-Flash-GGUF` | `Q2_K (23 shards)` | 100451521792 | 93.6 | Plausible but tight (license UNKNOWN; sharded; requires V4-capable llama.cpp) |
| `teamblobfish/DeepSeek-V4-Flash-GGUF` | `IQ2_XXS-XL (2 shards)` | 78518818624 | 73.1 | Plausible (sharded; upstream README indicates pointing llama.cpp at shard 00001 auto-loads the rest) |

## Reproducing the size numbers (no downloads)

The GGUF “sizes” above are taken from the Git LFS pointer metadata in a metadata-only clone (i.e. `GIT_LFS_SKIP_SMUDGE=1` / LFS filters disabled). This lets us record exact byte counts without fetching multi‑GB blobs.

Alternative (no clone): query the Hugging Face HTTP API for per-file sizes:

```bash
./scripts/upstream_hf_api_report.sh antirez/deepseek-v4-gguf --top 50 | rg '\\.gguf$'
```

To reproduce:

```bash
./scripts/fetch_upstreams.sh deepseek_v4_gguf_preyazz
./scripts/upstream_hf_pointer_report.sh deepseek_v4_gguf_preyazz
```

Repeat for other HF GGUF repos (e.g. `deepseek_v4_gguf_antirez`, `deepseek_v4_gguf_batiai`, etc.).

### antirez/deepseek-v4-gguf (DS4-tuned IQ2XXS)

- Source: `https://huggingface.co/antirez/deepseek-v4-gguf` @ `ef3b960827870d69ed0b225c095a617c12d7e80d` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - IQ2XXS: `DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf` (86720111200 bytes, 80.8 GiB)
  - Q4KExperts (too large for single Spark): `DeepSeek-V4-Flash-Q4KExperts-F16HC-F16Compressor-F16Indexer-Q8Attn-Q8Shared-Q8Out-chat-v2.gguf` (164633502304 bytes, 153.3 GiB)
  - MTP sidecar: `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf` (3807602400 bytes, 3.5 GiB)
- Provenance notes:
  - Model card states these quants are “specific for the DS4 inference engine” and links to `https://github.com/antirez/ds4`.
- Single-Spark plausibility:
  - **Plausible** on Spark0-class hardware as a first “one Spark produces tokens” target given the 80.8 GiB (~86.7 GB) footprint and ~120 GiB host/GPU memory; still needs on-hardware validation and careful KV/cache sizing.

### Preyazz/DeepSeek-V4-Flash-GGUF (community Q2_K/Q3_K_M/Q4_K_M)

- Source: `https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF` @ `6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - Q2_K: `DeepSeek-V4-Flash-Q2_K.gguf` (103283751520 bytes, ~96.2 GiB)
  - Q3_K_M: `DeepSeek-V4-Flash-Q3_K_M.gguf` (135535174240 bytes, ~126.2 GiB)
  - Q4_K_M: `DeepSeek-V4-Flash-Q4_K_M.gguf` (172037991008 bytes, ~160.2 GiB)
- Runtime requirement:
  - Model card states it requires a DeepSeek-V4-capable llama.cpp (example reference: `nisparks/llama.cpp` branch `wip/deepseek-v4-support`).
- Single-Spark plausibility:
  - **Q2_K plausible but tight** on Spark0-class hardware (96.2 GiB leaves limited KV/cache headroom).
  - **Q3_K_M/Q4_K_M not plausible** on Spark0-class memory (artifact alone exceeds ~119 GiB host RAM / ~119.7 GiB VRAM).

### batiai/DeepSeek-V4-Flash-GGUF (early-access shards; requires bati.cpp)

- Source: `https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF` @ `70c9597f26a5b4747272477fff37986c4ce484ef` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here; totals are from git-lfs pointer metadata across shards):
  - Q3_K_M: 3 shards (total 135410907136 bytes, ~126.1 GiB)
  - Q4_K_M: 4 shards (total 171918014464 bytes, ~160.1 GiB)
- Runtime requirement:
  - Model card states inference requires `batiai/bati.cpp` (not mainline `ggml-org/llama.cpp`).
- Single-Spark plausibility:
  - **Not plausible** on Spark0-class memory (Q3_K_M total exceeds ~119 GiB host RAM / ~119.7 GiB VRAM).

### lovedheart/DeepSeek-V4-Flash-GGUF (Q2_K shards; PR-referenced runtime)

- Source: `https://huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF` @ `cd42deba41ac0536e68b125dfc367197b0ec3038` (`refs/heads/main`)
- License: **UNKNOWN** (no `LICENSE*` file detected at pinned commit; see `./scripts/upstream_license_probe.sh`; treat as unknown until verified by a human)
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - Q2_K shards: 23 files under `Q2_K/` (total 100451521792 bytes, ~93.6 GiB)
  - `DeepSeek-V4-Flash-MXFP4_MOE.gguf` (150225324672 bytes, ~139.9 GiB)
- Runtime requirement:
  - Repo README instructs compiling llama.cpp PR `https://github.com/ggml-org/llama.cpp/pull/22378` (PR is closed and was explicitly “for reference”); in practice this maps to the pinned `nisparks/llama.cpp` `wip/deepseek-v4-support` branch.
- Single-Spark plausibility:
  - **Q2_K plausible but tight** on Spark0-class hardware (93.6 GiB leaves limited KV/cache headroom); note that it is sharded and may require an explicit merge step before use.
  - **MXFP4_MOE not plausible** on Spark0-class memory (139.9 GiB > ~119 GiB host RAM / ~119.7 GiB VRAM).

### nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF (native FP4/FP8)

- Source: `https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF` @ `0b34e0b629c706396002496e795e9f910f7bf69f` (`refs/heads/main`)
- License: “deepseek” link (model card points to DeepSeek-V4-Flash `LICENSE`)
- Artifact (not fetched here):
  - `DeepSeek-V4-Flash-FP4-FP8-native.gguf`
  - Size: ~146 GB
- Runtime requirement:
  - Requires DeepSeek-V4 loader plus native `F8_E4M3_B128` + `MXFP4` support; model card points to `nisparks/llama.cpp` branch `wip/deepseek-v4-support`.
- Single-Spark plausibility:
  - **Not plausible on Spark0-class hardware** (146 GB > ~119 GiB host RAM and > ~119.7 GiB VRAM).

### cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF (research artifact)

- Source: `https://huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF` @ `665c8e035e2602d12d28b84920808b158f337e09` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - Q2_K: `cyberneurova-DeepSeek-V4-Flash-abliterated-Q2_K.gguf` (98810926400 bytes, 92.0 GiB; model card also describes this as “98.8 GB”)
  - Q8_0: `cyberneurova-DeepSeek-V4-Flash-abliterated-Q8_0.gguf` (302251447616 bytes, 281.5 GiB; model card also describes this as “282 GB”)
- Single-Spark plausibility:
  - **Q2_K plausible but tight** on Spark0-class hardware (92.0 GiB / ~98.8 GB leaves limited KV/cache headroom); **Q8_0 not plausible** (too large).

### teamblobfish/DeepSeek-V4-Flash-GGUF (multi-quant sharded GGUFs)

- Source: `https://huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF` @ `ed189bf9706efc321f8db142cefae9e6f1da6e85` (`refs/heads/main`)
- License: MIT (model card)
- Runtime requirement (per upstream README):
  - Requires a DeepSeek-V4-capable llama.cpp fork; upstream recommends `cchuter/llama.cpp` branch `feat/v4-port`.
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - IQ2_XXS-XL (2 shards): total 78518818624 bytes (73.1 GiB)
  - IQ2_XS-XL (2 shards): total 87007827744 bytes (81.0 GiB)
  - Q2_K-XL (3 shards): total 107034192768 bytes (99.7 GiB)
- Single-Spark plausibility:
  - **IQ2_XXS-XL / IQ2_XS-XL plausible** on Spark0-class memory (leave more KV/cache headroom than ~90–100 GiB candidates).
  - **Q2_K-XL plausible but tight** on Spark0-class memory (99.7 GiB leaves limited KV/cache headroom).

## Related runtime forks (pinned)

- `https://github.com/antirez/llama.cpp-deepseek-v4-flash` @ `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f` (MIT)
- `https://github.com/nisparks/llama.cpp` `wip/deepseek-v4-support` @ `9d364087024da141510267e6b269ee495ca45176` (MIT)
- `https://github.com/cchuter/llama.cpp` `feat/v4-port` @ `19b63dc368dfef6db6783e5ba3143927b7ed1c96` (MIT)
- `https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` @ `9222e55c13c965ccb7e9104fda58796edd84a732` (MIT)
- `https://github.com/batiai/bati.cpp` @ `c7b64fe065164335b882e02a848fd4015b3c060a` (`refs/tags/v0.1.2`, MIT)

## Notes / non-goals

- Do not run upstream download scripts from this repo.
- Do not `git lfs pull` on Hugging Face repos cloned into `./upstreams`.
