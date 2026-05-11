# Upstream: DeepSeek-V4-Flash quantized single-Spark candidates (GGUF)

This repo does **not** vendor model weights. The entries below are **references only** for (a) provenance + licensing and (b) a quick “could this plausibly fit on one Spark?” filter. Any GGUF download remains a human-approved fixture.

For a runtime+artifact pairing matrix (what runs where), see [`docs/upstream-single-spark-v4-flash.md`](upstream-single-spark-v4-flash.md).

## Discovery (HF search, no downloads)

To discover new community GGUF repos without cloning or downloading weights, search the Hugging Face model index:

```bash
./scripts/upstream_hf_search.sh "DeepSeek-V4-Flash GGUF" --sort downloads --limit 50
```

Then inspect a promising repo’s GGUF footprint and LFS sha256 via the per-repo API report:

```bash
./scripts/upstream_hf_api_report.sh <org>/<repo> --sum-gguf
./scripts/upstream_hf_api_report.sh <org>/<repo> --top-oids 50 | rg '\\.gguf$'
```

To quickly find the smallest GGUF files in a repo (useful for a “could this fit on one Spark?” first pass), use:

```bash
./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --limit 20
```

If the repo stores sharded GGUFs (e.g. `...-00001-of-00002.gguf`), prefer the grouped report so you can reason about total artifact size:

```bash
./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --group-shards --limit 20
```

To filter a *search query* down to “the smallest GGUF variant per repo that’s <= N GiB” (shards summed), use:

```bash
./scripts/upstream_hf_spark_gguf_candidates.sh "DeepSeek-V4-Flash GGUF" --limit 50 --sort downloads --max-gib 110
```

To avoid common false positives, you can require the model-card `base_model` field to reference the official checkpoint:

```bash
./scripts/upstream_hf_spark_gguf_candidates.sh "DeepSeek-V4-Flash GGUF" --limit 50 --sort downloads --max-gib 110 --require-base-model deepseek-ai/DeepSeek-V4-Flash
```

Sanity-check for false positives:

- Many search hits are *not* the 284B MoE DeepSeek-V4-Flash model (e.g., smaller distill/fine-tune repos that include “V4-Flash” in the name).
- Prefer candidates whose HF metadata indicates `base_model: deepseek-ai/DeepSeek-V4-Flash` (or equivalent) and whose GGUF sizes are in the expected ~60–110 GiB “single Spark plausible” range.
- Watch for repos that claim “DeepSeek-V4-Flash” but use clearly non-canonical parameter counts (e.g. “158B”); treat those as separate models and do not mix them into the 284B single-Spark candidate set unless provenance is verified.
- Known false positives (distill / unrelated base model):
  - `*/Qwen3.5-9B-DeepSeek-V4-Flash*` repos (often `base_model: unsloth/Qwen3.5-9B`), which are small unrelated models that happen to include “DeepSeek-V4-Flash” in the name.

Note: HF model cards can express the base model as either a single `base_model` string or a list. `./scripts/upstream_hf_api_report.sh <org>/<repo>` prints `base_model:` as a comma-separated string in both cases.

Reproduce (no downloads):

```bash
./scripts/upstream_hf_api_report.sh <org>/<repo> | rg -n '^(base_model|license|sha):'
./scripts/upstream_hf_api_report.sh <org>/<repo> --sum-gguf
```

## Single-Spark memory baseline (Spark0)

Based on [`docs/spark0-hardware-baseline-2026-05-09.md`](spark0-hardware-baseline-2026-05-09.md), Spark0 has:

- Host RAM: ~119 GiB
- GPU VRAM (GB10): ~119.7 GiB

Treat this as the practical upper bound for “single Spark” artifacts; anything above ~100 GB leaves limited headroom for KV/cache + runtime overhead.

## Candidates (pinned)

Quick scan for “single Spark produces tokens” candidates (Spark0 baseline ~119 GiB host RAM / ~119.7 GiB VRAM):

