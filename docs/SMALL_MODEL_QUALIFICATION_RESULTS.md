# Small Model Qualification Results

Batch timestamp: `2026-05-21T12:29:27.624219Z`
Hardware node: `spark2`
Records: `64` of `64` inventory entries
Failures: `27`
Wall clock seconds: `1261.945`

## Top 3 By Quality
- `gguf-mistralai-Ministral-3-3B-Instruct-2512-GGUF-Ministral-3-3B-Instruct-2512-Q4_K_M` pass_rate=1.0
- `gguf-mistralai-Ministral-3-8B-Instruct-2512-GGUF-Ministral-3-8B-Instruct-2512-Q5_K_M` pass_rate=1.0
- `gguf-mistralai-Ministral-3-14B-Instruct-2512-GGUF-Ministral-3-14B-Instruct-2512-BF16` pass_rate=1.0

## Top 3 By Mean Tok/s
- `ling-Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ` mean_tok_s=23.533306930194254
- `gguf-mistralai-Ministral-3-3B-Reasoning-2512-GGUF-Ministral-3-3B-Reasoning-2512-BF16-mmproj` mean_tok_s=9.851862641417803
- `gguf-mistralai-Ministral-3-8B-Instruct-2512-GGUF-Ministral-3-8B-Instruct-2512-BF16-mmproj` mean_tok_s=9.763635061820837

## Top 3 By Cost Proxy
- `smoke-stories15M-q4_0` cost_proxy=0.3
- `gguf-mistralai-Ministral-3-3B-Instruct-2512-GGUF-Ministral-3-3B-Instruct-2512-Q4_K_M` cost_proxy=3.0
- `gguf-mistralai-Ministral-3-3B-Instruct-2512-GGUF-Ministral-3-3B-Instruct-2512-BF16` cost_proxy=4.0

## Failed Or Unwired Models
- `hf-Qwen-Qwen3.5-0.8B`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-R1-Distill-Qwen-1.5B`: serve_backend transformers not wired for #1214 batch
- `hf-Qwen-Qwen3.5-2B`: serve_backend transformers not wired for #1214 batch
- `hf-Qwen-Qwen3.5-35B-A3B-GPTQ-Int4`: serve_backend transformers not wired for #1214 batch
- `hf-Qwen-Qwen3.6-35B-A3B-FP8`: serve_backend transformers not wired for #1214 batch
- `hf-moonshotai-Moonlight-16B-A3B-Instruct`: serve_backend transformers not wired for #1214 batch
- `hf-Qwen-Qwen3.5-4B`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-R1-Distill-Qwen-7B`: serve_backend transformers not wired for #1214 batch
- `hf-zai-org-SWE-Dev-7B`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-R1-0528-Qwen3-8B`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-R1-Distill-Llama-8B`: serve_backend transformers not wired for #1214 batch
- `hf-Qwen-Qwen3.5-9B`: serve_backend transformers not wired for #1214 batch
- `hf-zai-org-SWE-Dev-9B`: serve_backend transformers not wired for #1214 batch
- `hf-Qwen-Qwen3.5-122B-A10B-GPTQ-Int4`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-R1-Distill-Qwen-14B`: serve_backend transformers not wired for #1214 batch
- `hf-mistralai-Devstral-Small-2-24B-Instruct-2512`: serve_backend transformers not wired for #1214 batch
- `hf-Qwen-Qwen3.6-27B-FP8`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-R1-Distill-Qwen-32B`: serve_backend transformers not wired for #1214 batch
- `hf-zai-org-SWE-Dev-32B`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-V4-Flash`: serve_backend transformers not wired for #1214 batch
- `hf-deepseek-ai-DeepSeek-V4-Flash-inference`: serve_backend transformers not wired for #1214 batch
- `hf-microsoft-Phi-4-mini-flash-reasoning`: serve_backend transformers not wired for #1214 batch
- `hf-microsoft-Phi-4-mini-instruct`: serve_backend transformers not wired for #1214 batch
- `hf-microsoft-Phi-4-mini-reasoning`: serve_backend transformers not wired for #1214 batch
- `hf-microsoft-Phi-4-reasoning`: serve_backend transformers not wired for #1214 batch
- `hf-microsoft-phi-4`: serve_backend transformers not wired for #1214 batch
- `hf-zai-org-GLM-4.7-Flash`: serve_backend transformers not wired for #1214 batch
