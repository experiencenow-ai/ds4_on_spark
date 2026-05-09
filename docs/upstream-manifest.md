# Upstream Manifest

Pinned upstream references for `experiencenow-ai/ds4_on_spark`.

- Pinned-at: 2026-05-09 (UTC)
- Policy: do **not** vendor large third-party trees or model weights; fetch on-demand and pin exact commits.

## Canonical Upstreams (Pinned)

| Name | Upstream | Ref | Commit | License | Notes |
| --- | --- | --- | --- | --- | --- |
| ds4 | `antirez/ds4` | `refs/heads/main` | `d615ab08c8bce9b8242963ecece5aed6b5a79367` | MIT | DeepSeek-V4-Flash-specific native engine (Metal-first); semantics + KV-cache design reference; do not run upstream model-download scripts. |
| DeepGEMM | `deepseek-ai/DeepGEMM` | `refs/tags/v2.1.1.post3` | `c9f8b34dcdacc20aa746b786f983492c51072870` | MIT | CUDA GEMM kernels; treat as optional accelerator reference. |
| DeepSeek-V3 (code) | `deepseek-ai/DeepSeek-V3` | `refs/tags/v1.0.0` | `f6e34dd26772dd4a216be94a8899276c5dca9e43` | MIT (code) | Repo has distinct code vs model/weights licensing. |
| DeepSeek-V4-Flash (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/heads/main` | `6976c7ff1b30a1b2cb7805021b8ba4684041f136` | MIT | HF repo is “official code/configs” source; fetch with `GIT_LFS_SKIP_SMUDGE=1` to avoid weights; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| DeepSeek-V4-Flash-Base (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base` | `refs/heads/main` | `8855555deef230a27a21a8d6f294b7b7497759b6` | MIT | Optional checkpoint; fetch metadata-only (no weights) via `GIT_LFS_SKIP_SMUDGE=1`; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| vLLM | `vllm-project/vllm` | `refs/tags/v0.20.2` | `bc150f50299199599673614f80d12a196f377655` | Apache-2.0 | Inference runtime reference; includes DeepSeek-V4 model support docs. |
| Transformers | `huggingface/transformers` | `refs/tags/v5.8.0` | `a9e70365af64e028d40d8c7909deb7f138b49857` | Apache-2.0 | Reference for HF config/tokenization + model wrappers. |
| llama.cpp | `ggml-org/llama.cpp` | `refs/tags/b8833` | `45cac7ca703fb9085eae62b9121fca01d20177f6` | MIT | Spark-relevant baseline for CPU/GPU inference + ggml tooling (pinned to a release tag). |

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