| Source | Artifact | Size (bytes) | Size (GiB) | LFS sha256 (content) | Single-Spark plausibility |
| --- | --- | ---: | ---: | --- | --- |
| `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` | `...IQ1_M.gguf` | 67505962560 | 62.9 | `a7c64ba7...3c58a22c` | Plausible (more headroom than IQ2 quants; requires V4-capable llama.cpp fork) |
| `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` | `...IQ2_XXS...(2 shards)` | 77907836672 | 72.6 | `0e4356c7...9d0ae99b` + `5dd29236...45da5c5e7` | Plausible (sharded; requires V4-capable llama.cpp fork) |
| `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` | `...IQ3_XXS.gguf` | 111834815936 | 104.2 | `e2e075f4...68dda5f2` | Plausible but tight (limited KV/cache headroom) |
| `antirez/deepseek-v4-gguf` | `...IQ2XXS...chat-v2.gguf` | 86720111200 | 80.8 | `31598c67...e86fd8c` | Plausible (headroom for KV/cache still required) |
| `Preyazz/DeepSeek-V4-Flash-GGUF` | `DeepSeek-V4-Flash-Q2_K.gguf` | 103283751520 | 96.2 | `3edea7ba...6528c993` | Plausible but tight (limited KV/cache headroom) |
| `cyberneurova/...-abliterated-GGUF` | `...-Q2_K.gguf` | 98810926400 | 92.0 | `1d494194...a9d7ec6b` | Plausible but tight (limited KV/cache headroom) |
| `lovedheart/DeepSeek-V4-Flash-GGUF` | `Q2_K (23 shards)` | 100451521792 | 93.6 | (see shard list below) | Plausible but tight (license UNKNOWN; sharded; requires V4-capable llama.cpp) |
| `teamblobfish/DeepSeek-V4-Flash-GGUF` | `IQ1_S-XL (2 shards)` | 61540800288 | 57.3 | `4f99d953...a3d13b` + `b15ce531...1495b5` | Plausible (sharded; more headroom than ~70–100 GiB candidates) |
| `teamblobfish/DeepSeek-V4-Flash-GGUF` | `IQ1_M (2 shards)` | 64508041632 | 60.1 | `c0d4aac8...f2856` + `812b1367...d2d81f` | Plausible (sharded; more headroom than ~70–100 GiB candidates) |
| `teamblobfish/DeepSeek-V4-Flash-GGUF` | `IQ1_M-XL (2 shards)` | 67907557152 | 63.2 | `b9e78422...6d43` + `857daa60...b3e3` | Plausible (sharded; still substantial KV/cache headroom) |
| `teamblobfish/DeepSeek-V4-Flash-GGUF` | `IQ2_XXS-XL (2 shards)` | 78518818624 | 73.1 | `a2472110...a04fdce` + `aedfb2c7...ea9bf92` | Plausible (sharded; upstream README indicates pointing llama.cpp at shard 00001 auto-loads the rest) |

## Not single-Spark plausible (still DeepSeek-V4-Flash)

The HF search results often include “native” conversions that are **correctly based on** `deepseek-ai/DeepSeek-V4-Flash`, but are too large for a single Spark0-class node. Track them as provenance references only.

| Source | Pinned commit | Artifact | Size (GiB) | LFS sha256 (content) | License | Notes |
| --- | --- | --- | ---: | --- | --- | --- |
| `asidaddy/Deepseek-V4-Flash-GGUF` | `2c3a2233ec6492024ee1c90aa6a06ec22173d909` | `DeepSeek-V4-Flash-native.gguf` | 145.42 | `e16f070a...738babcd` | MIT | Repo also contains large LFS `model-*.safetensors`; treat as metadata-only. |
| `Volko76/DeepSeek-V4-Flash-GGUF` | `5f45ca7217f7b4e46e230e7c8bce3d3ff705555a` | `DeepSeek-V4-Flash-Q2_K.gguf` | 142.47 | `b807d57e...27dc013` | MIT | Q2_K is still too large for Spark0-class memory headroom. |
| `setar007/DeepSeek-V4-Flash-Q8xQ5-GGUF` | `3f779b75664c2a50a8d5f8ed31d17ed1efe2fe52` | `DeepSeek-V4-Flash-Instruct-Q8xQ5.gguf (11 shards)` | 184.74 | `7cf4773f...2ed802eb` + ... (11 shards) | MIT | Too large for single Spark0-class memory; keep as provenance reference only. |
| `Preyazz/DeepSeek-V4-Flash-Q8_0-GGUF` | `066a35fd187293796317f61775b954bd1e5730dd` | `DeepSeek-V4-Flash-Q8_0.gguf` | 281.59 | `b34cbe6e...f1b3df03` | MIT | Q8_0 is far too large for single Spark0-class memory; keep as provenance reference only. |

