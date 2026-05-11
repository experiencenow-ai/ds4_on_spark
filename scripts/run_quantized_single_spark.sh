#!/usr/bin/env sh
set -eu

# Quantized single-Spark milestone wrapper.
# This does not fetch weights or build runtimes; it only sets the canonical low-cost run shape.

target="${1:-spark0@aitopatom-9ab9.local}"

SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

MODEL_GGUF_GLOB="${MODEL_GGUF_GLOB:-}"
MODEL_GGUF_EXCLUDE_EGREP="${MODEL_GGUF_EXCLUDE_EGREP:-MTP|DFlash|dflash|draft|sidecar}"

resolve_model_gguf()
{
    if [ "${MODEL_GGUF:-}" != "" ]; then
        return 0
    fi
    if [ "$MODEL_GGUF_GLOB" = "" ]; then
        echo "MODEL_GGUF=/abs/path/to/model.gguf is required (or set MODEL_GGUF_GLOB=/remote/path/*.gguf to auto-select the smallest staged trunk artifact)" >&2
        exit 2
    fi
    echo "resolving MODEL_GGUF from remote glob (no downloads): $MODEL_GGUF_GLOB" >&2
    MODEL_GGUF="$(ssh $SSH_OPTS "$target" "set -eu; best_path=\"\"; best_size=\"\"; for f in $MODEL_GGUF_GLOB; do [ -r \"\\$f\" ] || continue; b=\"\\$(basename \"\\$f\")\"; if echo \"\\$b\" | egrep -qi \"${MODEL_GGUF_EXCLUDE_EGREP}\"; then continue; fi; sz=\"\\$(wc -c <\"\\$f\" 2>/dev/null || echo 0)\"; case \"\\$sz\" in ''|*[!0-9]*) sz=0;; esac; if [ \"\\$sz\" -le 0 ]; then continue; fi; if [ \"\\$best_size\" = \"\" ] || [ \"\\$sz\" -lt \"\\$best_size\" ]; then best_size=\"\\$sz\"; best_path=\"\\$f\"; fi; done; if [ \"\\$best_path\" = \"\" ]; then echo \"no readable gguf candidates under glob (after exclude regex): $MODEL_GGUF_GLOB\" >&2; exit 11; fi; printf %s \"\\$best_path\"")"
    if [ "$MODEL_GGUF" = "" ]; then
        echo "failed to resolve MODEL_GGUF from $MODEL_GGUF_GLOB" >&2
        exit 2
    fi
    export MODEL_GGUF
    echo "resolved MODEL_GGUF=$MODEL_GGUF" >&2
}

resolve_model_gguf
if [ "${LLAMA_CLI:-}" = "" ]; then
    echo "LLAMA_CLI=/abs/path/to/v4-capable/llama-cli is required" >&2
    exit 3
fi

ALLOW_RUN="${ALLOW_RUN:-1}"
ALLOW_MODEL_INSPECT="${ALLOW_MODEL_INSPECT:-1}"
RUNTIME_LABEL="${RUNTIME_LABEL:-v4-capable-llama}"
MODEL_SOURCE="${MODEL_SOURCE:-unknown}"
MODEL_QUANT="${MODEL_QUANT:-unknown}"
LLAMA_DIR="${LLAMA_DIR:-}"
CTX="${CTX:-512}"
N_TOKENS="${N_TOKENS:-8}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
GPU_SAMPLE="${GPU_SAMPLE:-1}"
GPU_SAMPLE_INTERVAL_S="${GPU_SAMPLE_INTERVAL_S:-1}"
SPARK_INVENTORY="${SPARK_INVENTORY:-0}"
MODEL_RUNS_CSV="${MODEL_RUNS_CSV:-}"
LLAMA_SCOPE="${LLAMA_SCOPE:-deepseek_v4_flash}"
LLAMA_FATTN_PATCH_PROBE="${LLAMA_FATTN_PATCH_PROBE:-1}"
LLAMA_MULTISLOT_PATCH_PROBE="${LLAMA_MULTISLOT_PATCH_PROBE:-1}"
SKIP_MTP_SIDECAR="${SKIP_MTP_SIDECAR:-1}"
SKIP_VLLM="${SKIP_VLLM:-1}"
PUBLIC_QUALITY_PRIOR="${PUBLIC_QUALITY_PRIOR:-}"
PUBLIC_QUALITY_BASIS="${PUBLIC_QUALITY_BASIS:-}"
PUBLIC_QUALITY_SOURCE="${PUBLIC_QUALITY_SOURCE:-}"
PASSED_TASKS="${PASSED_TASKS:-}"
TOTAL_TASKS="${TOTAL_TASKS:-}"
LOCAL_QUALITY_SCORE="${LOCAL_QUALITY_SCORE:-}"
QUALITY_SCORE="${QUALITY_SCORE:-}"

