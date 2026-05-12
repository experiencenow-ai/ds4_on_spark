#!/usr/bin/env sh
set -eu

# Spark0 vLLM environment probe (no model downloads, no generation by default).
# This is a preflight check for Ling/Qwen/DFlash runs that depend on vLLM.

target="${1:-spark0@aitopatom-9ab9.local}"

RUN_LABEL="${RUN_LABEL:-vllm-env-probe}"
OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"

# Keep this probe metadata-only unless a human explicitly opts into generation.
REMOTE_VLLM_ENV="${REMOTE_VLLM_ENV:-ALLOW_RUN=0}"

OUT_ROOT="$OUT_ROOT" RUN_LABEL="$RUN_LABEL" SKIP_GGUF_INSPECT=1 SKIP_LLAMA=1 SKIP_MTP_SIDECAR=1 REMOTE_VLLM_ENV="$REMOTE_VLLM_ENV" scripts/run_baseline_existing_runtime.sh "$target"

