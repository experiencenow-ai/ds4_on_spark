# Upstream: antirez/ds4

## Source

- Repo: `https://github.com/antirez/ds4`
- Ref: `refs/heads/main`
- Commit: `ed5d30dba0a1ef0f7fb863270df8f11df13653a4`
- License: MIT (see upstream `LICENSE`)

## What it is

`ds4` is a DeepSeek-V4-Flash-specific inference engine (CLI + HTTP server), written as a narrow native implementation rather than a generic GGUF runtime. Upstream now includes Metal and CUDA graph paths, model-specific loading, prompt rendering, KV/cache logic, and validation harnesses.

## Why we track it

We track `ds4` as a compact reference point for:

- DeepSeek-V4-Flash execution semantics as implemented by a dedicated engine,
- KV-cache design choices (including disk-oriented cache ideas), and
- end-to-end ergonomics (CLI/server flags, test vectors, validation posture).

As of the pinned commit, upstream publishes a DGX Spark GB10 q2 single-run
number in the README (`7047` prompt tokens, `343.81` prefill t/s, `13.75`
generation t/s). Treat this as an upstream claim until reproduced locally with
the same prompt/context/token settings and fixture hash.

For the specific DeepSeek V4 Flash MTP draft/verify/rollback semantics and the `mtp.0.*` binding contract, see `docs/mtp-ds4-reference.md`.

This repo must not vendor large third-party trees or model weights: treat `ds4` as read-only reference material.

## Build notes (upstream)

- Build is Makefile-based (`make`); upstream builds `ds4` and `ds4-server` binaries.
- On Linux/Spark, the optimized path is CUDA; on macOS, the optimized path is Metal.
- Upstream includes scripts that download large GGUF model artifacts from Hugging Face; do not run those download paths from this repo/intake process.
- `./download_model.sh q2`, `q2-imatrix`, and `q4` fetch main GGUF variants; `./download_model.sh mtp` fetches an optional MTP sidecar. Model downloads remain human-approved fixtures only.

## Spark comparison wrapper

Use the repo wrapper to compare upstream `ds4` against our current Spark
baselines without downloading weights:

```bash
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
DS4_DIR=/remote/path/to/ds4 \
MODEL_GGUF=/remote/path/to/ds4flash.gguf \
ALLOW_RUN=1 \
scripts/run_baseline_antirez_ds4_spark.sh spark0@aitopatom-9ab9.local
```

Use the same `PROMPT`, `CTX`, `N_TOKENS`, and thinking flags as the llama.cpp or
vLLM run you are comparing against. The wrapper records `decode_tps`,
`prefill_tps`, `ttft_s`, `total_wall_s`, and optional quality metadata into
`MODEL_RUNS_CSV`.

## Fetch

```bash
./scripts/fetch_upstreams.sh ds4
```
