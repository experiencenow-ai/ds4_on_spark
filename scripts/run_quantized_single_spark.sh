#!/usr/bin/env sh
set -eu

# Quantized single-Spark milestone wrapper.
# This does not fetch weights or build runtimes; it only sets the canonical low-cost run shape.

target="${1:-spark0@aitopatom-9ab9.local}"

if [ "${MODEL_GGUF:-}" = "" ]; then
    echo "MODEL_GGUF=/abs/path/to/model.gguf is required" >&2
    exit 2
fi
if [ "${LLAMA_CLI:-}" = "" ]; then
    echo "LLAMA_CLI=/abs/path/to/v4-capable/llama-cli is required" >&2
    exit 3
fi

ALLOW_RUN="${ALLOW_RUN:-1}"
RUNTIME_LABEL="${RUNTIME_LABEL:-v4-capable-llama}"
MODEL_SOURCE="${MODEL_SOURCE:-unknown}"
MODEL_QUANT="${MODEL_QUANT:-unknown}"
CTX="${CTX:-2048}"
N_TOKENS="${N_TOKENS:-32}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
GPU_SAMPLE="${GPU_SAMPLE:-1}"
GPU_SAMPLE_INTERVAL_S="${GPU_SAMPLE_INTERVAL_S:-1}"
SPARK_INVENTORY="${SPARK_INVENTORY:-0}"

REMOTE_LLAMA_ENV="${REMOTE_LLAMA_ENV:-ALLOW_RUN=$ALLOW_RUN RUNTIME_LABEL=$RUNTIME_LABEL MODEL_SOURCE=$MODEL_SOURCE MODEL_QUANT=$MODEL_QUANT MODEL_GGUF=$MODEL_GGUF LLAMA_CLI=$LLAMA_CLI CTX=$CTX N_TOKENS=$N_TOKENS N_GPU_LAYERS=$N_GPU_LAYERS GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S}"

SPARK_INVENTORY="$SPARK_INVENTORY" REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV" scripts/run_baseline_existing_runtime.sh "$target"
