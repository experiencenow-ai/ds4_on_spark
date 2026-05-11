# Upstream Manifest

Pinned upstream references for `experiencenow-ai/ds4_on_spark`.

- Pinned-at: 2026-05-11 (UTC)
- Policy: do **not** vendor large third-party trees or model weights; fetch on-demand and pin exact commits.

## Canonical Upstreams (Pinned)

| Name | Upstream | Ref | Commit | License | Notes |
| --- | --- | --- | --- | --- | --- |
| ds4 | `antirez/ds4` | `refs/heads/main` | `e88a51fdac110ca5c0e0da06f1a27d4c0313b563` | MIT | DeepSeek-V4-Flash-specific native engine (Metal-first); semantics + KV-cache design reference; do not run upstream model-download scripts. |
| DeepGEMM | `deepseek-ai/DeepGEMM` | `refs/tags/v2.1.1.post3` | `c9f8b34dcdacc20aa746b786f983492c51072870` | MIT | CUDA GEMM kernels; upstream support is SM90/SM100 only (Spark SM121 not covered yet); pinned to a release tag (vs `main`). |
| FlashMLA | `deepseek-ai/FlashMLA` | `refs/heads/main` | `9241ae3ef9bac614dd25e45e507e089f888280e0` | MIT | Efficient Multi-head Latent Attention kernels; upstream support is SM90/SM100 only (Spark SM121 not covered yet); treat as kernel-design reference for V4-Flash-style MLA. |
| DeepSeek-V3 (code) | `deepseek-ai/DeepSeek-V3` | `refs/tags/v1.0.0` | `f6e34dd26772dd4a216be94a8899276c5dca9e43` | MIT (code) | Repo has distinct code vs model/weights licensing. |
| DeepSeek-V4-Flash (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/heads/main` | `6976c7ff1b30a1b2cb7805021b8ba4684041f136` | MIT | HF repo is “official code/configs” source (no dedicated `deepseek-ai/*` GitHub V4 repo found as of 2026-05-10); fetch with `GIT_LFS_SKIP_SMUDGE=1` to avoid weights; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| DeepSeek-V4-Flash-Base (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base` | `refs/heads/main` | `8855555deef230a27a21a8d6f294b7b7497759b6` | MIT | Optional checkpoint; fetch metadata-only (no weights) via `GIT_LFS_SKIP_SMUDGE=1`; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| DeepSeek-V4-Flash-FP8 (HF) | `huggingface.co/sgl-project/DeepSeek-V4-Flash-FP8` | `refs/heads/main` | `ae01d80c06cdfe30581edfd0e1c5449dc7ed7f17` | MIT | FP8 checkpoint mirror used in SGLang examples; metadata-only fetch only (LFS disabled); do not download weights without human approval. |
| vLLM | `vllm-project/vllm` | `refs/tags/v0.20.2` | `bc150f50299199599673614f80d12a196f377655` | Apache-2.0 | Inference runtime reference; DeepSeek-V4 support called out in v0.20.0 release notes (#40860). |
| Transformers | `huggingface/transformers` | `refs/tags/v5.8.0` | `049d2bf1220747b6d39e2a978b9f5fe0defa1dca` | Apache-2.0 | Reference for HF config/tokenization + model wrappers; v5.8.0 release adds DeepSeek-V4 integration (#45643). |
| DFlash (code) | `z-lab/dflash` | `refs/heads/main` | `94e4abc5e0c31b67bc1a9d30f1cc34ece28a8756` | MIT | DFlash block diffusion speculative decoding reference; model cards pin vLLM/SGLang PR refs; see `docs/upstream-qwen-dflash.md`. |
| GPT-OSS-20B (HF) | `huggingface.co/openai/gpt-oss-20b` | `refs/heads/main` | `6cee5e81ee83917806bbde320786a8fb61efebee` | Apache-2.0 | Open target with official Z Lab DFlash drafter (25.63 GiB safetensors); HF repo also includes large LFS blobs (e.g. `metal/model.bin`); do not download without human approval; see `docs/upstream-dflash.md`. |
| GPT-OSS-20B-DFlash (HF) | `huggingface.co/z-lab/gpt-oss-20b-DFlash` | `refs/heads/main` | `d53f6551543204c859e8bbaaddbd15d11b447af9` | MIT | Paired DFlash draft checkpoint (1.46 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| GPT-OSS-120B (HF) | `huggingface.co/openai/gpt-oss-120b` | `refs/heads/main` | `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` | Apache-2.0 | Large target (121.54 GiB safetensors; likely not single-Spark plausible); keep as provenance reference only; do not download without human approval; see `docs/upstream-dflash.md`. |
| GPT-OSS-120B-DFlash (HF) | `huggingface.co/z-lab/gpt-oss-120b-DFlash` | `refs/heads/main` | `1278df34f0a7bd2c8588a27f49048aaa05c7db00` | MIT | Paired DFlash draft checkpoint (1.46 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Qwen3-Coder-30B-A3B-Instruct-FP8 (HF) | `huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | `refs/heads/main` | `dcaee4d4dfc5ee71ad501f01f530e5652438fde0` | Apache-2.0 | Qwen FP8 comparison target (29.03 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3-Coder-30B-A3B-DFlash (HF) | `huggingface.co/z-lab/Qwen3-Coder-30B-A3B-DFlash` | `refs/heads/main` | `98ca0e3e2e6a372f2789d3a5e146566194084317` | MIT | Paired DFlash draft checkpoint (0.88 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.6-35B-A3B-FP8 (HF) | `huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8` | `refs/heads/main` | `95a723d08a9490559dae23d0cff1d9466213d989` | Apache-2.0 | FP8 MoE comparison target (34.89 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-35B-A3B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.6-35B-A3B-DFlash` | `refs/heads/main` | `42d3b34d588423cdae7ba8f53a8cf7789346a719` | MIT | Paired DFlash draft checkpoint (0.88 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.6-27B (HF) | `huggingface.co/Qwen/Qwen3.6-27B` | `refs/heads/main` | `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` | Apache-2.0 | Dense-ish comparison target (51.75 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-27B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.6-27B-DFlash` | `refs/heads/main` | `0919688658996800f86b895034249700e9481106` | MIT | Paired DFlash draft checkpoint (3.22 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.5-27B (HF) | `huggingface.co/Qwen/Qwen3.5-27B` | `refs/heads/main` | `fc05daec18b0a78c049392ed2e771dde82bdf654` | Apache-2.0 | Dense-ish 27B comparison target (51.75 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-27B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.5-27B-DFlash` | `refs/heads/main` | `b0400439c04be32c24e04d9dce3821b582c1a68a` | MIT | Paired DFlash draft checkpoint (3.22 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3-Coder-Next-FP8 (HF) | `huggingface.co/Qwen/Qwen3-Coder-Next-FP8` | `refs/heads/main` | `da6e2ed27304dd39abadd9c82ef50e8de67bdd4c` | Apache-2.0 | Larger comparison target (74.86 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3-Coder-Next-DFlash (HF) | `huggingface.co/z-lab/Qwen3-Coder-Next-DFlash` | `refs/heads/main` | `6d741db11b89d7ea80a423b109f0424817ce8f1b` | MIT | Paired DFlash draft checkpoint (0.88 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3-Coder-480B-A35B-Instruct-FP8 (HF) | `huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8` | `refs/heads/main` | `003f183a92fbe5b9a8325aaa8b2ae797c91dd90f` | Apache-2.0 | Reference-only target (449.04 GiB safetensors, not single-Spark plausible); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Ling-2.6-flash (HF) | `huggingface.co/inclusionAI/Ling-2.6-flash` | `refs/heads/main` | `9c861253ede654353d20bf1708182c81aab5f069` | MIT | Ling 2.6 Flash comparison target (200.23 GiB safetensors, not single-Spark plausible); do not download weights without human approval; see `docs/upstream-ling-2.6-flash.md`. |
| Ling-2.6-flash-fp8 (HF) | `huggingface.co/inclusionAI/Ling-2.6-flash-fp8` | `refs/heads/main` | `8bc416b60fe28be33303d57bb77dd826445a1eb1` | MIT | Ling 2.6 Flash FP8 target (101.48 GiB safetensors; single-Spark plausible but tight); do not download weights without human approval; see `docs/upstream-ling-2.6-flash.md`. |
| Ling-2.6-flash-int4 (HF) | `huggingface.co/inclusionAI/Ling-2.6-flash-int4` | `refs/heads/main` | `1bff63aa1f869e89499d52363790a119fd282edf` | MIT | Ling 2.6 Flash INT4 target (60.38 GiB safetensors; single-Spark plausible); do not download weights without human approval; see `docs/upstream-ling-2.6-flash.md`. |
| Gemma-4-26B-A4B-it (HF) | `huggingface.co/google/gemma-4-26B-A4B-it` | `refs/heads/main` | `462a98a12e28e2cbcfccaf78fe41e3e50235e6ae` | Apache-2.0 | Gemma 4 IT comparison target (48.07 GiB safetensors); do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Gemma-4-26B-A4B-it-DFlash (HF) | `huggingface.co/z-lab/gemma-4-26B-A4B-it-DFlash` | `refs/heads/main` | `77d4202772dfe50b2396ec7bac9cfffc7b9e7057` | Apache-2.0 | Paired DFlash draft checkpoint (0.80 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Gemma-4-31B-it (HF) | `huggingface.co/google/gemma-4-31B-it` | `refs/heads/main` | `ba74f5b6c647c0911554e50278d6f6f4477f9010` | Apache-2.0 | Gemma 4 IT comparison target (58.25 GiB safetensors); do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Gemma-4-31B-it-DFlash (HF) | `huggingface.co/z-lab/gemma-4-31B-it-DFlash` | `refs/heads/main` | `eabd648301ce28583cc14757912e5e0f84e152e1` | Apache-2.0 | Paired DFlash draft checkpoint (2.86 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| SGLang | `sgl-project/sglang` | `refs/tags/v0.5.11` | `612785ffdcaf35552f1ed433a981d596ca9fe900` | Apache-2.0 | Serving runtime reference with explicit DeepSeek-V4 docs/cookbook; pinned to a release tag for reproducibility. |
| llama.cpp | `ggml-org/llama.cpp` | `refs/tags/b9097` | `0b047287fe2f86875c4c0589cb42b3635d7389d8` | MIT | Spark-relevant baseline for CPU/GPU inference + ggml tooling (pinned to a release tag). |
| llama.cpp (DeepSeek V4 Flash fork) | `antirez/llama.cpp-deepseek-v4-flash` | `refs/heads/main` | `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f` | MIT | Flash-specific fork widely referenced by community GGUFs; not in upstream `ggml-org/llama.cpp` yet. |
| llama.cpp (DeepSeek V4 support WIP) | `nisparks/llama.cpp` | `refs/heads/wip/deepseek-v4-support` | `9d364087024da141510267e6b269ee495ca45176` | MIT | WIP branch adding `F8_E4M3_B128` + `MXFP4` types + V4 loader/converter; required by some “native FP4/FP8” GGUF artifacts. |
| llama.cpp (DeepSeek V4 port fork) | `cchuter/llama.cpp` | `refs/heads/feat/v4-port` | `19b63dc368dfef6db6783e5ba3143927b7ed1c96` | MIT | V4-capable fork referenced by `teamblobfish/DeepSeek-V4-Flash-GGUF`; includes V4 loader + kernels not merged upstream. |
| llama.cpp (ssweens DeepSeek V4 fork) | `ssweens/llama.cpp-deepseek-v4` | `refs/heads/main` | `bb648b31e137a44b1ee72907e20ad8fb1f21d644` | MIT | CUDA/ROCm/Vulkan fork used by `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` (IQ1_M + IQ2_XXS); validate Spark compatibility (CC/SM121 + memory/KV behavior). |
| llama.cpp (CUDA Spark fork) | `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` | `refs/heads/master` | `9222e55c13c965ccb7e9104fda58796edd84a732` | MIT | CUDA fork reported running on a single DGX Spark/GB10; provenance (report, 2026-05-05): `https://forums.developer.nvidia.com/t/deepseek-v4-flash-iq2xxs-on-a-single-gb10/368970`; validate perf + memory headroom on target Spark. |
| DeepSeek-V4-Flash (quantized safetensors, bleysg) | `huggingface.co/bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target` | `refs/heads/main` | `4ce0d4ac6bd35b63b68dfc813d0ae07497c4bf49` | MIT | Community quantized safetensors snapshot (~82.34 GiB total); base_model is `deepseek-ai/DeepSeek-V4-Flash`; do not download without human approval; runtime support is not yet pinned. |
| DeepSeek-V4-Flash GGUF (antirez) | `huggingface.co/antirez/deepseek-v4-gguf` | `refs/heads/main` | `9cb905d99321dbefb0e7c63fdb9bbd4d8aa7126a` | MIT | Single-file IQ2XXS GGUF (~80.8 GiB) tuned for `ds4` and used as single-Spark candidate; repo also publishes an optional MTP sidecar GGUF (~3.5 GiB); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (ssweens) | `huggingface.co/ssweens/DeepSeek-V4-Flash-GGUF-YMMV` | `refs/heads/main` | `1387c955943485e273ba1b0f7564b4134cf0e3cb` | MIT | GGUF pack includes `IQ1_M` (~62.9 GiB) + `IQ2_XXS` shards (~72.6 GiB) + `IQ3_XXS` shards (~104.2 GiB); also includes a BF16 GGUF (~150.7 GiB, not single-Spark plausible); requires V4-capable llama.cpp fork; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Preyazz) | `huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d` | MIT | Single-file Q2_K (~96 GiB) candidate; requires V4-capable llama.cpp fork (see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Preyazz Q8_0) | `huggingface.co/Preyazz/DeepSeek-V4-Flash-Q8_0-GGUF` | `refs/heads/main` | `066a35fd187293796317f61775b954bd1e5730dd` | MIT | Single-file Q8_0 GGUF (~281.6 GiB; not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (BatiAI) | `huggingface.co/batiai/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `70c9597f26a5b4747272477fff37986c4ce484ef` | MIT | Sharded GGUFs requiring `batiai/bati.cpp`; smallest quant listed is ~127 GB (not single-Spark plausible); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (lovedheart) | `huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `cd42deba41ac0536e68b125dfc367197b0ec3038` | UNKNOWN | No `LICENSE*` file detected at pinned commit (see `./scripts/upstream_license_probe.sh`); sharded Q2_K total ~93.6 GiB (single-Spark plausible but tight); README references llama.cpp PR `#22378` (closed; see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (native FP4/FP8) | `huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF` | `refs/heads/main` | `0b34e0b629c706396002496e795e9f910f7bf69f` | DeepSeek (link) | Single-file GGUF (~146 GB) 1:1 FP4/FP8 conversion; requires V4 loader + FP8/MXFP4 kernel support; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (abliterated) | `huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF` | `refs/heads/main` | `665c8e035e2602d12d28b84920808b158f337e09` | MIT | Experimental safety-research artifact; includes Q2_K (~99 GB) and Q8_0 (~302 GB) variants; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (teamblobfish) | `huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `49308dcbd636968324ba89c635bea99ebfd94398` | MIT | Sharded GGUF repo with multiple quant variants (IQ*/Q*); metadata-only fetch only; do not download weights without human approval. |
| DeepSeek-V4-Flash GGUF (asidaddy) | `huggingface.co/asidaddy/Deepseek-V4-Flash-GGUF` | `refs/heads/main` | `2c3a2233ec6492024ee1c90aa6a06ec22173d909` | MIT | Native conversion artifacts are ~145.4 GiB+ (not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Volko76) | `huggingface.co/Volko76/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `5f45ca7217f7b4e46e230e7c8bce3d3ff705555a` | MIT | Q2_K artifact is ~142.5 GiB (not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (setar007) | `huggingface.co/setar007/DeepSeek-V4-Flash-Q8xQ5-GGUF` | `refs/heads/main` | `3f779b75664c2a50a8d5f8ed31d17ed1efe2fe52` | MIT | Q8xQ5 sharded artifact totals ~184.7 GiB (not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| bati.cpp | `batiai/bati.cpp` | `refs/tags/v0.1.2` | `c7b64fe065164335b882e02a848fd4015b3c060a` | MIT | Early-access runtime referenced by `batiai/DeepSeek-V4-Flash-GGUF`; CUDA build path exists but is not yet validated on Spark. |
| Spark bring-up (pruned checkpoint) | `Mockingjay1316/deepseek-v4-flash-spark` | `refs/heads/master` | `08045f89d9716d3249ce834be1a1b1d91fd40859` | MIT | Single-Spark reference: prunes learned-router experts (example 256→128) and uses a streaming loader to avoid unified-memory OOM. |
| Spark bring-up (native checkpoint runtime) | `bigs/deepseek-v4-flash-dgx-spark` | `refs/heads/main` | `4410e814a76a1a9d662576e2a35fa4a8965d2edc` | UNKNOWN | No `LICENSE*` file detected at pinned commit (see `./scripts/upstream_license_probe.sh`); research runtime + OpenAI-compatible server for native FP8/FP4 checkpoint layout on Spark; includes inspection + manifest tooling; do not run without human-approved fixtures/hardware time. |
| Spark bring-up (GB10 C++ runtime, MXFP4) | `devid791/dsv4-flash-gb10-runtime` | `refs/tags/v0.1.0` | `244cb11d3ee3adfd96bd0f95d6a91649af7af45d` | Apache-2.0 | Proof-of-life Spark/GB10 runtime that loads the official BF16 HF snapshot and quantizes routed experts to MXFP4 on the fly; requires a human-approved HF snapshot download (large disk footprint). Provenance (2026-05-05): `https://forums.developer.nvidia.com/t/deepseek-v4-flash-mxfp4-proof-of-life-on-a-single-gb10-gx10/369131`. |
| Blackwell/SGLang arch patch (reference) | `0xSero/deepseek-v4-flash-sm120` | `refs/heads/main` | `c2eac5a9b2b457881d69b1164d909e8beab9286e` | Apache-2.0 | SM120 patch for SGLang FlashMLA sparse-decode kernels; may inform SM121/Spark troubleshooting. |

