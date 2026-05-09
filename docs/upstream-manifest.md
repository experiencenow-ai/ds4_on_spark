# Upstream Manifest

Pinned upstream references for `experiencenow-ai/ds4_on_spark`.

- Pinned-at: 2026-05-09 (UTC)
- Policy: do **not** vendor large third-party trees or model weights; fetch on-demand and pin exact commits.

## Canonical Upstreams (Pinned)

| Name | Upstream | Ref | Commit | License | Notes |
| --- | --- | --- | --- | --- | --- |
| ds4 | `antirez/ds4` | `refs/heads/main` | `d615ab08c8bce9b8242963ecece5aed6b5a79367` | MIT | DeepSeek-V4-Flash-specific native engine (Metal-first); semantics + KV-cache design reference; do not run upstream model-download scripts. |
| DeepGEMM | `deepseek-ai/DeepGEMM` | `refs/tags/v2.1.1.post3` | `c9f8b34dcdacc20aa746b786f983492c51072870` | MIT | CUDA GEMM kernels; treat as optional accelerator reference; pinned to a release tag (vs `main`). |
| DeepSeek-V3 (code) | `deepseek-ai/DeepSeek-V3` | `refs/tags/v1.0.0` | `f6e34dd26772dd4a216be94a8899276c5dca9e43` | MIT (code) | Repo has distinct code vs model/weights licensing. |
| DeepSeek-V4-Flash (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/heads/main` | `6976c7ff1b30a1b2cb7805021b8ba4684041f136` | MIT | HF repo is “official code/configs” source; fetch with `GIT_LFS_SKIP_SMUDGE=1` to avoid weights; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| DeepSeek-V4-Flash-Base (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base` | `refs/heads/main` | `8855555deef230a27a21a8d6f294b7b7497759b6` | MIT | Optional checkpoint; fetch metadata-only (no weights) via `GIT_LFS_SKIP_SMUDGE=1`; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| vLLM | `vllm-project/vllm` | `refs/tags/v0.20.2` | `bc150f50299199599673614f80d12a196f377655` | Apache-2.0 | Inference runtime reference; includes DeepSeek-V4 model support docs. |
| Transformers | `huggingface/transformers` | `refs/tags/v5.8.0` | `a9e70365af64e028d40d8c7909deb7f138b49857` | Apache-2.0 | Reference for HF config/tokenization + model wrappers. |
| llama.cpp | `ggml-org/llama.cpp` | `refs/tags/b8833` | `45cac7ca703fb9085eae62b9121fca01d20177f6` | MIT | Spark-relevant baseline for CPU/GPU inference + ggml tooling (pinned to a release tag). |
| llama.cpp (DeepSeek V4 Flash fork) | `antirez/llama.cpp-deepseek-v4-flash` | `refs/heads/main` | `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f` | MIT | Flash-specific fork widely referenced by community GGUFs; not in upstream `ggml-org/llama.cpp` yet. |
| llama.cpp (DeepSeek V4 support WIP) | `nisparks/llama.cpp` | `refs/heads/wip/deepseek-v4-support` | `9d364087024da141510267e6b269ee495ca45176` | MIT | WIP branch adding `F8_E4M3_B128` + `MXFP4` types + V4 loader/converter; required by some “native FP4/FP8” GGUF artifacts. |
| llama.cpp (CUDA Spark fork) | `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` | `refs/heads/master` | `9222e55c13c965ccb7e9104fda58796edd84a732` | MIT | CUDA fork reported running on a single DGX Spark/GB10; validate perf + memory headroom on target Spark. |
| DeepSeek-V4-Flash GGUF (antirez) | `huggingface.co/antirez/deepseek-v4-gguf` | `refs/heads/main` | `ef3b960827870d69ed0b225c095a617c12d7e80d` | MIT | Single-file GGUF (~87 GB) tuned for `ds4` and used as single-Spark candidate; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Preyazz) | `huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d` | MIT | Single-file Q2_K (~96 GiB) candidate; requires V4-capable llama.cpp fork (see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (BatiAI) | `huggingface.co/batiai/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `70c9597f26a5b4747272477fff37986c4ce484ef` | MIT | Sharded GGUFs requiring `batiai/bati.cpp`; smallest quant listed is ~127 GB (not single-Spark plausible); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (lovedheart) | `huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `cd42deba41ac0536e68b125dfc367197b0ec3038` | UNKNOWN | Sharded Q2_K total ~93.6 GiB (single-Spark plausible but tight); README references llama.cpp PR `#22378` (closed; see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (native FP4/FP8) | `huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF` | `refs/heads/main` | `0b34e0b629c706396002496e795e9f910f7bf69f` | DeepSeek (link) | Single-file GGUF (~146 GB) 1:1 FP4/FP8 conversion; requires V4 loader + FP8/MXFP4 kernel support; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (abliterated) | `huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF` | `refs/heads/main` | `665c8e035e2602d12d28b84920808b158f337e09` | MIT | Experimental safety-research artifact; includes Q2_K (~99 GB) and Q8_0 (~302 GB) variants; do not download without human approval. |
| bati.cpp | `batiai/bati.cpp` | `refs/tags/v0.1.2` | `c7b64fe065164335b882e02a848fd4015b3c060a` | MIT | Early-access runtime referenced by `batiai/DeepSeek-V4-Flash-GGUF`; CUDA build path exists but is not yet validated on Spark. |

## Fetching

Use [`scripts/fetch_upstreams.sh`](../scripts/fetch_upstreams.sh) to clone pinned refs into a local `upstreams/` directory (ignored by git). For Hugging Face repos, the script sets `GIT_LFS_SKIP_SMUDGE=1` so large weight blobs are not downloaded.

## Refreshing Pins

To see the current HEAD commits upstream (without cloning), run:

```bash
./scripts/upstream_ls_remote.sh
```

To verify that the **pinned** refs/commits in this manifest still resolve upstream, run:

```bash
./scripts/upstream_verify_pins.sh
```

## Per-Upstream Notes

- [`docs/upstream-ds4.md`](upstream-ds4.md)
- [`docs/upstream-deepgemm.md`](upstream-deepgemm.md)
- [`docs/upstream-deepseek-v3.md`](upstream-deepseek-v3.md)
- [`docs/upstream-deepseek-v4-flash.md`](upstream-deepseek-v4-flash.md)
- [`docs/upstream-vllm-transformers.md`](upstream-vllm-transformers.md)
- [`docs/upstream-llama-cpp.md`](upstream-llama-cpp.md)
- [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md)
