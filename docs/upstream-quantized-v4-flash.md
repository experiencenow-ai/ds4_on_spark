# Upstream: DeepSeek-V4-Flash quantized single-Spark candidates (GGUF)

This repo does **not** vendor model weights. The entries below are **references only** for (a) provenance + licensing and (b) a quick “could this plausibly fit on one Spark?” filter. Any GGUF download remains a human-approved fixture.

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
  - **Plausible** as a first single-node/Spark target given the ~87 GB footprint and existing reports of “IQ2XXS on single GB10/Spark” in CUDA llama.cpp forks; still needs on-hardware validation and careful KV/cache sizing.

### nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF (native FP4/FP8)

- Source: `https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF` @ `0b34e0b629c706396002496e795e9f910f7bf69f` (`refs/heads/main`)
- License: “deepseek” link (model card points to DeepSeek-V4-Flash `LICENSE`)
- Artifact (not fetched here):
  - `DeepSeek-V4-Flash-FP4-FP8-native.gguf`
  - Size: ~146 GB
- Runtime requirement:
  - Requires DeepSeek-V4 loader plus native `F8_E4M3_B128` + `MXFP4` support; model card points to `nisparks/llama.cpp` branch `wip/deepseek-v4-support`.
- Single-Spark plausibility:
  - **Unclear / likely tight** for a single Spark-class node unless host RAM is comfortably above ~146 GB + KV/cache overhead; validate with real Spark memory limits before attempting.

### cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF (research artifact)

- Source: `https://huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF` @ `665c8e035e2602d12d28b84920808b158f337e09` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here):
  - Q2_K: 98.8 GB (RAM floor stated: 128 GB)
  - Q8_0: ~282 GB (RAM floor stated: 320 GB)
- Single-Spark plausibility:
  - **Q2_K plausible** on a high-RAM single node; **Q8_0 not plausible** for typical single-Spark constraints.

## Related runtime forks (pinned)

- `https://github.com/antirez/llama.cpp-deepseek-v4-flash` @ `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f` (MIT)
- `https://github.com/nisparks/llama.cpp` `wip/deepseek-v4-support` @ `9d364087024da141510267e6b269ee495ca45176` (MIT)
- `https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` @ `9222e55c13c965ccb7e9104fda58796edd84a732` (MIT)

## Notes / non-goals

- Do not run upstream download scripts from this repo.
- Do not `git lfs pull` on Hugging Face repos cloned into `./upstreams`.