## Reproducing the size numbers (no downloads)

The GGUF “sizes” above are taken from the Git LFS pointer metadata in a metadata-only clone (i.e. `GIT_LFS_SKIP_SMUDGE=1` / LFS filters disabled). This lets us record exact byte counts without fetching multi‑GB blobs.

Alternative (no clone): query the Hugging Face HTTP API for per-file sizes *and* LFS content sha256:

```bash
./scripts/upstream_hf_api_report.sh antirez/deepseek-v4-gguf --top-oids 50 | rg '\\.gguf$'
```

To reproduce:

```bash
./scripts/fetch_upstreams.sh deepseek_v4_gguf_preyazz
./scripts/upstream_hf_pointer_report.sh deepseek_v4_gguf_preyazz
```

Repeat for other HF GGUF repos (e.g. `deepseek_v4_gguf_antirez`, `deepseek_v4_gguf_batiai`, etc.).

### antirez/deepseek-v4-gguf (DS4-tuned IQ2XXS)

- Source: `https://huggingface.co/antirez/deepseek-v4-gguf` @ `b0c3326275d2207e25e42bc8ac0704952466b5bb` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - IQ2XXS: `DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf` (86720111200 bytes, 80.8 GiB)
    - LFS sha256: `31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c`
  - Q4KExperts (too large for single Spark): `DeepSeek-V4-Flash-Q4KExperts-F16HC-F16Compressor-F16Indexer-Q8Attn-Q8Shared-Q8Out-chat-v2.gguf` (164633502304 bytes, 153.3 GiB)
    - LFS sha256: `39e5de72ac544fdd5ffaf83ec28e36aaf3341b145235488e67d59400bbb3af55`
  - MTP sidecar: `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf` (3807602400 bytes, 3.5 GiB)
    - LFS sha256: `afd481ee689dce9037f70f39085fcdae5a5b096d521cdad43b19fa52bf8f4083`
- Provenance notes:
  - Model card states these quants are “specific for the DS4 inference engine” and links to `https://github.com/antirez/ds4`.
  - Single-GB10 report (2026-05-05): community run on `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` with `-hf antirez/deepseek-v4-gguf` (`https://forums.developer.nvidia.com/t/deepseek-v4-flash-iq2xxs-on-a-single-gb10/368970`).
- Single-Spark plausibility:
  - **Plausible** on Spark0-class hardware as a first “one Spark produces tokens” target given the 80.8 GiB (~86.7 GB) footprint and ~120 GiB host/GPU memory; still needs on-hardware validation and careful KV/cache sizing.

### ssweens/DeepSeek-V4-Flash-GGUF-YMMV (IQ1_M + IQ2_XXS + IQ3_XXS)

- Source: `https://huggingface.co/ssweens/DeepSeek-V4-Flash-GGUF-YMMV` @ `1387c955943485e273ba1b0f7564b4134cf0e3cb` (`refs/heads/main`)
- License: MIT (model card)
- Runtime requirement:
  - Requires `ssweens/llama.cpp-deepseek-v4` (`bb648b31e137a44b1ee72907e20ad8fb1f21d644`) per upstream README (tested CPU/CUDA/ROCm/Vulkan).
  - Upstream README also claims compatibility with `antirez/deepseek-v4-gguf`.