if [ "$LLAMA_DIR" = "" ]; then
    case "$LLAMA_CLI" in
        */build*/bin/*)
            LLAMA_DIR="$(dirname "$(dirname "$(dirname "$LLAMA_CLI")")")"
            ;;
    esac
fi


sh_quote()
{
    v="${1:-}"
    printf "'%s'" "$(printf %s "$v" | sed "s/'/'\\''/g")"
}

if [ "${REMOTE_LLAMA_ENV:-}" = "" ]; then
    REMOTE_LLAMA_ENV="ALLOW_RUN=$(sh_quote "$ALLOW_RUN") ALLOW_MODEL_INSPECT=$(sh_quote "$ALLOW_MODEL_INSPECT") RUNTIME_LABEL=$(sh_quote "$RUNTIME_LABEL") MODEL_SOURCE=$(sh_quote "$MODEL_SOURCE") MODEL_QUANT=$(sh_quote "$MODEL_QUANT") MODEL_GGUF=$(sh_quote "$MODEL_GGUF") LLAMA_CLI=$(sh_quote "$LLAMA_CLI") CTX=$(sh_quote "$CTX") N_TOKENS=$(sh_quote "$N_TOKENS") N_GPU_LAYERS=$(sh_quote "$N_GPU_LAYERS") GPU_SAMPLE=$(sh_quote "$GPU_SAMPLE") GPU_SAMPLE_INTERVAL_S=$(sh_quote "$GPU_SAMPLE_INTERVAL_S")"
    if [ "${PROMPT:-}" != "" ]; then
        REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV PROMPT=$(sh_quote "$PROMPT")"
    fi
    if [ "${EXTRA_ARGS:-}" != "" ]; then
        REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV EXTRA_ARGS=$(sh_quote "$EXTRA_ARGS")"
	fi
fi

LLAMA_DIR="$LLAMA_DIR" LLAMA_FATTN_PATCH_PROBE="$LLAMA_FATTN_PATCH_PROBE" LLAMA_MULTISLOT_PATCH_PROBE="$LLAMA_MULTISLOT_PATCH_PROBE" SKIP_MTP_SIDECAR="$SKIP_MTP_SIDECAR" SKIP_VLLM="$SKIP_VLLM" SPARK_INVENTORY="$SPARK_INVENTORY" MODEL_RUNS_CSV="$MODEL_RUNS_CSV" LLAMA_SCOPE="$LLAMA_SCOPE" PUBLIC_QUALITY_PRIOR="$PUBLIC_QUALITY_PRIOR" PUBLIC_QUALITY_BASIS="$PUBLIC_QUALITY_BASIS" PUBLIC_QUALITY_SOURCE="$PUBLIC_QUALITY_SOURCE" PASSED_TASKS="$PASSED_TASKS" TOTAL_TASKS="$TOTAL_TASKS" LOCAL_QUALITY_SCORE="$LOCAL_QUALITY_SCORE" QUALITY_SCORE="$QUALITY_SCORE" REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV" scripts/run_baseline_existing_runtime.sh "$target"
