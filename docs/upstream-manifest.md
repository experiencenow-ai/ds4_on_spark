# Upstream Manifest

Pinned upstream references for this Spark local-inference performance lab (repo name `experiencenow-ai/ds4_on_spark` is historical shorthand).

Scope hygiene: treat DeepSeek V4 Flash, Qwen/Ling comparator targets (target-only), and DFlash speculative decoding as separate tracks in reports (see `docs/model-quality-speed.md`).

- Pinned-at: 2026-05-12 (UTC)
- Policy: do **not** vendor large third-party trees or model weights; fetch on-demand and pin exact commits.

## Canonical Upstreams (Pinned)

| Name | Upstream | Ref | Commit | License | Notes |
| --- | --- | --- | --- | --- | --- |
| ds4 | `antirez/ds4` | `refs/heads/main` | `a97e7a3989c7825dbc4b49395aeeee800389ad70` | MIT | DeepSeek-V4-Flash-specific native engine with Metal and CUDA graph paths; upstream README reports DGX Spark GB10 q2 `343.81` prefill t/s + `13.75` generation t/s; do not run upstream model-download scripts without human approval. |
| DeepGEMM | `deepseek-ai/DeepGEMM` | `refs/tags/v2.1.1.post3` | `c9f8b34dcdacc20aa746b786f983492c51072870` | MIT | CUDA GEMM kernels; upstream support is SM90/SM100 only (Spark SM121 not covered yet); pinned to a release tag (vs `main`). |
| FlashMLA | `deepseek-ai/FlashMLA` | `refs/heads/main` | `9241ae3ef9bac614dd25e45e507e089f888280e0` | MIT | Efficient Multi-head Latent Attention kernels; upstream support is SM90/SM100 only (Spark SM121 not covered yet); treat as kernel-design reference for V4-Flash-style MLA. |
| DeepSeek-V3 (code) | `deepseek-ai/DeepSeek-V3` | `refs/tags/v1.0.0` | `f6e34dd26772dd4a216be94a8899276c5dca9e43` | MIT (code) | Repo has distinct code vs model/weights licensing. |
| DeepSeek-V4-Flash (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/heads/main` | `6976c7ff1b30a1b2cb7805021b8ba4684041f136` | MIT | HF repo is “official code/configs” source (no dedicated `deepseek-ai/*` GitHub V4 repo found as of 2026-05-11); fetch with `GIT_LFS_SKIP_SMUDGE=1` to avoid weights; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| DeepSeek-V4-Flash (HF PR 14, config drift watch) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/pr/14` | `6c858e71890b508e4f3fd6491f45b325580ba934` | MIT | Draft PR that removes `expert_dtype` from top-level `config.json` while keeping `inference/config.json` `expert_dtype="fp4"`; track for Flash vs Flash-Base semantic stability (do not download weights). |
| DeepSeek-V4-Flash (HF PR 16, chat-template drift watch) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/pr/16` | `014a5cfe6d1349d3d1096b2f8c15faaaa11819d5` | MIT | Draft PR ref for reproducible inspection of “conversational”/templating changes (e.g. `chat_template.jinja`) and any config deltas; do not download weights. |
| DeepSeek-V4-Flash (HF PR 18, SGLang + config drift watch) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash` | `refs/pr/18` | `e37f9032e9116f7002fc917b720e945857bbac68` | MIT | Draft PR that adds an SGLang deployment pointer and also removes `expert_dtype` from top-level `config.json` (matching PR 14 drift) while changing `inference/model.py` shared-expert construction; treat as runtime-visible semantic drift (do not download weights). |
| DeepSeek-V4-Flash-Base (HF) | `huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base` | `refs/heads/main` | `8855555deef230a27a21a8d6f294b7b7497759b6` | MIT | Optional checkpoint; fetch metadata-only (no weights) via `GIT_LFS_SKIP_SMUDGE=1`; commit here is from git transport (`git ls-remote`), not the HF web UI revision string. |
| DeepSeek-V4-Flash-FP8 (HF) | `huggingface.co/sgl-project/DeepSeek-V4-Flash-FP8` | `refs/heads/main` | `ae01d80c06cdfe30581edfd0e1c5449dc7ed7f17` | MIT | FP8 checkpoint mirror used in SGLang examples; metadata-only fetch only (LFS disabled); do not download weights without human approval. |
| vLLM | `vllm-project/vllm` | `refs/tags/v0.20.2` | `bc150f50299199599673614f80d12a196f377655` | Apache-2.0 | Inference runtime reference; DeepSeek-V4 support called out in v0.20.0 release notes (#40860). |
| Transformers | `huggingface/transformers` | `refs/tags/v5.8.0` | `049d2bf1220747b6d39e2a978b9f5fe0defa1dca` | Apache-2.0 | Reference for HF config/tokenization + model wrappers; v5.8.0 release adds DeepSeek-V4 integration (#45643). |
| DeepSeek-V4-Flash W4A16-FP8 quant recipe (reference) | `pasta-paul/dsv4-flash-w4a16-fp8` | `refs/heads/main` | `6fb9cbe0348030b4877c5e4f5964900d7a43b017` | Apache-2.0 | Quantization recipe + patches for W4A16-FP8 on 8x H200; not Spark-specific; use as a conversion/benchmarking reference only. |
| DeepSeek-V4-Flash vLLM Ampere patch (reference) | `Lasimeri/vllm-dsv4-ampere` | `refs/heads/master` | `06f6f6058834907b7db490f440baa443787a0666` | UNKNOWN | Community patch set to run DeepSeek-V4-Flash on Ampere SM86 via vLLM pyref/Triton fallbacks; no `LICENSE*` detected at pinned commit; treat as license-unknown reference only. |
| DFlash (code) | `z-lab/dflash` | `refs/heads/main` | `94e4abc5e0c31b67bc1a9d30f1cc34ece28a8756` | MIT | DFlash block diffusion speculative decoding reference; model cards pin vLLM/SGLang PR refs; see `docs/upstream-qwen-dflash.md`. |
| vLLM (DFlash PR ref) | `vllm-project/vllm` | `refs/pull/40898/head` | `23002d3f368a5a24641301bc71e4ae15dae89a24` | Apache-2.0 | Z Lab DFlash model cards reference this PR ref for speculative decoding support; pin it separately from release tags for reproducible inspection. |
| SGLang (DFlash PR ref) | `sgl-project/sglang` | `refs/pull/20547/head` | `e67a0d488d905661e621342912874bc7893f1d94` | Apache-2.0 | Z Lab DFlash model cards reference this PR ref; pin it separately from the release-tag SGLang row for reproducible inspection. |
| AEON Qwen3.6 27B DFlash ops | `AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-DFlash` | `refs/heads/main` | `67be1e0e8450a8f1ba68793563a1266ab7197363` | Apache-2.0 | DGX Spark Qwen3.6 27B XS + DFlash deployment/benchmark reference; no weights; see `docs/upstream-aeon-qwen36-dflash.md`. |
| AEON vLLM DFlash ops | `AEON-7/vllm-dflash` | `refs/heads/main` | `4efa0929a01f06a96fe7a10bd74652b1e2380f19` | Apache-2.0 | Older Qwen3.5 27B DFlash Spark deployment/benchmark reference with useful acceptance/concurrency notes; no weights; see `docs/upstream-aeon-qwen36-dflash.md`. |
| AEON Qwen3.6 27B MTP-XS (HF) | `huggingface.co/AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-Multimodal-NVFP4-MTP-XS` | `refs/heads/main` | `6394b93fa092dcbfbf09e952f56f30337509d17c` | Apache-2.0 | Spark-sized Qwen3.6 27B XS modelopt body used by AEON's DFlash recipe (19.15 GiB safetensors); do not download without human approval. |
| GPT-OSS-20B (HF) | `huggingface.co/openai/gpt-oss-20b` | `refs/heads/main` | `6cee5e81ee83917806bbde320786a8fb61efebee` | Apache-2.0 | Open target with official Z Lab DFlash drafter (25.63 GiB safetensors); HF repo also includes large LFS blobs (e.g. `metal/model.bin`); do not download without human approval; see `docs/upstream-dflash.md`. |
| GPT-OSS-20B-DFlash (HF) | `huggingface.co/z-lab/gpt-oss-20b-DFlash` | `refs/heads/main` | `d53f6551543204c859e8bbaaddbd15d11b447af9` | MIT | Paired DFlash draft checkpoint (1.46 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Llama-3.1-8B-Instruct (HF) | `huggingface.co/meta-llama/Llama-3.1-8B-Instruct` | `refs/heads/main` | `0e9e39f249a16976918f6564b8830bc894c89659` | llama3.1 | Small target with an official Z Lab DFlash drafter (14.96 GiB safetensors); repo also includes large LFS “original” blobs; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Llama-3.1-8B-Instruct-DFlash-UltraChat (HF) | `huggingface.co/z-lab/LLaMA3.1-8B-Instruct-DFlash-UltraChat` | `refs/heads/main` | `d3af30def9601abdd10810aba220d692f0e803f0` | MIT | Paired DFlash draft checkpoint (1.95 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| GPT-OSS-120B (HF) | `huggingface.co/openai/gpt-oss-120b` | `refs/heads/main` | `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` | Apache-2.0 | Large target (121.54 GiB safetensors; likely not single-Spark plausible); keep as provenance reference only; do not download without human approval; see `docs/upstream-dflash.md`. |
| GPT-OSS-120B-DFlash (HF) | `huggingface.co/z-lab/gpt-oss-120b-DFlash` | `refs/heads/main` | `1278df34f0a7bd2c8588a27f49048aaa05c7db00` | MIT | Paired DFlash draft checkpoint (1.46 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Kimi-K2.5 (HF) | `huggingface.co/moonshotai/Kimi-K2.5` | `refs/heads/main` | `4d01dfe0332d63057c186e0b262165819efb6611` | Modified-MIT | Multimodal MoE target (554.30 GiB safetensors; not single-Spark plausible); keep as provenance reference only for paired DFlash drafts. |
| Kimi-K2.5-DFlash (HF) | `huggingface.co/z-lab/Kimi-K2.5-DFlash` | `refs/heads/main` | `e2db14df8337367b5eae8a6c206ea0d7d01a42a8` | MIT | Paired DFlash draft checkpoint (6.48 GiB safetensors) for exact target `moonshotai/Kimi-K2.5`; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Kimi-K2.6 (HF) | `huggingface.co/moonshotai/Kimi-K2.6` | `refs/heads/main` | `b5aabbfb20227ed42becbf5541dbffd213942c58` | Other | Follow-up Kimi MoE target (554.30 GiB safetensors; not single-Spark plausible); HF license tag currently reports `other`; keep as provenance reference only for paired DFlash drafts. |
| Kimi-K2.6-DFlash (HF) | `huggingface.co/z-lab/Kimi-K2.6-DFlash` | `refs/heads/main` | `c1462ef46589f6ccb3eca424bffef94d72354ea9` | MIT | Paired DFlash draft checkpoint (6.48 GiB safetensors) for exact target `moonshotai/Kimi-K2.6`; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| MiniMax-M2.7 (HF) | `huggingface.co/MiniMaxAI/MiniMax-M2.7` | `refs/heads/main` | `d494266a4affc0d2995ba1fa35c8481cbd84294b` | Other | Large target (214.33 GiB safetensors; not single-Spark plausible); keep as provenance reference only for paired DFlash drafts. |
| MiniMax-M2.7-DFlash (HF) | `huggingface.co/z-lab/MiniMax-M2.7-DFlash` | `refs/heads/main` | `c36fb6e5ad86afc64ecc9824ab5a80d2ae640df3` | UNKNOWN | Paired DFlash draft checkpoint (1.04 GiB safetensors) for exact target `MiniMaxAI/MiniMax-M2.7`; model card raw access returned HTTP 401 at pinned sha; treat license as unknown until verified; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Qwen3-Coder-30B-A3B-Instruct-FP8 (HF) | `huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | `refs/heads/main` | `dcaee4d4dfc5ee71ad501f01f530e5652438fde0` | Apache-2.0 | Qwen FP8 comparison target (29.03 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3-Coder-30B-A3B-DFlash (HF) | `huggingface.co/z-lab/Qwen3-Coder-30B-A3B-DFlash` | `refs/heads/main` | `98ca0e3e2e6a372f2789d3a5e146566194084317` | MIT | Paired DFlash draft checkpoint (0.88 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.6-35B-A3B-FP8 (HF) | `huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8` | `refs/heads/main` | `95a723d08a9490559dae23d0cff1d9466213d989` | Apache-2.0 | FP8 MoE comparison target (34.89 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-35B-A3B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.6-35B-A3B-DFlash` | `refs/heads/main` | `42d3b34d588423cdae7ba8f53a8cf7789346a719` | MIT | Paired DFlash draft checkpoint (0.88 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.6-27B (HF) | `huggingface.co/Qwen/Qwen3.6-27B` | `refs/heads/main` | `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` | Apache-2.0 | Dense-ish comparison target (51.75 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-27B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.6-27B-DFlash` | `refs/heads/main` | `0919688658996800f86b895034249700e9481106` | MIT | Paired DFlash draft checkpoint (3.22 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.6-27B-DFlash (GGUF, spiritbuun, HF) | `huggingface.co/spiritbuun/Qwen3.6-27B-DFlash-GGUF` | `refs/heads/main` | `5e4442a299deb9282b3dfe179de6e8330b19d9de` | MIT | Community GGUF conversions of `z-lab/Qwen3.6-27B-DFlash` for llama.cpp experiments (2.68 GiB total across Q8_0 + Q4_K_M drafts); draft-only artifact; do not download without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-27B-DFlash (GGUF, Lucebox, HF) | `huggingface.co/Lucebox/Qwen3.6-27B-DFlash-GGUF` | `refs/heads/main` | `ad1c40503211a40b819469d402257cc9e98e5b5f` | Apache-2.0 | Community GGUF conversion of `z-lab/Qwen3.6-27B-DFlash` (1.71 GiB Q8_0); draft-only artifact; do not download without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-27B-DFlash (GGUF, Ardenzard, HF) | `huggingface.co/Ardenzard/Qwen3.6-27B-DFlash-GGUF` | `refs/heads/main` | `0b249ff557371b11c582f2d9cf1b0e7d99c2f06d` | MIT | Community GGUF conversions of `z-lab/Qwen3.6-27B-DFlash` (10.18 GiB total; includes F16 + Q8_0 variants); draft-only artifact; do not download without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-35B-A3B-DFlash (GGUF, starskyzheng, HF) | `huggingface.co/starskyzheng/Qwen3.6-35B-DFlash-GGUF` | `refs/heads/main` | `3065fea71cafc7346ee2ab16e8fe1636eb74428a` | MIT | Community GGUF conversions of `z-lab/Qwen3.6-35B-A3B-DFlash` (1.64 GiB total across F16 + Q8_0 + Q4_K_M drafts); draft-only artifact; do not download without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-35B-A3B-DFlash (GGUF, abhinand, HF) | `huggingface.co/abhinand/Qwen3.6-35B-A3B-DFlash-GGUF` | `refs/heads/main` | `97ea13883f85fbf35e5a4539dc756e8e3f400cef` | MIT | Community GGUF conversions of `z-lab/Qwen3.6-35B-A3B-DFlash` (2.02 GiB total across BF16 + Q8_0 + Q6_K + Q4_K_M drafts); draft-only artifact; do not download without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.6-27B-FP8 (HF) | `huggingface.co/Qwen/Qwen3.6-27B-FP8` | `refs/heads/main` | `e89b16ebf1988b3d6befa7de50abc2d76f26eb09` | Apache-2.0 | FP8-packaged 27B target (28.75 GiB safetensors; single-Spark plausible); no official DFlash drafter found; do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-27B (HF) | `huggingface.co/Qwen/Qwen3.5-27B` | `refs/heads/main` | `fc05daec18b0a78c049392ed2e771dde82bdf654` | Apache-2.0 | Dense-ish 27B comparison target (51.75 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-27B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.5-27B-DFlash` | `refs/heads/main` | `b0400439c04be32c24e04d9dce3821b582c1a68a` | MIT | Paired DFlash draft checkpoint (3.22 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.5-27B-DFlash (GGUF, spiritbuun, HF) | `huggingface.co/spiritbuun/Qwen3.5-27B-DFlash-GGUF` | `refs/heads/main` | `3fa59f082214838d36d01d5d1276758efb1f3b3c` | MIT | Community GGUF conversion of `z-lab/Qwen3.5-27B-DFlash` (0.96 GiB Q4_K_M); draft-only artifact; do not download without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-27B-FP8 (HF) | `huggingface.co/Qwen/Qwen3.5-27B-FP8` | `refs/heads/main` | `97f5941bf617e31c5e237364a8602ce3f03a551a` | Apache-2.0 | FP8-packaged 27B target (28.75 GiB safetensors; single-Spark plausible); no official DFlash drafter found; do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-35B-A3B (HF) | `huggingface.co/Qwen/Qwen3.5-35B-A3B` | `refs/heads/main` | `59d61f3ce65a6d9863b86d2e96597125219dc754` | Apache-2.0 | MoE A3B comparison target (66.97 GiB safetensors; single-Spark plausible but less headroom than FP8 A3B); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-35B-A3B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.5-35B-A3B-DFlash` | `refs/heads/main` | `a6ab3a277f856d91c43f28711611e7929073d56d` | MIT | Paired DFlash draft checkpoint (0.88 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3.5-9B (HF) | `huggingface.co/Qwen/Qwen3.5-9B` | `refs/heads/main` | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | Apache-2.0 | Smaller Qwen comparison target (17.98 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-9B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.5-9B-DFlash` | `refs/heads/main` | `492f4b532a957a50561e1418e5a3f31690f127f4` | MIT | Paired DFlash draft checkpoint (1.95 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3-8B (HF) | `huggingface.co/Qwen/Qwen3-8B` | `refs/heads/main` | `b968826d9c46dd6066d109eabc6255188de91218` | Apache-2.0 | Small Qwen comparison target (15.26 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3-8B-DFlash-b16 (HF) | `huggingface.co/z-lab/Qwen3-8B-DFlash-b16` | `refs/heads/main` | `9b41424b7109f9c5413454f481b09a82b85333f4` | MIT | Paired DFlash draft checkpoint (1.95 GiB safetensors) for exact target `Qwen/Qwen3-8B`; do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3-4B (HF) | `huggingface.co/Qwen/Qwen3-4B` | `refs/heads/main` | `1cfa9a7208912126459214e8b04321603b3df60c` | Apache-2.0 | Smallest pinned Qwen comparison target (7.49 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3-4B-DFlash-b16 (HF) | `huggingface.co/z-lab/Qwen3-4B-DFlash-b16` | `refs/heads/main` | `b74e3a329c4d963783143b1e970d95b002be72bd` | MIT | Paired DFlash draft checkpoint (1.00 GiB safetensors) for exact target `Qwen/Qwen3-4B`; do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-4B (HF) | `huggingface.co/Qwen/Qwen3.5-4B` | `refs/heads/main` | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | Apache-2.0 | Small Qwen comparison target (8.68 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3.5-4B-DFlash (HF) | `huggingface.co/z-lab/Qwen3.5-4B-DFlash` | `refs/heads/main` | `96899cc270945f554998309580b08a04a05a3187` | MIT | Paired DFlash draft checkpoint (1.00 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3-Coder-Next-FP8 (HF) | `huggingface.co/Qwen/Qwen3-Coder-Next-FP8` | `refs/heads/main` | `da6e2ed27304dd39abadd9c82ef50e8de67bdd4c` | Apache-2.0 | Larger comparison target (74.86 GiB safetensors); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Qwen3-Coder-Next-DFlash (HF) | `huggingface.co/z-lab/Qwen3-Coder-Next-DFlash` | `refs/heads/main` | `6d741db11b89d7ea80a423b109f0424817ce8f1b` | MIT | Paired DFlash draft checkpoint (0.88 GiB safetensors); must match the exact target; do not download weights without human approval. |
| Qwen3-Coder-480B-A35B-Instruct-FP8 (HF) | `huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8` | `refs/heads/main` | `003f183a92fbe5b9a8325aaa8b2ae797c91dd90f` | Apache-2.0 | Reference-only target (449.04 GiB safetensors, not single-Spark plausible); do not download weights without human approval; see `docs/upstream-qwen-dflash.md`. |
| Ling-2.6-flash (HF) | `huggingface.co/inclusionAI/Ling-2.6-flash` | `refs/heads/main` | `9c861253ede654353d20bf1708182c81aab5f069` | MIT | Ling 2.6 Flash comparison target (200.23 GiB safetensors, not single-Spark plausible); do not download weights without human approval; see `docs/upstream-ling-2.6-flash.md`. |
| Ling-2.6-flash-fp8 (HF) | `huggingface.co/inclusionAI/Ling-2.6-flash-fp8` | `refs/heads/main` | `8bc416b60fe28be33303d57bb77dd826445a1eb1` | MIT | Ling 2.6 Flash FP8 target (101.48 GiB safetensors; single-Spark plausible but tight); do not download weights without human approval; see `docs/upstream-ling-2.6-flash.md`. |
| Ling-2.6-flash-int4 (HF) | `huggingface.co/inclusionAI/Ling-2.6-flash-int4` | `refs/heads/main` | `1bff63aa1f869e89499d52363790a119fd282edf` | MIT | Ling 2.6 Flash INT4 target (60.38 GiB safetensors; single-Spark plausible); do not download weights without human approval; see `docs/upstream-ling-2.6-flash.md`. |
| Ling-2.6-flash GGUF (ljupco, HF) | `huggingface.co/ljupco/Ling-2.6-flash-GGUF` | `refs/heads/main` | `5bdbd5ca603bd48488ccca06ec17e0e1312764f3` | Apache-2.0 | Community GGUF conversion used as Spark provenance for `Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf` (56.96 GiB); current pinned V4-capable llama.cpp forks reject `general.architecture=bailing_hybrid`, so keep this as target-only reference; do not download without human approval; see `docs/upstream-ling-2.6-flash.md`. |
| Gemma-4-26B-A4B-it (HF) | `huggingface.co/google/gemma-4-26B-A4B-it` | `refs/heads/main` | `462a98a12e28e2cbcfccaf78fe41e3e50235e6ae` | Apache-2.0 | Gemma 4 IT comparison target (48.07 GiB safetensors); do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Gemma-4-26B-A4B-it-DFlash (HF) | `huggingface.co/z-lab/gemma-4-26B-A4B-it-DFlash` | `refs/heads/main` | `77d4202772dfe50b2396ec7bac9cfffc7b9e7057` | Apache-2.0 | Paired DFlash draft checkpoint (0.80 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Gemma-4-31B-it (HF) | `huggingface.co/google/gemma-4-31B-it` | `refs/heads/main` | `ba74f5b6c647c0911554e50278d6f6f4477f9010` | Apache-2.0 | Gemma 4 IT comparison target (58.25 GiB safetensors); do not download weights without human approval; see `docs/upstream-dflash.md`. |
| Gemma-4-31B-it-DFlash (HF) | `huggingface.co/z-lab/gemma-4-31B-it-DFlash` | `refs/heads/main` | `eabd648301ce28583cc14757912e5e0f84e152e1` | Apache-2.0 | Paired DFlash draft checkpoint (2.86 GiB safetensors); must match the exact target; do not download weights without human approval; see `docs/upstream-dflash.md`. |
| SGLang | `sgl-project/sglang` | `refs/tags/v0.5.11` | `612785ffdcaf35552f1ed433a981d596ca9fe900` | Apache-2.0 | Serving runtime reference with explicit DeepSeek-V4 docs/cookbook; pinned to a release tag for reproducibility. |
| llama.cpp | `ggml-org/llama.cpp` | `refs/tags/b9110` | `ef22b3e4ac9444d1dca1c44164861e0317b5579d` | MIT | Spark-relevant baseline for CPU/GPU inference + ggml tooling (pinned to a release tag). |
| llama.cpp (DeepSeek V4 Flash fork) | `antirez/llama.cpp-deepseek-v4-flash` | `refs/heads/main` | `2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f` | MIT | Flash-specific fork widely referenced by community GGUFs; not in upstream `ggml-org/llama.cpp` yet. |
| llama.cpp (DeepSeek V4 support WIP) | `nisparks/llama.cpp` | `refs/heads/wip/deepseek-v4-support` | `9d364087024da141510267e6b269ee495ca45176` | MIT | WIP branch adding `F8_E4M3_B128` + `MXFP4` types + V4 loader/converter; required by some “native FP4/FP8” GGUF artifacts. |
| llama.cpp (DeepSeek V4 port fork) | `cchuter/llama.cpp` | `refs/heads/feat/v4-port` | `19b63dc368dfef6db6783e5ba3143927b7ed1c96` | MIT | V4-capable fork referenced by `teamblobfish/DeepSeek-V4-Flash-GGUF`; includes V4 loader + kernels not merged upstream. |
| llama.cpp (ssweens DeepSeek V4 fork) | `ssweens/llama.cpp-deepseek-v4` | `refs/heads/main` | `5b36105bae79a7127b39780c77ed22265d963f9a` | MIT | CUDA/ROCm/Vulkan fork used by `ssweens/DeepSeek-V4-Flash-GGUF-YMMV` (IQ1_M + IQ2_XXS); validate Spark compatibility (CC/SM121 + memory/KV behavior). |
| llama.cpp (CUDA Spark fork) | `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark` | `refs/heads/master` | `94073e2e2c1f7df4fa69642f39a8e7c69228e53b` | MIT | CUDA fork reported running on a single DGX Spark/GB10; provenance (report, 2026-05-05): `https://forums.developer.nvidia.com/t/deepseek-v4-flash-iq2xxs-on-a-single-gb10/368970`; validate perf + memory headroom on target Spark. |
| DeepSeek-V4-Flash (quantized safetensors, bleysg) | `huggingface.co/bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target` | `refs/heads/main` | `0cb3642b466e93bc30d83ff3f9afb122914e9645` | MIT | Community quantized safetensors snapshot (~82.34 GiB total); base_model is `deepseek-ai/DeepSeek-V4-Flash`; do not download without human approval; intended runtime is `Entrpi/ds4-spark-vllm` (pins in this manifest) which registers `--quantization deepseek_v4_hybrid_iq2`. |
| DeepSeek-V4-Flash GGUF (antirez) | `huggingface.co/antirez/deepseek-v4-gguf` | `refs/heads/main` | `c566ab6d7c696ddd0c7f124e115228af1a326824` | MIT | Single-file IQ2XXS GGUF (~80.8 GiB) tuned for `ds4` and used as single-Spark candidate; repo also publishes an optional MTP sidecar GGUF (~3.5 GiB); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (ssweens) | `huggingface.co/ssweens/DeepSeek-V4-Flash-GGUF-YMMV` | `refs/heads/main` | `e559a88dbceeed0e531257bbcdd66c3cc7359ddd` | MIT | GGUF pack includes `IQ1_M` (~62.9 GiB) + `IQ2_XXS` shards (~72.6 GiB) + `IQ3_XXS` shards (~104.2 GiB); also includes a BF16 GGUF (~150.7 GiB, not single-Spark plausible); requires V4-capable llama.cpp fork; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Preyazz) | `huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d` | MIT | Single-file Q2_K (~96 GiB) candidate; requires V4-capable llama.cpp fork (see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Preyazz Q8_0) | `huggingface.co/Preyazz/DeepSeek-V4-Flash-Q8_0-GGUF` | `refs/heads/main` | `066a35fd187293796317f61775b954bd1e5730dd` | MIT | Single-file Q8_0 GGUF (~281.6 GiB; not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (BatiAI) | `huggingface.co/batiai/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `70c9597f26a5b4747272477fff37986c4ce484ef` | MIT | Sharded GGUFs requiring `batiai/bati.cpp`; smallest quant listed is ~127 GB (not single-Spark plausible); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (lovedheart) | `huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `cd42deba41ac0536e68b125dfc367197b0ec3038` | UNKNOWN | No `LICENSE*` file detected at pinned commit (see `./scripts/upstream_license_probe.sh`); sharded Q2_K total ~93.6 GiB (single-Spark plausible but tight); README references llama.cpp PR `#22378` (closed; see `nisparks/llama.cpp` WIP); do not download without human approval. |
| DeepSeek-V4-Flash GGUF (native FP4/FP8) | `huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF` | `refs/heads/main` | `0b34e0b629c706396002496e795e9f910f7bf69f` | DeepSeek (link) | Single-file GGUF (~146 GB) 1:1 FP4/FP8 conversion; requires V4 loader + FP8/MXFP4 kernel support; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (abliterated) | `huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF` | `refs/heads/main` | `665c8e035e2602d12d28b84920808b158f337e09` | MIT | Experimental safety-research artifact; includes Q2_K (~99 GB) and Q8_0 (~302 GB) variants; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (teamblobfish) | `huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `3efdad27c080100655fe90b4b9b39224d0e300b4` | MIT | Sharded GGUF repo with multiple quant variants (IQ*/Q*); metadata-only fetch only; do not download weights without human approval. |
| DeepSeek-V4-Flash GGUF (asidaddy) | `huggingface.co/asidaddy/Deepseek-V4-Flash-GGUF` | `refs/heads/main` | `2c3a2233ec6492024ee1c90aa6a06ec22173d909` | MIT | Native conversion artifacts are ~145.4 GiB+ (not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (Volko76) | `huggingface.co/Volko76/DeepSeek-V4-Flash-GGUF` | `refs/heads/main` | `5f45ca7217f7b4e46e230e7c8bce3d3ff705555a` | MIT | Q2_K artifact is ~142.5 GiB (not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| DeepSeek-V4-Flash GGUF (setar007) | `huggingface.co/setar007/DeepSeek-V4-Flash-Q8xQ5-GGUF` | `refs/heads/main` | `3f779b75664c2a50a8d5f8ed31d17ed1efe2fe52` | MIT | Q8xQ5 sharded artifact totals ~184.7 GiB (not single-Spark plausible); keep as provenance reference only; do not download without human approval. |
| bati.cpp | `batiai/bati.cpp` | `refs/tags/v0.1.2` | `c7b64fe065164335b882e02a848fd4015b3c060a` | MIT | Early-access runtime referenced by `batiai/DeepSeek-V4-Flash-GGUF`; CUDA build path exists but is not yet validated on Spark. |
| Spark bring-up (pruned checkpoint) | `Mockingjay1316/deepseek-v4-flash-spark` | `refs/heads/master` | `08045f89d9716d3249ce834be1a1b1d91fd40859` | MIT | Single-Spark reference: prunes learned-router experts (example 256→128) and uses a streaming loader to avoid unified-memory OOM. |
| Spark bring-up (vLLM hybrid quant) | `Entrpi/ds4-spark-vllm` | `refs/heads/main` | `dab8c4c4a44111e686f516b747a7ffb161475943` | MIT | Single-Spark vLLM bring-up reference that applies ds4-style hybrid quant ideas to DeepSeek-V4-Flash; do not run without human-approved fixtures/weights. |
| Spark bring-up (native checkpoint runtime) | `bigs/deepseek-v4-flash-dgx-spark` | `refs/heads/main` | `4410e814a76a1a9d662576e2a35fa4a8965d2edc` | UNKNOWN | No `LICENSE*` file detected at pinned commit (see `./scripts/upstream_license_probe.sh`); research runtime + OpenAI-compatible server for native FP8/FP4 checkpoint layout on Spark; includes inspection + manifest tooling; do not run without human-approved fixtures/hardware time. |
| Spark bring-up (GB10 C++ runtime, MXFP4) | `devid791/dsv4-flash-gb10-runtime` | `refs/tags/v0.1.0` | `244cb11d3ee3adfd96bd0f95d6a91649af7af45d` | Apache-2.0 | Proof-of-life Spark/GB10 runtime that loads the official BF16 HF snapshot and quantizes routed experts to MXFP4 on the fly; requires a human-approved HF snapshot download (large disk footprint). Provenance (2026-05-05): `https://forums.developer.nvidia.com/t/deepseek-v4-flash-mxfp4-proof-of-life-on-a-single-gb10-gx10/369131`. |
| Blackwell/SGLang arch patch (reference) | `0xSero/deepseek-v4-flash-sm120` | `refs/heads/main` | `c2eac5a9b2b457881d69b1164d909e8beab9286e` | Apache-2.0 | SM120 patch for SGLang FlashMLA sparse-decode kernels; may inform SM121/Spark troubleshooting. |

## Fetching

Use [`scripts/fetch_upstreams.sh`](../scripts/fetch_upstreams.sh) to clone pinned refs into a local `upstreams/` directory (ignored by git). The script verifies that the checked-out commit matches the pinned `Commit` in this manifest. For Hugging Face repos, the script sets `GIT_LFS_SKIP_SMUDGE=1` so large weight blobs are not downloaded.

## Refreshing Pins

To see the current HEAD commits upstream (without cloning), run:

```bash
./scripts/upstream_ls_remote.sh
```

To print the current resolution of the **pinned** refs (without cloning), run:

```bash
./scripts/upstream_ls_remote.sh --pinned
```

To print both reports (HEAD + pinned), run:

```bash
./scripts/upstream_ls_remote.sh --all
```

To verify that the **pinned** refs/commits in this manifest still resolve upstream, run:

```bash
./scripts/upstream_verify_pins.sh
```

To probe for common `LICENSE*` files at pinned commits (without cloning), run:

```bash
./scripts/upstream_license_probe.sh
```

To discover new community Hugging Face GGUF candidates (metadata only; no downloads), run:

```bash
./scripts/upstream_hf_search.sh "DeepSeek-V4-Flash GGUF" --sort downloads --limit 50
```

To inspect the smallest GGUF files in a repo (metadata only; no downloads), run:

```bash
./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --limit 20
```

For sharded GGUF repos, use the grouped report to sum shard sizes:

```bash
./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --group-shards --limit 20
```

## Per-Upstream Notes

- [`docs/upstream-ds4.md`](upstream-ds4.md)
- [`docs/upstream-deepgemm.md`](upstream-deepgemm.md)
- [`docs/upstream-flashmla.md`](upstream-flashmla.md)
- [`docs/upstream-deepseek-v3.md`](upstream-deepseek-v3.md)
- [`docs/upstream-deepseek-v4-flash.md`](upstream-deepseek-v4-flash.md)
- [`docs/upstream-vllm-transformers.md`](upstream-vllm-transformers.md)
- [`docs/upstream-sglang.md`](upstream-sglang.md)
- [`docs/upstream-llama-cpp.md`](upstream-llama-cpp.md)
- [`docs/upstream-quantized-v4-flash.md`](upstream-quantized-v4-flash.md)
- [`docs/upstream-quantized-v4-flash-safetensors.md`](upstream-quantized-v4-flash-safetensors.md)
- [`docs/upstream-single-spark-v4-flash.md`](upstream-single-spark-v4-flash.md)
- [`docs/upstream-spark-v4-bringup.md`](upstream-spark-v4-bringup.md)
- [`docs/upstream-qwen-dflash.md`](upstream-qwen-dflash.md)
- [`docs/upstream-aeon-qwen36-dflash.md`](upstream-aeon-qwen36-dflash.md)
- [`docs/upstream-dflash.md`](upstream-dflash.md)
- [`docs/upstream-ling-2.6-flash.md`](upstream-ling-2.6-flash.md)
- [`docs/model-quality-speed.md`](model-quality-speed.md)
