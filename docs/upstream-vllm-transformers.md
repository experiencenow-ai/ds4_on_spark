# Upstreams: vLLM + Transformers

These are tracked as “runtime + reference” components for Spark deployment work.

The pins below are validated by `./scripts/upstream_verify_pins.sh`. If you want to sanity-check that the pinned versions still contain DeepSeek-V4 support codepaths, see `./scripts/upstream_feature_probe.sh` (requires local `./upstreams/*` checkouts).

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

Pinned DeepSeek-V4 implementation pointers (local clone):

- Model entrypoint: `upstreams/vllm/vllm/model_executor/models/deepseek_v4.py`
- DeepSeek-V4 attention ops: `upstreams/vllm/vllm/v1/attention/ops/deepseek_v4_ops/`
- Fused KV insert kernel: `upstreams/vllm/csrc/fused_deepseek_v4_qnorm_rope_kv_insert_kernel.cu`

DeepSeek-V4-Flash vs Flash-Base (why we care):

- The vLLM DeepSeek-V4 FP8 config distinguishes MoE expert formats:
  - Flash: `expert_dtype="fp4"` (MXFP4 experts + UE8M0 FP8 linear scales)
  - Flash-Base: `expert_dtype="fp8"` (FP8 block experts + float32 scales)
- If we mis-detect `expert_dtype`, we can silently route the wrong expert-kernel path (compiles, but is wrong).

Build notes (Spark / GPU nodes, high level):

- Treat vLLM as an external runtime: prefer `pip install vllm==<version>` (or wheel) over building in-tree.
- CUDA compatibility is a triple constraint: driver + CUDA runtime + PyTorch build; pin all three in deployment docs.
- Validate that DeepSeek-V4 configs resolve correctly from the HF metadata repo (Flash vs Flash-Base differences).

DeepSeek-V4 landing notes:

- vLLM release notes for `v0.20.0` explicitly call out “DeepSeek V4: initial DeepSeek V4 support landed” (`#40860`): `https://github.com/vllm-project/vllm/releases`
- vLLM release notes for `v0.20.1` describe “DeepSeek V4 stabilization and performance improvements” (base model support, multi-stream pre-attn GEMM, etc.): `https://github.com/vllm-project/vllm/releases`
- vLLM blog (DeepSeek-V4 attention + deployment notes): `https://vllm.ai/blog/deepseek-v4`
- Community reports indicate some DeepSeek-V4 local deployments may require vLLM nightly wheels + a newer Transformers snapshot than the latest stable wheels; treat this as a compatibility watch item (not a guarantee): `https://discuss.vllm.ai/t/the-latest-version-of-vllm-is-not-compatible-with-local-deployment-of-deepseek-v4-0-20/2599`

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

Pinned DeepSeek-V4 implementation pointers (local clone):

- Model code: `upstreams/transformers/src/transformers/models/deepseek_v4/`
- Model docs: `upstreams/transformers/docs/source/en/model_doc/deepseek_v4.md`

DeepSeek-V4 landing notes:

- Transformers `v5.8.0` release notes list “New Model additions → DeepSeek-V4” and point at PR `#45643`: `https://github.com/huggingface/transformers/releases/tag/v5.8.0`
- The HF-hosted Transformers docs page notes DeepSeek-V4 was “added to Hugging Face Transformers on 2026-05-02”: `https://huggingface.co/docs/transformers/model_doc/deepseek_v4`

Build notes (Spark / packaging, high level):

- Prefer pinned wheels (`pip install transformers==<version>`) plus a pinned tokenizer stack (`tokenizers`, `sentencepiece` if required).
- Treat Transformers as the canonical reference for config/tokenization semantics; avoid re-implementing unless required for performance.
