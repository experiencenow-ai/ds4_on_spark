# Upstream: DeepSeek-V4-Flash quantized single-Spark candidates (GGUF)

This repo does **not** vendor model weights. The entries below are **references only** for (a) provenance + licensing and (b) a quick “could this plausibly fit on one Spark?” filter. Any GGUF download remains a human-approved fixture.

## Single-Spark memory baseline (Spark0)

Based on [`docs/spark0-hardware-baseline-2026-05-09.md`](spark0-hardware-baseline-2026-05-09.md), Spark0 has:

- Host RAM: ~119 GiB
- GPU VRAM (GB10): ~119.7 GiB

Treat this as the practical upper bound for “single Spark” artifacts; anything above ~100 GB leaves limited headroom for KV/cache + runtime overhead.

## Candidates (pinned)

### antirez/deepseek-v4-gguf (DS4-tuned IQ2XXS)

- Source: `https://huggingface.co/antirez/deepseek-v4-gguf` @ `ef3b960827870d69ed0b225c095a617c12d7e80d` (`refs/heads/main`)
- License: MIT (model card)
- Artifact (not fetched here):
  - `DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf`
  - Size: ~86.7 GB
- Provenance notes:
  - Model card states these quants are “specific for the DS4 inference engine” and links to `https://github.com/antirez/ds4`.
- Single-Spark plausibility:
  - **Plausible** on Spark0-class hardware as a first “one Spark produces tokens” target given the ~87 GB footprint and ~120 GiB host/GPU memory; still needs on-hardware validation and careful KV/cache sizing.

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
- Artifacts (not fetched here):
  - Q2_K: 98.8 GB (RAM floor stated: 128 GB)
  - Q8_0: ~282 GB (RAM floor stated: 320 GB)
- Single-Spark plausibility:
  - **Q2_K plausible but tight** on Spark0-class hardware (98.8 GB leaves limited KV/cache headroom); **Q8_0 not plausible** (too large).

## Related runtime forks (pinned)

- `https://github.com/antirez/llama.cpp-deepseek-v4-flash` @ `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f` (MIT)
- `https://github.com/nisparks/llama.cpp` `wip/deepseek-v4-support` @ `9d364087024da141510267e6b269ee495ca45176` (MIT)
- `https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` @ `9222e55c13c965ccb7e9104fda58796edd84a732` (MIT)

## Notes / non-goals

- Do not run upstream download scripts from this repo.
- Do not `git lfs pull` on Hugging Face repos cloned into `./upstreams`.
