# Upstreams: vLLM + Transformers

These are tracked as “runtime + reference” components for Spark deployment work.

## vLLM

- Repo: `https://github.com/vllm-project/vllm`
- Ref: `refs/tags/v0.20.2`
- Commit: `bc150f50299199599673614f80d12a196f377655`
- License: Apache-2.0 (see upstream `LICENSE`)
- DeepSeek-V4 docs: `https://docs.vllm.ai/en/latest/api/vllm/model_executor/models/deepseek_v4/`

Fetch:

```bash
./scripts/fetch_upstreams.sh vllm
```

Build notes (Spark / GPU nodes, high level):

- Treat vLLM as an external runtime: prefer `pip install vllm==<version>` (or wheel) over building in-tree.
- CUDA compatibility is a triple constraint: driver + CUDA runtime + PyTorch build; pin all three in deployment docs.
- Validate that DeepSeek-V4 configs resolve correctly from the HF metadata repo (Flash vs Flash-Base differences).

## Transformers

- Repo: `https://github.com/huggingface/transformers`
- Ref: `refs/tags/v5.8.0`
- Commit: `049d2bf1220747b6d39e2a978b9f5fe0defa1dca`
- License: Apache-2.0 (see upstream `LICENSE`)
- DeepSeek-V4 docs: `https://huggingface.co/docs/transformers/model_doc/deepseek_v4`

Fetch:

```bash
./scripts/fetch_upstreams.sh transformers
```

Build notes (Spark / packaging, high level):

- Prefer pinned wheels (`pip install transformers==<version>`) plus a pinned tokenizer stack (`tokenizers`, `sentencepiece` if required).
- Treat Transformers as the canonical reference for config/tokenization semantics; avoid re-implementing unless required for performance.