## Fetching

Use [`scripts/fetch_upstreams.sh`](../scripts/fetch_upstreams.sh) to clone pinned refs into a local `upstreams/` directory (ignored by git). The script verifies that the checked-out commit matches the pinned `Commit` in this manifest. For Hugging Face repos, the script sets `GIT_LFS_SKIP_SMUDGE=1` so large weight blobs are not downloaded.

## Refreshing Pins

To see the current HEAD commits upstream (without cloning), run:

```bash
./scripts/upstream_ls_remote.sh
```

To print the current resolution of the **pinned** refs (without cloning), run:

```bash
./scripts/upstream_ls_remote.sh --pinned
```

To print both reports (HEAD + pinned), run:

```bash
./scripts/upstream_ls_remote.sh --all
```

To verify that the **pinned** refs/commits in this manifest still resolve upstream, run:

```bash
./scripts/upstream_verify_pins.sh
```

To probe for common `LICENSE*` files at pinned commits (without cloning), run:

```bash
./scripts/upstream_license_probe.sh
```

To discover new community Hugging Face GGUF candidates (metadata only; no downloads), run:

```bash
./scripts/upstream_hf_search.sh "DeepSeek-V4-Flash GGUF" --sort downloads --limit 50
```

To inspect the smallest GGUF files in a repo (metadata only; no downloads), run:

