# Upstream Manifest

Pinned upstream references for `experiencenow-ai/ds4_on_spark`.

- Pinned-at: 2026-05-09 (UTC)
- Policy: do **not** vendor large third-party trees or model weights; fetch on-demand and pin exact commits.

## Canonical Upstreams (Pinned)

| Name | Upstream | Ref | Commit | License | Notes |
| --- | --- | --- | --- | --- | --- |
| ds4 | `antirez/ds4` | `refs/heads/main` | `8e7575be0ef44bd97c5ebaccf49ef85e05048b7b` | MIT | DeepSeek-V4-Flash-specific native engine (Metal-first); semantics + KV-cache design reference; do not run upstream model-download scripts. |
| DeepGEMM | `deepseek-ai/DeepGEMM` | `refs/tags/v2.1.1.post3` | `c9f8b34dcdacc20aa746b786f983492c51072870` | MIT | CUDA GEMM kernels; upstream support is SM90/SM100 only (Spark SM121 not covered yet); pinned to a release tag (vs `main`). |
| FlashMLA | `deepseek-ai/FlashMLA` | `refs/heads/main` | `9241ae3ef9bac614dd25e45e507e089f888280e0` | MIT | Efficient Multi-head Latent Attention kernels; upstream support is SM90/SM100 only (Spark SM121 not covered yet); treat as kernel-design reference for V4-Flash-style MLA. |
| DeepSeek-V3 (code) | `deepseek-ai/DeepSeek-V3` | `refs/tags/v1.0.0` | `f6e34dd26772dd4a216be94a8899276c5dca9e43` | MIT (code) | Repo has distinct code vs model/weights licensing. |
| DeepSeek-V4-Flash (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/heads/main` | `6976c7ff1b30a1b2cb7805021b8ba4684041f136` | MIT | HF repo is “official code/configs” source; fetch with `GIT_LFS_SKIP_SMUDGE=1` to avoid weights; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| DeepSeek-V4-Flash-Base (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base` | `refs/heads/main` | `8855555deef230a27a21a8d6f294b7b7497759b6` | MIT | Optional checkpoint; fetch metadata-only (no weights) via `GIT_LFS_SKIP_SMUDGE=1`; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| vLLM | `vllm-project/vllm` | `refs/tags/v0.20.2` | `bc150f50299199599673614f80d12a196f377655` | Apache-2.0 | Inference runtime reference; includes DeepSeek-V4 model support docs. |
| Transformers | `huggingface/transformers` | `refs/tags/v5.8.0` | `049d2bf1220747b6d39e2a978b9f5fe0defa1dca` | Apache-2.0 | Reference for HF config/tokenization + model wrappers. |
| SGLang | `sgl-project/sglang` | `refs/heads/main` | `c95454b34176fbc0da5ad031d646e71340d8bb50` | Apache-2.0 | Serving runtime reference with explicit DeepSeek-V4 docs/tests (newer than latest release tag); track alongside vLLM for V4-Flash bring-up context. |
| llama.cpp | `ggml-org/llama.cpp` | `refs/tags/b9085` | `046e2844370208007c116fab448ed4033d77653f` | MIT | Spark-relevant baseline for CPU/GPU inference + ggml tooling (pinned to a release tag). |
| llama.cpp (DeepSeek V4 Flash fork) | `antirez/llama.cpp-deepseek-v4-flash` | `refs/heads/main` | `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f` | MIT | Flash-specific fork widely referenced by community GGUFs; not in upstream `ggml-org/llama.cpp` yet. |
| llama.cpp (DeepSeek V4 support WIP) | `nisparks/llama.cpp` | `refs/heads/wip/deepseek-v4-support` | `9d364087024da141510267e6b269ee495ca45176` | MIT | WIP branch adding `F8_E4M3_B128` + `MXFP4` types + V4 loader/converter; required by some “native FP4/FP8” GGUF artifacts. |
| llama.cpp (DeepSeek V4 port fork) | `cchuter/llama.cpp` | `refs/heads/feat/v4-port` | `19b63dc368dfef6db6783e5ba3143927b7ed1c96` | MIT | V4-capable fork referenced by `teamblobfish/DeepSeek-V4-Flash-GGUF`; includes V4 loader + kernels not merged upstream. |
| llama.cpp (ssweens DeepSeek V4 fork) | `ssweens/llama.cpp-deepseek-v4` | `refs/heads/main` | `443fbfc1eff9ad0e89490bbf5697bfb15c1281e8` | MIT | CUDA/ROCm/Vulkan fork used by `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` (IQ1_M + IQ2_XXS); validate Spark compatibility (CC/SM121 + memory/KV behavior). |
| llama.cpp (CUDA Spark fork) | `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` | `refs/heads/master` | `9222e55c13c965ccb7e9104fda58796edd84a732` | MIT | CUDA fork reported running on a single DGX Spark/GB10; provenance (report, 2026-05-05): `https://forums.developer.nvidia.com/t/deepseek-v4-flash-iq2xxs-on-a-single-gb10/368970`; validate perf + memory headroom on target Spark. |
| DeepSeek-V4-Flash GGUF (antirez) | `huggingface.co/antirez/deepseek-v4-gguf` | `refs/heads/main` | `ef3b960827870d69ed0b225c095a617c12d7e80d` | MIT | Single-file GGUF (~87 GB) tuned for `ds4` and used as single-Spark candidate; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (ssweens) | `huggingface.co/ssweens/DeepSeek-V4-Flash-GGUF-YMMV` | `refs/heads/main` | `cd14d4663786e5fa368e560324b10e92110f39c2` | MIT | GGUF pack includes `IQ1_M` (~62.9 GiB) + `IQ2_XXS` shards (~72.6 GiB); requires V4-capable llama.cpp fork; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Preyazz) | `huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d` | MIT | Single-file Q2_K (~96 GiB) candidate; requires V4-capable llama.cpp fork (see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (BatiAI) | `huggingface.co/batiai/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `70c9597f26a5b4747272477fff37986c4ce484ef` | MIT | Sharded GGUFs requiring `batiai/bati.cpp`; smallest quant listed is ~127 GB (not single-Spark plausible); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (lovedheart) | `huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `cd42deba41ac0536e68b125dfc367197b0ec3038` | UNKNOWN | No `LICENSE*` file detected at pinned commit (see `./scripts/upstream_license_probe.sh`); sharded Q2_K total ~93.6 GiB (single-Spark plausible but tight); README references llama.cpp PR `#22378` (closed; see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (native FP4/FP8) | `huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF` | `refs/heads/main` | `0b34e0b629c706396002496e795e9f910f7bf69f` | DeepSeek (link) | Single-file GGUF (~146 GB) 1:1 FP4/FP8 conversion; requires V4 loader + FP8/MXFP4 kernel support; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (abliterated) | `huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF` | `refs/heads/main` | `665c8e035e2602d12d28b84920808b158f337e09` | MIT | Experimental safety-research artifact; includes Q2_K (~99 GB) and Q8_0 (~302 GB) variants; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (teamblobfish) | `huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `ed189bf9706efc321f8db142cefae9e6f1da6e85` | MIT | Sharded GGUF repo with multiple quant variants (IQ*/Q*); metadata-only fetch only; do not download weights without human approval. |
| bati.cpp | `batiai/bati.cpp` | `refs/tags/v0.1.2` | `c7b64fe065164335b882e02a848fd4015b3c060a` | MIT | Early-access runtime referenced by `batiai/DeepSeek-V4-Flash-GGUF`; CUDA build path exists but is not yet validated on Spark. |
| Spark bring-up (pruned checkpoint) | `Mockingjay1316/deepseek-v4-flash-spark` | `refs/heads/master` | `08045f89d9716d3249ce834be1a1b1d91fd40859` | MIT | Single-Spark reference: prunes learned-router experts (example 256→128) and uses a streaming loader to avoid unified-memory OOM. |
| Spark bring-up (native checkpoint runtime) | `bigs/deepseek-v4-flash-dgx-spark` | `refs/heads/main` | `4410e814a76a1a9d662576e2a35fa4a8965d2edc` | UNKNOWN | No `LICENSE*` file detected at pinned commit (see `./scripts/upstream_license_probe.sh`); research runtime + OpenAI-compatible server for native FP8/FP4 checkpoint layout on Spark; includes inspection + manifest tooling; do not run without human-approved fixtures/hardware time. |
| Spark bring-up (GB10 C++ runtime, MXFP4) | `devid791/dsv4-flash-gb10-runtime` | `refs/heads/main` | `244cb11d3ee3adfd96bd0f95d6a91649af7af45d` | Apache-2.0 | Proof-of-life Spark/GB10 runtime that loads the official BF16 HF snapshot and quantizes routed experts to MXFP4 on the fly; requires a human-approved HF snapshot download (large disk footprint). |
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
- [`docs/upstream-single-spark-v4-flash.md`](upstream-single-spark-v4-flash.md)
- [`docs/upstream-spark-v4-bringup.md`](upstream-spark-v4-bringup.md)
