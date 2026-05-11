# Upstream: DeepSeek-V4-Flash quantized candidates (safetensors)

This repo does **not** vendor model weights. This note tracks community **safetensors** snapshots that claim `deepseek-ai/DeepSeek-V4-Flash` as their base model. Treat these as **human-approved fixtures only** (no downloads by automation).

For GGUF-based candidates, see [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md).

## Candidate: bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target

## Source

- Repo: `https://huggingface.co/bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target`
- Ref: `refs/heads/main`
- Commit: `0cb3642b466e93bc30d83ff3f9afb122914e9645`
- License: MIT (HF model card + `LICENSE` in repo)
- `base_model`: `deepseek-ai/DeepSeek-V4-Flash` (HF metadata)

## Footprint (HF API, no downloads)

As of `0cb3642b466e93bc30d83ff3f9afb122914e9645`:

- Total repo storage: **82.34 GiB**
- `*.gguf`: **0 bytes** (none)
- Primary files are `model-*.safetensors` shards tracked by Git LFS.

Reproduce (metadata only):

```bash
./scripts/upstream_hf_api_report.sh bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target
./scripts/upstream_hf_api_report.sh bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target --sum-safetensors
```

## Quantization config (from `config.json`, metadata-only clone)

This repo’s `config.json` includes a `quantization_config` block describing a hybrid quant recipe:

- `quant_method`: `deepseek_v4_hybrid_iq2`
- `moe_experts`: `IQ2_XXS gate/up + Q2_K down (ds4 recipe)`
- `dense_layers`: `FP8 E4M3 block-128 with UE8M0 scales (sgl-project)`
- Sources recorded in the config:
  - `source_gguf`: `antirez/deepseek-v4-gguf`
  - `source_fp8`: `sgl-project/DeepSeek-V4-Flash-FP8`
  - `converter`: `ds4_hybrid_quant.builder`

Note: the config’s `expert_dtype` is `fp8` (this should be treated as a runtime/loader contract and must be re-validated if this candidate is ever used).

## Runtime status (single Spark)

- **Plausible by size** for Spark0-class memory (≈82 GiB artifact).
- Intended runtime (pinned upstream): `Entrpi/ds4-spark-vllm` (see `docs/upstream-spark-v4-bringup.md` + `docs/upstream-manifest.md`).
  - The model card states it must be served via vLLM with `--quantization deepseek_v4_hybrid_iq2` (registered by the `ds4_hybrid_quant` overlay/plugin from `Entrpi/ds4-spark-vllm`).
  - The model card also calls out `VLLM_TRITON_MLA_SPARSE_MATMUL_DECODE=0` as correctness-critical on SM121 for layers with `compress_ratio>=4`.
- This repo should still treat the checkpoint as a **human-approved fixture only** (no automated downloads or local load attempts).
