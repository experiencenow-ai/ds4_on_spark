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
  - The upstream README states the full FP4 checkpoint is ~149 GB and does not fit on a 128 GB unified-memory Spark, while a 128-expert prune is ~85 GB and leaves headroom for runtime/KV.
- Why we track it:
  - Reference for single-Spark feasibility when staying in the official checkpoint format (not GGUF), and for “page-cache aware” streaming load patterns that matter on unified-memory systems.
- Risk notes:
  - Requires downloading the official HF checkpoint and running a conversion step; treat as human-approved, Spark-only work.

## bigs/deepseek-v4-flash-dgx-spark (native checkpoint runtime experiments)

- Repo: `https://github.com/bigs/deepseek-v4-flash-dgx-spark`
- Ref: `refs/heads/main`
- Commit: `4410e814a76a1a9d662576e2a35fa4a8965d2edc`
- License: UNKNOWN (GitHub API does not report a repo license; verify before reuse)
- What it is (from upstream README, summarized):
  - Research runtime + OpenAI-compatible server for running DeepSeek-V4-Flash from the **native FP8/FP4 checkpoint layout**, with Spark-specific measurement/guardrails.
  - Includes scripts for checkpoint inspection + weight-manifest generation and a guarded Docker runner for Spark experiments.
- Why we track it:
  - A concrete “native checkpoint on Spark” reference that complements GGUF/llama.cpp paths; useful for studying manifest mapping + lazy expert materialization ideas.
- Risk notes:
  - Requires the official HF checkpoint; also includes Spark-specific CUDA experimentation that is out-of-scope for this repo’s non-hardware automation loop.

## 0xSero/deepseek-v4-flash-sm120 (Blackwell/SGLang kernel patch)

- Repo: `https://github.com/0xSero/deepseek-v4-flash-sm120`
- Ref: `refs/heads/main`
- Commit: `c2eac5a9b2b457881d69b1164d909e8beab9286e`
- License: Apache-2.0 (upstream; README also calls out CUTLASS submodule licensing)
- What it is (from upstream README, summarized):
  - A small CUDA extension + runtime patch for SGLang to provide FlashMLA sparse-decode kernels on Blackwell SM120 GPUs (the upstream image targets SM90/SM100).
- Why we track it:
  - Reference for “Blackwell arch gaps” when using containerized runtimes; could be relevant if Spark/GB10 (SM121) hits similar architecture filtering issues in third-party images.
- Risk notes:
  - Not Spark/SM121-specific; treat as a reference until validated on actual Spark hardware.