- Artifacts (not fetched here; sizes are from HF API / git-lfs pointer metadata):
  - IQ1_M: `deepseek-ai__DeepSeek-V4-Flash-IQ1_M.gguf` (67505962560 bytes, 62.9 GiB)
    - LFS sha256: `a7c64ba75a3b4ce42f0b51a69d05e7a37d2bbacc1f8e6017d6a0faca3c58a22c`
  - IQ2_XXS (2 shards): total 77907836672 bytes (72.6 GiB)
    - LFS sha256 shards:
      - `0e4356c7f2e3876bd5757bbaa4f2b7530370063939083048a320816a9d0ae99b` (`...IQ2_XXS-00001-of-00002...`, 49491736416 bytes)
      - `5dd29236696a4bec748c2d4e194dd4719473970873fc1f34422f92845da5c5e7` (`...IQ2_XXS-00002-of-00002...`, 28416100256 bytes)
  - IQ3_XXS (3 shards): total 111834816288 bytes (104.2 GiB)
    - LFS sha256 shards:
      - `8d1d6f79313ea2164f3b69177777b385e0729a62f30d9c6078712816a4492f3b` (`...IQ3_XXS-00001-of-00003...`, 49837684288 bytes)
      - `86d6c4e04754a08f78a10916c768504015e6f3e436f3164eb4247d821c5eed31` (`...IQ3_XXS-00002-of-00003...`, 49979559168 bytes)
      - `013b52f77bbf666f45fe396a2c02c244e437400003ddefa999ddeca53b4245d7` (`...IQ3_XXS-00003-of-00003...`, 12017572832 bytes)
  - BF16-ish (not single-Spark plausible): `deepseek-ai__DeepSeek-V4-Flash-bf16.gguf` (161799012416 bytes, 150.7 GiB)
    - LFS sha256: `0576a182aa80478733495f013fc7dd2ce71cbf9de8c4d59230a8c2724cad6614`
- Single-Spark plausibility:
  - **IQ1_M plausible** on Spark0-class memory (more headroom for KV/cache than ~70–90 GiB IQ2/Q2_K candidates).
  - **IQ2_XXS plausible** on Spark0-class memory; still needs KV/cache sizing validation; note it is sharded.
  - **IQ3_XXS plausible but tight** on Spark0-class memory (104.2 GiB leaves limited KV/cache headroom).
  - **BF16-ish not plausible** on Spark0-class memory (150.7 GiB > ~119 GiB host RAM / ~119.7 GiB VRAM).

### Preyazz/DeepSeek-V4-Flash-GGUF (community Q2_K/Q3_K_M/Q4_K_M)

- Source: `https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF` @ `6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - Q2_K: `DeepSeek-V4-Flash-Q2_K.gguf` (103283751520 bytes, ~96.2 GiB)
    - LFS sha256: `3edea7ba62c553109b4b1477b37d17862cf555b817f1725ffba709176528c993`
  - Q3_K_M: `DeepSeek-V4-Flash-Q3_K_M.gguf` (135535174240 bytes, ~126.2 GiB)
    - LFS sha256: `1b7b7ad4a97be78252016eea0166c169abaf1628cd25c2e6ee753b555020b8f1`
  - Q4_K_M: `DeepSeek-V4-Flash-Q4_K_M.gguf` (172037991008 bytes, ~160.2 GiB)
    - LFS sha256: `475a30468469e832225bfb6693e0243f6b731aec59b8b6e77b07a1b0bb9a402e`
- Runtime requirement:
  - Model card states it requires a DeepSeek-V4-capable llama.cpp (example reference: `nisparks/llama.cpp` branch `wip/deepseek-v4-support`).
- Single-Spark plausibility:
  - **Q2_K plausible but tight** on Spark0-class hardware (96.2 GiB leaves limited KV/cache headroom).
  - **Q3_K_M/Q4_K_M not plausible** on Spark0-class memory (artifact alone exceeds ~119 GiB host RAM / ~119.7 GiB VRAM).

### Preyazz/DeepSeek-V4-Flash-Q8_0-GGUF (oversized Q8_0)

- Source: `https://huggingface.co/Preyazz/DeepSeek-V4-Flash-Q8_0-GGUF` @ `066a35fd187293796317f61775b954bd1e5730dd` (`refs/heads/main`)
- License: MIT (model card)
- Artifacts (not fetched here; sizes are from HF API / git-lfs pointer metadata):
  - Q8_0: `DeepSeek-V4-Flash-Q8_0.gguf` (302355139168 bytes, 281.6 GiB)
    - LFS sha256: `b34cbe6eb2ce78a5c0b6824c3e554a9fe2ec85953fbfd6f832fabee4f1b3df03`
