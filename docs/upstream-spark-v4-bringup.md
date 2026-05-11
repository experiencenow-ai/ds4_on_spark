# Upstreams: Spark bring-up references (DeepSeek-V4-Flash)

These repos are tracked as **Spark-relevant bring-up references** for running DeepSeek-V4-Flash on a single DGX Spark / GB10-class system.

This project **must not** download or vendor large checkpoints/weights; treat these upstreams as documentation + code references only unless a human explicitly approves fixture setup on Spark.

## Mockingjay1316/deepseek-v4-flash-spark (single Spark prune + loader)

- Repo: `https://github.com/Mockingjay1316/deepseek-v4-flash-spark`
- Ref: `refs/heads/master`
- Commit: `08045f89d9716d3249ce834be1a1b1d91fd40859`
- License: MIT (upstream repo metadata)
- What it is (from upstream README, summarized):
  - A Spark/GB10-focused flow for producing and serving a **pruned** DeepSeek-V4-Flash checkpoint (example: learned-router experts pruned from 256 → 128) plus a **streaming loader** to avoid unified-memory OOM during load.
  - The upstream README states the full FP4 checkpoint is ~149 GB and does not fit on a 128 GB unified-memory Spark; the HF API reports the official Flash `*.safetensors` total is 148.66 GiB at `deepseek-ai/DeepSeek-V4-Flash` commit `6976c7ff1b30a1b2cb7805021b8ba4684041f136`. A 128-expert prune is ~85 GB and leaves headroom for runtime/KV.
- Why we track it:
  - Reference for single-Spark feasibility when staying in the official checkpoint format (not GGUF), and for “page-cache aware” streaming load patterns that matter on unified-memory systems.
- Risk notes:
  - Requires downloading the official HF checkpoint and running a conversion step; treat as human-approved, Spark-only work.

## Entrpi/ds4-spark-vllm (single Spark vLLM hybrid-quant bring-up)

- Repo: `https://github.com/Entrpi/ds4-spark-vllm`
- Ref: `refs/heads/main`
- Commit: `dab8c4c4a44111e686f516b747a7ffb161475943`
- License: MIT (see upstream `LICENSE`)
- What it is (from upstream README, summarized):
  - A Spark-focused bring-up that runs DeepSeek-V4-Flash through a **vLLM** stack while applying ds4-style hybrid quantization ideas (as opposed to the pure llama.cpp GGUF path).
  - The bring-up targets the quantized safetensors checkpoint `bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target` and registers vLLM `--quantization deepseek_v4_hybrid_iq2` via the `ds4_hybrid_quant` overlay/plugin.
  - Upstream model card calls out a correctness knob for SM121: `VLLM_TRITON_MLA_SPARSE_MATMUL_DECODE=0` (switches away from the default triton compressed-decode kernel path for `compress_ratio>=4` layers).
- Why we track it:
  - Useful as a “vLLM-first” reference when a GGUF path is not viable, and as a cross-check against ds4/llama.cpp behavior for the same prompts.
- Risk notes:
  - Assumes a local checkpoint is already staged; do not pull weights without explicit approval.

## bigs/deepseek-v4-flash-dgx-spark (native checkpoint runtime experiments)

- Repo: `https://github.com/bigs/deepseek-v4-flash-dgx-spark`
- Ref: `refs/heads/main`
- Commit: `4410e814a76a1a9d662576e2a35fa4a8965d2edc`
- License: UNKNOWN (no `LICENSE*` file detected at pinned commit; see `./scripts/upstream_license_probe.sh` before reuse)
- What it is (from upstream README, summarized):
  - Research runtime + OpenAI-compatible server for running DeepSeek-V4-Flash from the **native FP8/FP4 checkpoint layout**, with Spark-specific measurement/guardrails.
  - Includes scripts for checkpoint inspection + weight-manifest generation and a guarded Docker runner for Spark experiments.
- Why we track it:
  - A concrete “native checkpoint on Spark” reference that complements GGUF/llama.cpp paths; useful for studying manifest mapping + lazy expert materialization ideas.
- Risk notes:
  - Requires the official HF checkpoint; also includes Spark-specific CUDA experimentation that is out-of-scope for this repo’s non-hardware automation loop.

## devid791/dsv4-flash-gb10-runtime (MXFP4 proof-of-life on GB10/GX10)

- Repo: `https://github.com/devid791/dsv4-flash-gb10-runtime`
- Ref: `refs/tags/v0.1.0`
- Commit: `244cb11d3ee3adfd96bd0f95d6a91649af7af45d`
- License: Apache-2.0 (see upstream `LICENSE`)
- What it is (from upstream README, summarized):
  - A proof-of-life runtime targeting a single GB10/GX10-class node (sm_121a, 128 GB unified memory) running DeepSeek-V4-Flash end-to-end without sharding/TP/PP.
  - Loads the official **BF16** Hugging Face snapshot and quantizes **routed experts** to **MXFP4** on the fly, then runs a custom C++/CUDA engine via a thin Python wrapper.
  - Focus is staged correctness (forced-token gates + per-layer tensor comparisons) rather than throughput optimization.
  - Provenance thread (2026-05-05): `https://forums.developer.nvidia.com/t/deepseek-v4-flash-mxfp4-proof-of-life-on-a-single-gb10-gx10/369131`
- Why we track it:
  - It is the most directly Spark/GB10-targeted “native checkpoint format” bring-up reference with a concrete build + correctness harness.
- Risk notes:
  - Requires a human-approved download of the official HF snapshot and a large disk footprint; out-of-scope for this repo’s non-hardware automation loop.

## 0xSero/deepseek-v4-flash-sm120 (Blackwell/SGLang kernel patch)

- Repo: `https://github.com/0xSero/deepseek-v4-flash-sm120`
- Ref: `refs/heads/main`
- Commit: `c2eac5a9b2b457881d69b1164d909e8beab9286e`
- License: Apache-2.0 (upstream; README also calls out CUTLASS submodule licensing)
- Base runtime: `sgl-project/sglang` (see [`docs/upstream-sglang.md`](upstream-sglang.md) for the current pinned commit); upstream README targets `lmsysorg/sglang:deepseek-v4-blackwell` Docker image
- What it is (from upstream README, summarized):
  - A small CUDA extension + runtime patch for SGLang to provide FlashMLA sparse-decode kernels on Blackwell SM120 GPUs (the upstream image targets SM90/SM100).
- Why we track it:
  - Reference for “Blackwell arch gaps” when using containerized runtimes; could be relevant if Spark/GB10 (SM121) hits similar architecture filtering issues in third-party images.
- Risk notes:
  - Not Spark/SM121-specific; treat as a reference until validated on actual Spark hardware.
