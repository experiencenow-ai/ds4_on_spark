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
MODEL_RUNS_CSV="${MODEL_RUNS_CSV:-}"
PUBLIC_QUALITY_PRIOR="${PUBLIC_QUALITY_PRIOR:-}"
PUBLIC_QUALITY_BASIS="${PUBLIC_QUALITY_BASIS:-}"
PUBLIC_QUALITY_SOURCE="${PUBLIC_QUALITY_SOURCE:-}"
PASSED_TASKS="${PASSED_TASKS:-}"
TOTAL_TASKS="${TOTAL_TASKS:-}"
LOCAL_QUALITY_SCORE="${LOCAL_QUALITY_SCORE:-}"
QUALITY_SCORE="${QUALITY_SCORE:-}"


sh_quote()
{
    v="${1:-}"
    printf "'%s'" "$(printf %s "$v" | sed "s/'/'\\''/g")"
}

if [ "${REMOTE_LLAMA_ENV:-}" = "" ]; then
    REMOTE_LLAMA_ENV="ALLOW_RUN=$(sh_quote "$ALLOW_RUN") RUNTIME_LABEL=$(sh_quote "$RUNTIME_LABEL") MODEL_SOURCE=$(sh_quote "$MODEL_SOURCE") MODEL_QUANT=$(sh_quote "$MODEL_QUANT") MODEL_GGUF=$(sh_quote "$MODEL_GGUF") LLAMA_CLI=$(sh_quote "$LLAMA_CLI") CTX=$(sh_quote "$CTX") N_TOKENS=$(sh_quote "$N_TOKENS") N_GPU_LAYERS=$(sh_quote "$N_GPU_LAYERS") GPU_SAMPLE=$(sh_quote "$GPU_SAMPLE") GPU_SAMPLE_INTERVAL_S=$(sh_quote "$GPU_SAMPLE_INTERVAL_S")"
    if [ "${PROMPT:-}" != "" ]; then
        REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV PROMPT=$(sh_quote "$PROMPT")"
    fi
    if [ "${EXTRA_ARGS:-}" != "" ]; then
        REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV EXTRA_ARGS=$(sh_quote "$EXTRA_ARGS")"
    fi
fi

SPARK_INVENTORY="$SPARK_INVENTORY" MODEL_RUNS_CSV="$MODEL_RUNS_CSV" PUBLIC_QUALITY_PRIOR="$PUBLIC_QUALITY_PRIOR" PUBLIC_QUALITY_BASIS="$PUBLIC_QUALITY_BASIS" PUBLIC_QUALITY_SOURCE="$PUBLIC_QUALITY_SOURCE" PASSED_TASKS="$PASSED_TASKS" TOTAL_TASKS="$TOTAL_TASKS" LOCAL_QUALITY_SCORE="$LOCAL_QUALITY_SCORE" QUALITY_SCORE="$QUALITY_SCORE" REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV" scripts/run_baseline_existing_runtime.sh "$target"
