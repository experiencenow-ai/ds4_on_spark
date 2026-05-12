#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

MODEL_SOURCE="${MODEL_SOURCE:-}"
MODEL_QUANT="${MODEL_QUANT:-}"
MODEL_GGUF="${MODEL_GGUF:-}"
MODEL_GGUF_GLOB="${MODEL_GGUF_GLOB:-}"
MODEL_GGUF_EXCLUDE_EGREP="${MODEL_GGUF_EXCLUDE_EGREP:-MTP|DFlash|draft|sidecar}"
MODEL_GGUF_INCLUDE_EGREP="${MODEL_GGUF_INCLUDE_EGREP:-}"
LLAMA_CLI="${LLAMA_CLI:-}"
RUNTIME_LABEL="${RUNTIME_LABEL:-v4flash-external}"
CTX="${CTX:-512}"
N_TOKENS="${N_TOKENS:-8}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"
RUN_LABEL="${RUN_LABEL:-}"
MODEL_RUNS_CSV="${MODEL_RUNS_CSV:-}"
LLAMA_SCOPE="${LLAMA_SCOPE:-deepseek_v4_flash}"

SKIP_MTP_SIDECAR="${SKIP_MTP_SIDECAR:-1}"
SKIP_VLLM="${SKIP_VLLM:-1}"
SKIP_LLAMA="${SKIP_LLAMA:-0}"
SKIP_GGUF_INSPECT="${SKIP_GGUF_INSPECT:-0}"

LLAMA_FATTN_PATCH_PROBE="${LLAMA_FATTN_PATCH_PROBE:-1}"
LLAMA_MULTISLOT_PATCH_PROBE="${LLAMA_MULTISLOT_PATCH_PROBE:-1}"
FETCH_LLAMA_OUT_DIR="${FETCH_LLAMA_OUT_DIR:-0}"

quote_sh()
{
    v="${1:-}"
    printf "'%s'" "$(printf %s "$v" | sed "s/'/'\\\\\\\\''/g")"
}

infer_llama_dir()
{
    p="${1:-}"
    if [ "$p" = "" ]; then
        return 0
    fi
    # Expected: /abs/path/to/llama.cpp/build*/bin/llama-cli
    printf %s "$p" | sed -E 's:/build[^/]*/bin/llama-cli$::'
}

remote_select_model_gguf()
{
    glob="${1:-}"
    exclude_re="${2:-}"
    include_re="${3:-}"
    if [ "$glob" = "" ]; then
        return 0
    fi
    # Avoid quote injection by passing the glob/regex as positional args to `sh -lc`.
    # Note: `sh -c <script> arg0 arg1 arg2 ...` maps arg1->"$1", arg2->"$2", etc.
    ssh $SSH_OPTS "$target" "sh -lc 'set -eu; glob=\"\$1\"; exclude_re=\"\$2\"; include_re=\"\$3\"; best_path=\"\"; best_size=\"\"; for f in \$glob; do [ -r \"\$f\" ] || continue; base=\"\${f##*/}\"; if [ \"\$exclude_re\" != \"\" ] && printf %s \"\$base\" | grep -Eiq \"\$exclude_re\"; then continue; fi; if [ \"\$include_re\" != \"\" ] && ! printf %s \"\$base\" | grep -Eiq \"\$include_re\"; then continue; fi; sz=\$(stat -c %s \"\$f\" 2>/dev/null || (wc -c <\"\$f\" 2>/dev/null | tr -d \"[:space:]\") || true); [ \"\$sz\" != \"\" ] || continue; if [ \"\$best_size\" = \"\" ] || [ \"\$sz\" -lt \"\$best_size\" ]; then best_size=\"\$sz\"; best_path=\"\$f\"; fi; done; [ \"\$best_path\" != \"\" ]; printf \"%s\\n\" \"\$best_path\"' sh $(quote_sh "$glob") $(quote_sh "$exclude_re") $(quote_sh "$include_re")" 2>/dev/null || true
}

if [ "$MODEL_GGUF" = "" ] && [ "$MODEL_GGUF_GLOB" != "" ]; then
    selected="$(remote_select_model_gguf "$MODEL_GGUF_GLOB" "$MODEL_GGUF_EXCLUDE_EGREP" "$MODEL_GGUF_INCLUDE_EGREP")"
    if [ "$selected" = "" ]; then
        echo "error: MODEL_GGUF_GLOB matched no readable GGUFs on $target" >&2
        echo "note: MODEL_GGUF_GLOB=$MODEL_GGUF_GLOB" >&2
        echo "note: MODEL_GGUF_EXCLUDE_EGREP=$MODEL_GGUF_EXCLUDE_EGREP" >&2
        echo "note: MODEL_GGUF_INCLUDE_EGREP=$MODEL_GGUF_INCLUDE_EGREP" >&2
        exit 4
    fi
    MODEL_GGUF="$selected"
