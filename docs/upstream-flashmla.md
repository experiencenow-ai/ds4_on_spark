# Upstream: deepseek-ai/FlashMLA

## Source

- Repo: `https://github.com/deepseek-ai/FlashMLA`
- Ref: `refs/heads/main`
- Commit: `9241ae3ef9bac614dd25e45e507e089f888280e0`
- License: MIT (see upstream `LICENSE`)

## Why we track it

FlashMLA is an official DeepSeek kernel repo for “Multi-head Latent Attention” (MLA). Track it as a Spark GPU kernel reference point when comparing:

- attention-kernel design tradeoffs for MLA-style models, and
- what a plausible “official” kernel implementation looks like vs community ports.

## Build notes (upstream, high level)

- Treat as an out-of-tree reference; do not vendor the repo.
- Expect CUDA toolchain requirements and tight coupling to GPU architecture; validate on Spark only with explicit human approval.

## Fetch

```bash
./scripts/fetch_upstreams.sh flashmla
```
