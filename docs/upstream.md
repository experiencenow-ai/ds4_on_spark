# Upstream

> Supersedes: `docs/upstream-quantized-v4-flash-safetensors.md`, `docs/upstream-manifest.md`, `docs/upstream-deepseek-v4-flash.md`, `docs/upstream-deepgemm.md`, `docs/upstream-qwen-dflash.md`, `docs/upstream-aeon-qwen36-dflash.md`, `docs/upstream-deepseek-v3.md`, `docs/upstream-llama-cpp.md`, `docs/upstream-spark-v4-bringup.md`, `docs/upstream-quantized-v4-flash.md`, `docs/upstream-dflash.md`, `docs/upstream-single-spark-v4-flash.md`, `docs/upstream-vllm-transformers.md`, `docs/upstream-flashinfer.md`, `docs/upstream-ds4.md`, `docs/upstream-sglang.md`, `docs/upstream-flashmla.md`, `docs/upstream-ling-2.6-flash.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 18 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `upstream-quantized-v4-flash-safetensors.md`: Upstream: DeepSeek-V4-Flash quantized candidates (safetensors) (52 lines).
- `upstream-manifest.md`: Upstream Manifest (184 lines).
- `upstream-deepseek-v4-flash.md`: Upstream: DeepSeek-V4-Flash (official configs) (186 lines).
- `upstream-deepgemm.md`: Upstream: deepseek-ai/DeepGEMM (38 lines).
- `upstream-qwen-dflash.md`: Upstream: model comparison candidates (263 lines).
- `upstream-aeon-qwen36-dflash.md`: Upstream: AEON-7 Qwen3.6 27B DFlash On DGX Spark (178 lines).
- `upstream-deepseek-v3.md`: Upstream: deepseek-ai/DeepSeek-V3 (24 lines).
- `upstream-llama-cpp.md`: Upstream: ggml-org/llama.cpp (111 lines).
- `upstream-spark-v4-bringup.md`: Upstreams: Spark bring-up references (DeepSeek-V4-Flash) (78 lines).
- `upstream-quantized-v4-flash.md`: Upstream: DeepSeek-V4-Flash quantized single-Spark candidates (GGUF) (311 lines).
- `upstream-dflash.md`: Upstream: DFlash candidate pairs (non-Qwen) (91 lines).
- `upstream-single-spark-v4-flash.md`: Single-Spark DeepSeek-V4-Flash: runtime + artifact candidate matrix (93 lines).
- `upstream-vllm-transformers.md`: Upstreams: vLLM + Transformers (84 lines).
- `upstream-flashinfer.md`: Upstream: flashinfer-ai/flashinfer (28 lines).
- `upstream-ds4.md`: Upstream: antirez/ds4 (70 lines).
- `upstream-sglang.md`: Upstream: SGLang (DeepSeek-V4 serving reference) (55 lines).
- `upstream-flashmla.md`: Upstream: deepseek-ai/FlashMLA (30 lines).
- `upstream-ling-2.6-flash.md`: Upstream: Ling 2.6 Flash (comparison targets) (65 lines).

## Command Inventory

- `upstream-quantized-v4-flash-safetensors.md`: `./scripts/upstream_hf_api_report.sh bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target`
- `upstream-quantized-v4-flash-safetensors.md`: `./scripts/upstream_hf_api_report.sh bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target --sum-safetensors`
- `upstream-manifest.md`: `./scripts/upstream_ls_remote.sh`
- `upstream-manifest.md`: `./scripts/upstream_ls_remote.sh --pinned`
- `upstream-manifest.md`: `./scripts/upstream_ls_remote.sh --all`
- `upstream-manifest.md`: `./scripts/upstream_verify_pins.sh`
- `upstream-manifest.md`: `./scripts/upstream_license_probe.sh`
- `upstream-manifest.md`: `./scripts/upstream_hf_search.sh "DeepSeek-V4-Flash GGUF" --sort downloads --limit 50`
- `upstream-manifest.md`: `./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --limit 20`
- `upstream-manifest.md`: `./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --group-shards --limit 20`
- `upstream-deepseek-v4-flash.md`: `./scripts/upstream_hf_api_report.sh deepseek-ai/DeepSeek-V4-Flash --sum-safetensors`
- `upstream-deepseek-v4-flash.md`: `./scripts/upstream_hf_api_report.sh deepseek-ai/DeepSeek-V4-Flash-Base --sum-safetensors`
- `upstream-deepseek-v4-flash.md`: `./scripts/upstream_hf_api_report.sh sgl-project/DeepSeek-V4-Flash-FP8 --sum-safetensors`
- `upstream-deepseek-v4-flash.md`: `./scripts/upstream_hf_api_report.sh deepseek-ai/DeepSeek-V4-Flash`
- `upstream-deepseek-v4-flash.md`: `git ls-remote https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash refs/heads/main`
- `upstream-deepseek-v4-flash.md`: `./scripts/upstream_feature_probe.sh --fetch`
- `upstream-deepseek-v4-flash.md`: `./scripts/fetch_upstreams.sh deepseek_v4_flash_hf_pr14`
- `upstream-deepseek-v4-flash.md`: `./scripts/fetch_upstreams.sh deepseek_v4_flash_hf_pr16`
- `upstream-deepseek-v4-flash.md`: `./scripts/fetch_upstreams.sh deepseek_v4_flash_hf_pr18`
- `upstream-deepseek-v4-flash.md`: `./scripts/fetch_upstreams.sh deepseek_v4_flash_hf`
- `upstream-deepseek-v4-flash.md`: `./scripts/fetch_upstreams.sh deepseek_v4_flash_base_hf`
- `upstream-deepgemm.md`: `./scripts/fetch_upstreams.sh deepgemm`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh Qwen/Qwen3.6-35B-A3B-FP8`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh Qwen/Qwen3.6-35B-A3B-FP8 --sum-safetensors`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh spiritbuun/Qwen3.5-27B-DFlash-GGUF --sum-gguf`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh spiritbuun/Qwen3.6-27B-DFlash-GGUF --sum-gguf`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh Lucebox/Qwen3.6-27B-DFlash-GGUF --sum-gguf`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh Ardenzard/Qwen3.6-27B-DFlash-GGUF --sum-gguf`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh starskyzheng/Qwen3.6-35B-DFlash-GGUF --sum-gguf`
- `upstream-qwen-dflash.md`: `./scripts/upstream_hf_api_report.sh abhinand/Qwen3.6-35B-A3B-DFlash-GGUF --sum-gguf`
- `upstream-aeon-qwen36-dflash.md`: `curl -s http://localhost:8000/metrics | grep -E 'spec_decode|draft_acceptance|dflash' || true`
- `upstream-deepseek-v3.md`: `./scripts/fetch_upstreams.sh deepseek_v3`
- `upstream-llama-cpp.md`: `./scripts/fetch_upstreams.sh llama_cpp`
- `upstream-llama-cpp.md`: `./scripts/fetch_upstreams.sh llama_cpp_deepseek_v4_flash`
- `upstream-llama-cpp.md`: `./scripts/fetch_upstreams.sh llama_cpp_deepseek_v4_support_wip`
- `upstream-llama-cpp.md`: `./scripts/fetch_upstreams.sh llama_cpp_deepseek_v4_port_cchuter`
- `upstream-llama-cpp.md`: `./scripts/fetch_upstreams.sh llama_cpp_deepseek_v4_ssweens`
- `upstream-llama-cpp.md`: `./scripts/fetch_upstreams.sh llama_cpp_cuda_spark`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_search.sh "DeepSeek-V4-Flash GGUF" --sort downloads --limit 50`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_api_report.sh <org>/<repo> --sum-gguf`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_api_report.sh <org>/<repo> --top-oids 50 | rg '\\.gguf$'`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --limit 20`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_smallest_gguf.sh <org>/<repo> --group-shards --limit 20`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_spark_gguf_candidates.sh "DeepSeek-V4-Flash GGUF" --limit 50 --sort downloads --max-gib 110`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_spark_gguf_candidates.sh "DeepSeek-V4-Flash GGUF" --limit 50 --sort downloads --max-gib 110 --require-base-model deepseek-ai/DeepSeek-V4-Flash`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_api_report.sh <org>/<repo> | rg -n '^(base_model|license|sha):'`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_api_report.sh antirez/deepseek-v4-gguf --top-oids 50 | rg '\\.gguf$'`
- `upstream-quantized-v4-flash.md`: `./scripts/fetch_upstreams.sh deepseek_v4_gguf_preyazz`
- `upstream-quantized-v4-flash.md`: `./scripts/upstream_hf_pointer_report.sh deepseek_v4_gguf_preyazz`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh openai/gpt-oss-20b --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh z-lab/gpt-oss-20b-DFlash --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh meta-llama/Llama-3.1-8B-Instruct --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh z-lab/LLaMA3.1-8B-Instruct-DFlash-UltraChat --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh openai/gpt-oss-120b --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh z-lab/gpt-oss-120b-DFlash --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh google/gemma-4-26B-A4B-it --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh z-lab/gemma-4-26B-A4B-it-DFlash --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh google/gemma-4-31B-it --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh z-lab/gemma-4-31B-it-DFlash --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh MiniMaxAI/MiniMax-M2.7 --sum-safetensors`
- `upstream-dflash.md`: `./scripts/upstream_hf_api_report.sh z-lab/MiniMax-M2.7-DFlash --sum-safetensors`
- `upstream-single-spark-v4-flash.md`: `./scripts/upstream_hf_api_report.sh deepseek-ai/DeepSeek-V4-Flash --sum-safetensors`
- `upstream-single-spark-v4-flash.md`: `./scripts/upstream_hf_api_report.sh deepseek-ai/DeepSeek-V4-Flash-Base --sum-safetensors`
- `upstream-single-spark-v4-flash.md`: `DS4_DIR=/remote/path/to/ds4 \`
- `upstream-vllm-transformers.md`: `./scripts/fetch_upstreams.sh vllm`
- `upstream-vllm-transformers.md`: `./scripts/fetch_upstreams.sh transformers`
- `upstream-flashinfer.md`: `./scripts/fetch_upstreams.sh flashinfer`
- `upstream-ds4.md`: `DS4_DIR=/remote/path/to/ds4 \`
- `upstream-ds4.md`: `./scripts/fetch_upstreams.sh ds4`
- `upstream-sglang.md`: `./scripts/fetch_upstreams.sh sglang`
- `upstream-flashmla.md`: `./scripts/fetch_upstreams.sh flashmla`
- `upstream-ling-2.6-flash.md`: `./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-int4`
- `upstream-ling-2.6-flash.md`: `./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-int4 --sum-safetensors`
- `upstream-ling-2.6-flash.md`: `./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash-fp8 --sum-safetensors`
- `upstream-ling-2.6-flash.md`: `./scripts/upstream_hf_api_report.sh inclusionAI/Ling-2.6-flash --sum-safetensors`
- `upstream-ling-2.6-flash.md`: `./scripts/upstream_hf_api_report.sh ljupco/Ling-2.6-flash-GGUF`
- `upstream-ling-2.6-flash.md`: `./scripts/upstream_hf_smallest_gguf.sh ljupco/Ling-2.6-flash-GGUF --group-shards --limit 20`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/upstream-quantized-v4-flash-safetensors.md` | 52 | Upstream: DeepSeek-V4-Flash quantized candidates (safetensors) | Candidate: bleysg/DeepSeek-V4-Flash-IQ2XXS-Q2K-FP8-120GB-target, Source, Footprint (HF API, no downloads), Quantization config (from `config.json`, metadata-only clone), Runtime status (single Spark) |
| `docs/upstream-manifest.md` | 184 | Upstream Manifest | Canonical Upstreams (Pinned), Fetching, Refreshing Pins, Per-Upstream Notes |
| `docs/upstream-deepseek-v4-flash.md` | 186 | Upstream: DeepSeek-V4-Flash (official configs) | Sources, Related official kernel repos (reference), What we read from HF (no weights), Public quality prior (model card, metadata-only), Weight footprint (HF API, no downloads) |
| `docs/upstream-deepgemm.md` | 38 | Upstream: deepseek-ai/DeepGEMM | Source, Why we track it, Pinning notes, Build notes (upstream, summarized), Fetch |
| `docs/upstream-qwen-dflash.md` | 263 | Upstream: model comparison candidates | Core Comparison Matrix, FP8-packaged 27B targets (target-only), Model-card Requirements (DFlash), Metadata Commands (No Downloads), DFlash Expansion Candidates |
| `docs/upstream-aeon-qwen36-dflash.md` | 178 | Upstream: AEON-7 Qwen3.6 27B DFlash On DGX Spark | Sources And Attribution, Most Useful Takeaways, AEON Public Performance Signal, Spark Runtime Recipe To Test Locally, Benchmarking Added Here |
| `docs/upstream-deepseek-v3.md` | 24 | Upstream: deepseek-ai/DeepSeek-V3 | Source, Why we track it, Fetch |
| `docs/upstream-llama-cpp.md` | 111 | Upstream: ggml-org/llama.cpp | Source, Why we track it (Spark relevance), Additional Spark references, DeepSeek-V4-Flash-specific forks (Spark relevance), DeepSeek V4 Flash MTP sidecar (Spark forks) |
| `docs/upstream-spark-v4-bringup.md` | 78 | Upstreams: Spark bring-up references (DeepSeek-V4-Flash) | Mockingjay1316/deepseek-v4-flash-spark (single Spark prune + loader), Entrpi/ds4-spark-vllm (single Spark vLLM hybrid-quant bring-up), bigs/deepseek-v4-flash-dgx-spark (native checkpoint runtime experiments), devid791/dsv4-flash-gb10-runtime (MXFP4 proof-of-life on GB10/GX10), 0xSero/deepseek-v4-flash-sm120 (Blackwell/SGLang kernel patch) |
| `docs/upstream-quantized-v4-flash.md` | 311 | Upstream: DeepSeek-V4-Flash quantized single-Spark candidates (GGUF) | Discovery (HF search, no downloads), Single-Spark memory baseline (Spark0), Candidates (pinned), Not single-Spark plausible (still DeepSeek-V4-Flash), Reproducing the size numbers (no downloads) |
| `docs/upstream-dflash.md` | 91 | Upstream: DFlash candidate pairs (non-Qwen) | Candidate Matrix, Public quality prior (metadata-only pointers), Model-card requirements (DFlash), Metadata commands (no downloads) |
| `docs/upstream-single-spark-v4-flash.md` | 93 | Single-Spark DeepSeek-V4-Flash: runtime + artifact candidate matrix | Memory baseline (Spark0), Candidates (GGUF path), Candidates (native checkpoint path), Candidates (quantized safetensors snapshots), What this repo should do next (intake posture) |
| `docs/upstream-vllm-transformers.md` | 84 | Upstreams: vLLM + Transformers | vLLM, Transformers |
| `docs/upstream-flashinfer.md` | 28 | Upstream: flashinfer-ai/flashinfer | Source, Why we track it (Spark relevance), Notes / guardrails, Fetch |
| `docs/upstream-ds4.md` | 70 | Upstream: antirez/ds4 | Source, Notable upstream delta (since previous pin), What it is, Why we track it, Build notes (upstream) |
| `docs/upstream-sglang.md` | 55 | Upstream: SGLang (DeepSeek-V4 serving reference) | Why we track it, Fetch / build notes (no weights), Provider probe status, DFlash model-card PR pin (reference) |
| `docs/upstream-flashmla.md` | 30 | Upstream: deepseek-ai/FlashMLA | Source, Why we track it, Build notes (upstream, high level), Fetch |
| `docs/upstream-ling-2.6-flash.md` | 65 | Upstream: Ling 2.6 Flash (comparison targets) | Targets (HF, pinned), Community GGUF (Spark provenance, pinned), DFlash status, Public quality prior (model card, metadata-only), Metadata commands (no downloads) |
