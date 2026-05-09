# Upstream: DeepSeek-V4-Flash (official configs)

DeepSeek-V4-Flash “official code/configs” are distributed via the Hugging Face model repo. This project **must not** download or vendor large model artifacts; treat the HF repo as metadata/config only.

## Sources

- Hugging Face repo: `https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash`
  - Ref: `refs/heads/main`
  - Commit: `6976c7ff1b30a1b2cb7805021b8ba4684041f136`
  - License: MIT (see HF `LICENSE`)

Related checkpoint (same “official configs” approach):

- `https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base`
  - Ref: `refs/heads/main`
  - Commit: `8855555deef230a27a21a8d6f294b7b7497759b6`
  - License: MIT (see HF `LICENSE`)

## Related official kernel repos (reference)

These are tracked as optional GPU-kernel reference points for Spark:

- DeepGEMM: see [`docs/upstream-deepgemm.md`](upstream-deepgemm.md)
- FlashMLA: see [`docs/upstream-flashmla.md`](upstream-flashmla.md)

## What we read from HF (no weights)

- `config.json`, `generation_config.json`
- `tokenizer.json`, `tokenizer_config.json`
- `encoding/` (tokenizer-related assets)
- `inference/` (reference scripts; small, but do not vendor)
- `DeepSeek_V4.pdf` (technical report)

## Weight download risk (Git LFS)

- The HF repos include many `model-*.safetensors` files tracked by Git LFS.
- When fetched via `scripts/fetch_upstreams.sh` with LFS disabled, these appear as small pointer stubs (first line `version https://git-lfs.github.com/spec/v1`), not actual weights.
- Do not run `git lfs pull` (or any alternative fetch that resolves LFS blobs) inside `upstreams/deepseek_v4_*`.

## HF storage backend note (Xet/LFS)

The Hub increasingly serves large files via Xet-backed storage, while keeping Git-compatible workflows. Regardless of backend, this repo always treats the Git transport (`git ls-remote`, `git clone`) as the source of truth for the pinned commit hashes used by our fetch/verify scripts.

## Hugging Face revisions vs git commits

Hugging Face’s web UI may show short “revision IDs” (often 7 hex chars) that don’t match the git commit hash returned by `git ls-remote`. This project treats the git transport as the source of truth because `scripts/fetch_upstreams.sh` uses `git clone/fetch`.

To see the exact git commit for the pinned ref, use:

```bash
git ls-remote https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash refs/heads/main
```
## Quantized single-Spark candidates

Quantized community artifacts are useful for the intermediate "one Spark produces tokens" milestone, but they are not canonical sources of model semantics. Track them as runtime fixtures, not upstream truth.

Before using any quantized artifact, record:

- HF repo and exact revision
- file list, file sizes, and sha256 for downloaded files
- declared quantization type and declared base model
- required runtime fork/branch/commit
- license and conversion notes

Do not add community quantized model repos to `scripts/fetch_upstreams.sh` unless the fetch remains metadata-only. Large GGUF or safetensor downloads must remain human-approved, manual fixture setup.

## vLLM references

DeepSeek-V4 support is documented/implemented in vLLM (see `vllm.model_executor.models.deepseek_v4`):

- `https://docs.vllm.ai/en/latest/api/vllm/model_executor/models/deepseek_v4/`

Flash vs Flash-Base (important runtime semantic):

- vLLM keys MoE expert handling off `expert_dtype` in the HF config:
  - Flash: `expert_dtype="fp4"` (MXFP4 experts + UE8M0 FP8 linear scales)
  - Flash-Base: `expert_dtype="fp8"` (FP8 block experts + float32 FP8 scales)
- Treat “Flash vs Base” as more than just weights: it changes which expert kernels and scale dtypes are correct.

## Transformers references

Transformers publishes an architecture + integration reference for `deepseek_v4`:

- `https://huggingface.co/docs/transformers/model_doc/deepseek_v4`

## Fetch (metadata only)

The fetch script disables Git LFS smudge/filters (and sets `GIT_LFS_SKIP_SMUDGE=1`) so LFS weights are not downloaded.

```bash
./scripts/fetch_upstreams.sh deepseek_v4_flash_hf
```

To fetch the Flash-Base HF metadata (no weights):

```bash
./scripts/fetch_upstreams.sh deepseek_v4_flash_base_hf
```