fi

if [ "$SKIP_LLAMA" != "1" ]; then
    if [ "$MODEL_GGUF" = "" ]; then
        echo "error: MODEL_GGUF is required (Spark absolute path)" >&2
        exit 2
    fi
    if [ "$LLAMA_CLI" = "" ]; then
        echo "error: LLAMA_CLI is required (Spark absolute path to llama-cli)" >&2
        exit 3
    fi
fi

LLAMA_DIR="${LLAMA_DIR:-}"
if [ "$LLAMA_DIR" = "" ] && [ "$LLAMA_CLI" != "" ]; then
    inferred="$(infer_llama_dir "$LLAMA_CLI" || true)"
    if [ "$inferred" != "" ] && [ "$inferred" != "$LLAMA_CLI" ]; then
        LLAMA_DIR="$inferred"
    fi
fi

REMOTE_LLAMA_ENV="ALLOW_RUN=1"
REMOTE_GGUF_INSPECT_ENV="ALLOW_MODEL_INSPECT=1"

if [ "$MODEL_SOURCE" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV MODEL_SOURCE=$(quote_sh "$MODEL_SOURCE")"
fi
if [ "$MODEL_QUANT" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV MODEL_QUANT=$(quote_sh "$MODEL_QUANT")"
fi
if [ "$MODEL_GGUF" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV MODEL_GGUF=$(quote_sh "$MODEL_GGUF")"
    REMOTE_GGUF_INSPECT_ENV="$REMOTE_GGUF_INSPECT_ENV MODEL_GGUF=$(quote_sh "$MODEL_GGUF")"
fi
if [ "$MODEL_GGUF_GLOB" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV MODEL_GGUF_GLOB=$(quote_sh "$MODEL_GGUF_GLOB") MODEL_GGUF_EXCLUDE_EGREP=$(quote_sh "$MODEL_GGUF_EXCLUDE_EGREP") MODEL_GGUF_INCLUDE_EGREP=$(quote_sh "$MODEL_GGUF_INCLUDE_EGREP") MODEL_GGUF_SELECT=$(quote_sh "smallest_by_size_bytes")"
    REMOTE_GGUF_INSPECT_ENV="$REMOTE_GGUF_INSPECT_ENV MODEL_GGUF_GLOB=$(quote_sh "$MODEL_GGUF_GLOB") MODEL_GGUF_EXCLUDE_EGREP=$(quote_sh "$MODEL_GGUF_EXCLUDE_EGREP") MODEL_GGUF_INCLUDE_EGREP=$(quote_sh "$MODEL_GGUF_INCLUDE_EGREP") MODEL_GGUF_SELECT=$(quote_sh "smallest_by_size_bytes")"
fi
if [ "$LLAMA_CLI" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV LLAMA_CLI=$(quote_sh "$LLAMA_CLI")"
fi
if [ "$LLAMA_DIR" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV LLAMA_DIR=$(quote_sh "$LLAMA_DIR")"
fi
if [ "$RUNTIME_LABEL" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV RUNTIME_LABEL=$(quote_sh "$RUNTIME_LABEL")"
fi
REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV CTX=$(quote_sh "$CTX") N_TOKENS=$(quote_sh "$N_TOKENS") N_GPU_LAYERS=$(quote_sh "$N_GPU_LAYERS")"
if [ "$EXTRA_ARGS" != "" ]; then
    REMOTE_LLAMA_ENV="$REMOTE_LLAMA_ENV EXTRA_ARGS=$(quote_sh "$EXTRA_ARGS")"
fi

if [ "$MODEL_RUNS_CSV" = "" ]; then
    MODEL_RUNS_CSV="$OUT_ROOT/model_runs.csv"
fi

export OUT_ROOT RUN_LABEL MODEL_RUNS_CSV LLAMA_SCOPE
export SKIP_GGUF_INSPECT SKIP_LLAMA SKIP_MTP_SIDECAR SKIP_VLLM
export LLAMA_FATTN_PATCH_PROBE LLAMA_MULTISLOT_PATCH_PROBE FETCH_LLAMA_OUT_DIR
export REMOTE_LLAMA_ENV REMOTE_GGUF_INSPECT_ENV
export SSH_OPTS

scripts/run_baseline_existing_runtime.sh "$target"