```bash
./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --limit 20
```

For sharded GGUF repos, use the grouped report to sum shard sizes:

```bash
./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --group-shards --limit 20
```

## Per-Upstream Notes

- [`docs/upstream-ds4.md`](upstream-ds4.md)
- [`docs/upstream-deepgemm.md`](upstream-deepgemm.md)
- [`docs/upstream-flashmla.md`](upstream-flashmla.md)
- [`docs/upstream-deepseek-v3.md`](upstream-deepseek-v3.md)
- [`docs/upstream-deepseek-v4-flash.md`](upstream-deepseek-v4-flash.md)
- [`docs/upstream-vllm-transformers.md`](upstream-vllm-transformers.md)
- [`docs/upstream-sglang.md`](upstream-sglang.md)
- [`docs/upstream-llama-cpp.md`](upstream-llama-cpp.md)
- [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md)
- [`docs/upstream-quantized-v4-flash-safetensors.md`](upstream-quantized-v4-flash-safetensors.md)
- [`docs/upstream-single-spark-v4-flash.md`](upstream-single-spark-v4-flash.md)
- [`docs/upstream-spark-v4-bringup.md`](upstream-spark-v4-bringup.md)
- [`docs/upstream-qwen-dflash.md`](upstream-qwen-dflash.md)
- [`docs/upstream-dflash.md`](upstream-dflash.md)
- [`docs/upstream-ling-2.6-flash.md`](upstream-ling-2.6-flash.md)
- [`docs/model-quality-speed.md`](model-quality-speed.md)
