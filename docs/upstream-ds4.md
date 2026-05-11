# Upstream: antirez/ds4

## Source

- Repo: `https://github.com/antirez/ds4`
- Ref: `refs/heads/main`
- Commit: `99a5c13ba82e05bd2e47a90cdf4825fc7840cf96`
- License: MIT (see upstream `LICENSE`)

## What it is

`ds4` is a DeepSeek-V4-Flash-specific inference engine (CLI + HTTP server), written as a narrow native implementation rather than a generic GGUF runtime. Upstream is Metal-first (macOS) and includes model-specific loading, prompt rendering, KV/cache logic, and validation harnesses.

## Why we track it

We track `ds4` as a compact reference point for:

- DeepSeek-V4-Flash execution semantics as implemented by a dedicated engine,
- KV-cache design choices (including disk-oriented cache ideas), and
- end-to-end ergonomics (CLI/server flags, test vectors, validation posture).

For the specific DeepSeek V4 Flash MTP draft/verify/rollback semantics and the `mtp.0.*` binding contract, see `docs/mtp-ds4-reference.md`.

This repo must not vendor large third-party trees or model weights: treat `ds4` as read-only reference material.

## Build notes (upstream)

- Build is Makefile-based (`make`); upstream builds `ds4` and `ds4-server` binaries.
- Upstream includes scripts that download large GGUF model artifacts from Hugging Face; do not run those download paths from this repo/intake process.

## Fetch

```bash
./scripts/fetch_upstreams.sh ds4
```