- Single-Spark plausibility:
  - **Not plausible** on Spark0-class hardware (artifact alone exceeds ~119 GiB host RAM / ~119.7 GiB VRAM).

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
    - LFS sha256 per shard (HF API; no downloads):
      - `f8d487bcf9dc66b21a6290dda1d25af66ae941fb96a3a0b305bb0302cb51c0b8` (`...00001-of-00023...`, 4422407072 bytes)
      - `0ade6d9b83d7e11ac46188de26a29814179afd0edadc04235a676de003bb5b26` (`...00002-of-00023...`, 4479736224 bytes)
      - `625db1ffafbde9dd9054c3dd144576b9c546bfdb7630036d6ca2bc08e4a1ed2a` (`...00003-of-00023...`, 4473531744 bytes)
      - `a15fd173e4bfae7447e9ed2f0baab3b66eb2ecb2fad77423c16cc2de619cb871` (`...00004-of-00023...`, 4473531744 bytes)
      - `538c5b1032755208f14bee6c126b61a883bd2df0814fefc2c2bb1f8ad23a0909` (`...00005-of-00023...`, 4473531744 bytes)
      - `f65fea31bc6fa7ecdea52bfd81ec23fe9c7858b16e4ccb6a7d6eaefd3305c8b6` (`...00006-of-00023...`, 4473531808 bytes)
      - `3e8733cbf918f05277d5affd26948d2bf21bb6f4a83aca7a0332eff59578e7fe` (`...00007-of-00023...`, 4473531808 bytes)
      - `462bb5e5bad75aa508c0759c1a2bfd1d8bdff332e0c1fa243e4c9c9e44e854e1` (`...00008-of-00023...`, 4473531808 bytes)
      - `1d0a370fe8b490d49ced959b837ad793b41d08fd532c0d401b68dbffacfae8df` (`...00009-of-00023...`, 4473531808 bytes)
      - `da7b98606864d66cadefc8535680113892094adff4eb0cb034e6a750eb5b924e` (`...00010-of-00023...`, 4473531808 bytes)
      - `c38cfb2d342052cedd1035fe3a6539f893d91526a5f8911c372ca115ff1357e4` (`...00011-of-00023...`, 4473531808 bytes)
      - `f9c2805b5575e368759932f79e454b4cb951535a3de2869a9abc4e47e9e28ca7` (`...00012-of-00023...`, 4473531808 bytes)
      - `91ddede652f0c472a9ec1ecda9c5806d8bd203aa85f7f28f046c98e2cd5adf2e` (`...00013-of-00023...`, 4473531808 bytes)
      - `b1d6c9d56f7a9c2af07f5925252c15d08adc92865bf866028b6cbe87dd43f969` (`...00014-of-00023...`, 4473531808 bytes)
      - `1d5e666b976692045e551c92144936236b11c5fa732c29f1865b84cc213bdf67` (`...00015-of-00023...`, 4473531808 bytes)
      - `f388288c601356f2c14cea308b9e5638bc88fe7a3d3734993e89bf90217202df` (`...00016-of-00023...`, 4473531808 bytes)
      - `3c43da498f6728f5e92e0bc809dd7f426860bafee15ab0140fb5d2e2f3a6a689` (`...00017-of-00023...`, 4473531808 bytes)
      - `6df5eb53151249872717a977c58100aa13612cdfe0ddaf3735c6beab5d6a5c3a` (`...00018-of-00023...`, 4473531808 bytes)
      - `00e8fefa1985b5d3fba4a5bf93b7e107708cb7c9415c7402ea0552cb7b3c209f` (`...00019-of-00023...`, 4473531808 bytes)
      - `c5ec6959ae3a9e33c6d04ccc189071b1a7ecc9de97c09382f1226932c75fb31c` (`...00020-of-00023...`, 4473531808 bytes)
      - `4cba5301b365d505be6bd64c4eb08de307126ee4b788550b1b7912a9d7b96c11` (`...00021-of-00023...`, 4473531808 bytes)
      - `bd3a7200d9423a595e723ff09f625d143afdce7d4ddb77e702b9425f9ad74272` (`...00022-of-00023...`, 4104744384 bytes)
      - `fc62571715dea301cf52e54bd1e5fc39dc267f44bfadcf7eb0cfb61e41bf046f` (`...00023-of-00023...`, 2447529952 bytes)
  - `DeepSeek-V4-Flash-MXFP4_MOE.gguf` (150225324672 bytes, ~139.9 GiB)
    - LFS sha256: `66991d4296a0608479d185ff6afdf0f9316facf1e38e9601607fb98c4a3cd855`
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
    - LFS sha256: `1d494194a4acf1218b52da4ecba3f3c7677d3a91353540a27b60dea1a9d7ec6b`
  - Q8_0: `cyberneurova-DeepSeek-V4-Flash-abliterated-Q8_0.gguf` (302251447616 bytes, 281.5 GiB; model card also describes this as “282 GB”)
    - LFS sha256: `ffff4e8e526a490f4e68dd649f32f6bc1e25d80d2f5df343996b5a956f9490cc`
