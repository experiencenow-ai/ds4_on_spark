# Upstream: DeepSeek-V4-Flash (official configs)

DeepSeek-V4-Flash “official code/configs” are distributed via the Hugging Face model repo. This project **must not** download or vendor large model artifacts; treat the HF repo as metadata/config only.

## Sources

- Hugging Face repo: `https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash`
  - Ref: `refs/heads/main`
  - Commit: `6976c7ff1b30a1b2cb7805021b8ba4684041f136`
  - License: MIT (see HF `LICENSE`)

Optional related checkpoint:

- `https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base`
  - Ref: `refs/heads/main`
  - Commit: `8855555deef230a27a21a8d6f294b7b7497759b6`

## vLLM references

DeepSeek-V4 support is documented/implemented in vLLM (see `vllm.model_executor.models.deepseek_v4`):

- `https://docs.vllm.ai/en/latest/api/vllm/model_executor/models/deepseek_v4/`

## Transformers references

Transformers publishes an architecture + integration reference for `deepseek_v4`:

- `https://huggingface.co/docs/transformers/model_doc/deepseek_v4`

## Fetch (metadata only)

The fetch script disables Git LFS smudge/filters (and sets `GIT_LFS_SKIP_SMUDGE=1`) so LFS weights are not downloaded.

```bash
./scripts/fetch_upstreams.sh deepseek_v4_flash_hf
```
