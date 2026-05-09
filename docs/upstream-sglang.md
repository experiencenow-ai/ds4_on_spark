# Upstream: SGLang (DeepSeek-V4 serving reference)

SGLang is a high-performance serving framework that includes explicit DeepSeek-V4 guidance and runtime hooks. We track it as a **Spark-relevant serving-runtime reference** alongside vLLM/Transformers.

- Repo: `https://github.com/sgl-project/sglang`
- Ref: `refs/heads/main`
- Commit: `b735ca178c9c60ed5f66a3c5428212a7b02a17c4`
- License: Apache-2.0 (see upstream `LICENSE`)

## Why we track it

- DeepSeek-V4 docs exist in-repo at the pinned commit (example: `docs_new/cookbook/autoregressive/DeepSeek/DeepSeek-V4.mdx`).
- The upstream container build flow explicitly references FlashMLA for DeepSeek‑V4 kernels (example: `docker/Dockerfile` contains a DeepSeek‑V4 note and clones `deepseek-ai/FlashMLA`).
- It provides a second “serving stack” viewpoint (in addition to vLLM) for troubleshooting model config/packing, KV/cache sizing, and DeepSeek‑specific runtime details.

## Fetch / build notes (no weights)

- Fetch the pinned source (code only; no weights):

```bash
./scripts/fetch_upstreams.sh sglang
```

- This repo’s automation loop does **not** run SGLang builds or GPU tests; treat upstream as a reference unless a human approves Spark time + fixtures.