- Single-Spark plausibility:
  - **Q2_K plausible but tight** on Spark0-class hardware (92.0 GiB / ~98.8 GB leaves limited KV/cache headroom); **Q8_0 not plausible** (too large).

### teamblobfish/DeepSeek-V4-Flash-GGUF (multi-quant sharded GGUFs)

- Source: `https://huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF` @ `3efdad27c080100655fe90b4b9b39224d0e300b4` (`refs/heads/main`)
- License: MIT (model card)
- Runtime requirement (per upstream README):
  - Requires a DeepSeek-V4-capable llama.cpp fork; upstream recommends `cchuter/llama.cpp` branch `feat/v4-port`.
- Artifacts (not fetched here; sizes are from git-lfs pointer metadata):
  - IQ1_S-XL (2 shards): total 61540800288 bytes (57.3 GiB)
    - LFS sha256 shards:
      - `4f99d953761b3a0478593fb2bbd1bf0c9de3e9eb3bd061ff6b8bde3db5a3d13b` (`...00001-of-00002...`, 49952653312 bytes)
      - `b15ce53183f61b8f29a9ccfd5b132a2577b3db82191cac49ebf3ca7e541495b5` (`...00002-of-00002...`, 11588146976 bytes)
  - IQ1_M (2 shards): total 64508041632 bytes (60.1 GiB)
    - LFS sha256 shards:
      - `c0d4aac8f92764fa896df593761e2255b37b107dd3f54b43e0ec8f9730ef2856` (`...00001-of-00002...`, 49882720352 bytes)
      - `812b13677c9466068711d1fe77aac46ca0012159697542e170e8cd7ba8d2d81f` (`...00002-of-00002...`, 14625321280 bytes)
  - IQ1_M-XL (2 shards): total 67907557152 bytes (63.2 GiB)
    - LFS sha256 shards:
      - `b9e784229c9ef5fc6cee790565267d7f25accdf3e2e99724eda734ec82af6d43` (`...00001-of-00002...`, 49946099200 bytes)
      - `857daa60b6e6e9cca1278c7e6e413cc298fdcd528ce4705730a18d41eeb6b3e3` (`...00002-of-00002...`, 17961457952 bytes)
  - IQ2_XXS-XL (2 shards): total 78518818624 bytes (73.1 GiB)
    - LFS sha256 shards:
      - `a2472110107d2ede08518340412482afffd09ce0101b187d3b8c6b1f4a04fdce` (`...00001-of-00002...`, 49859753888 bytes)
      - `aedfb2c7c1973b935df28fb1d6e2a8aeb894f5558b3e20f9c78999726ea9bf92` (`...00002-of-00002...`, 28659064736 bytes)
  - IQ2_XS-XL (2 shards): total 87007827744 bytes (81.0 GiB)
    - LFS sha256 shards:
      - `80dc7801419734bd255374f8ccb8419ec8622e42bcd8ccf5e6be3522261552ff` (`...00001-of-00002...`, 49732546624 bytes)
      - `5eed6f63c7aa5b66985254dee52a152ee2689ca905a1b2ceaa47cacdbec7d84d` (`...00002-of-00002...`, 37275281120 bytes)
  - Q2_K-XL (3 shards): total 107034192768 bytes (99.7 GiB)
- Single-Spark plausibility:
  - **IQ1_S-XL / IQ1_M / IQ1_M-XL / IQ2_XXS-XL / IQ2_XS-XL plausible** on Spark0-class memory (IQ1 variants leave the most KV/cache headroom).
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
