# Upstream: DeepSeek-V4-Flash quantized candidates (safetensors)

This repo does **not** vendor model weights. This note tracks community **safetensors** snapshots that claim `deepseek-ai/DeepSeek-V4-Flash` as their base model. Treat these as **human-approved fixtures only** (no downloads by automation).

For GGUF-based candidates, see [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md).

## Candidate: bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target

## Source

- Repo: `https://huggingface.co/bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target`
- Ref: `refs/heads/main`
- Commit: `4ce0d4ac6bd35b63b68dfc813d0ae07497c4bf49`
- License: MIT (HF model card + `LICENSE` in repo)
- `base_model`: `deepseek-ai/DeepSeek-V4-Flash` (HF metadata)

## Footprint (HF API, no downloads)

As of `4ce0d4ac6bd35b63b68dfc813d0ae07497c4bf49`:

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

- **Plausible by size** for Spark0-class memory (≈82 GiB artifact), but **blocked** until we pin a runtime that can load this specific `quantization_config` safetensors layout.
- This project should not attempt to load or download these weights without explicit human approval.
