#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
FETCH_REMOTE_ARTIFACTS="${FETCH_REMOTE_ARTIFACTS:-1}"
RUN_DS4_MACOS="${RUN_DS4_MACOS:-0}"
SPARK_INVENTORY="${SPARK_INVENTORY:-0}"
INVENTORY_DIRS="${INVENTORY_DIRS:-}"
INVENTORY_MAX_DEPTH="${INVENTORY_MAX_DEPTH:-}"
INVENTORY_MAX_FILES="${INVENTORY_MAX_FILES:-}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"
LLAMA_DIR="${LLAMA_DIR:-}"
MODEL_GGUF="${MODEL_GGUF:-}"
LLAMA_CLI="${LLAMA_CLI:-}"
RUNTIME_LABEL="${RUNTIME_LABEL:-}"
MODEL_SOURCE="${MODEL_SOURCE:-}"
MODEL_QUANT="${MODEL_QUANT:-}"
LLAMA_PROMPT="${LLAMA_PROMPT:-${PROMPT:-}}"
CTX="${CTX:-}"
N_TOKENS="${N_TOKENS:-}"
N_GPU_LAYERS="${N_GPU_LAYERS:-}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
SKIP_MODEL_SHA="${SKIP_MODEL_SHA:-0}"
LLAMA_SERVER_SWEEP="${LLAMA_SERVER_SWEEP:-0}"
LLAMA_SERVER="${LLAMA_SERVER:-}"
LLAMA_SERVER_SWEEP_PORT="${LLAMA_SERVER_SWEEP_PORT:-18080}"
LLAMA_SERVER_SWEEP_CTX="${LLAMA_SERVER_SWEEP_CTX:-}"
LLAMA_SERVER_SWEEP_PROMPT_WORDS="${LLAMA_SERVER_SWEEP_PROMPT_WORDS:-256 1024 4096}"
LLAMA_SERVER_SWEEP_N_PREDICT="${LLAMA_SERVER_SWEEP_N_PREDICT:-8}"
LLAMA_SERVER_SWEEP_REPEATS="${LLAMA_SERVER_SWEEP_REPEATS:-1}"
LLAMA_SERVER_SWEEP_CACHE_PROMPT="${LLAMA_SERVER_SWEEP_CACHE_PROMPT:-0}"
LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S="${LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S:-1200}"
LLAMA_SERVER_SWEEP_POLL_S="${LLAMA_SERVER_SWEEP_POLL_S:-5}"
LLAMA_SERVER_SWEEP_KEEP_SERVER="${LLAMA_SERVER_SWEEP_KEEP_SERVER:-0}"
LLAMA_SERVER_SWEEP_SERVER_ARGS="${LLAMA_SERVER_SWEEP_SERVER_ARGS:-}"
VLLM_MODEL="${VLLM_MODEL:-}"
VLLM_PROMPT="${VLLM_PROMPT:-${PROMPT:-}}"
MAX_TOKENS="${MAX_TOKENS:-}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-}"
MEASURE_TTFT="${MEASURE_TTFT:-}"
GPU_SAMPLE="${GPU_SAMPLE:-1}"
GPU_SAMPLE_INTERVAL_S="${GPU_SAMPLE_INTERVAL_S:-1}"
DS4_DIR="${DS4_DIR:-}"
DS4_MODEL_GGUF="${DS4_MODEL_GGUF:-}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"
REMOTE_BENCH_ENV="${REMOTE_BENCH_ENV:-}"
REMOTE_LLAMA_ENV="${REMOTE_LLAMA_ENV:-}"
REMOTE_VLLM_ENV="${REMOTE_VLLM_ENV:-}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"

mkdir -p "$OUT_DIR"

echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"

REPORT_MD="$OUT_DIR/baseline_existing_runtime.md"

prompt_meta_line()
{
    s="$1"
    if [ "$s" = "" ]; then
        echo "prompt=default"
        return 0
    fi
    chars="$(printf %s "$s" | wc -c | tr -d ' ')"
    sha="NA"
    if command -v sha256sum >/dev/null 2>&1; then
        sha="$(printf %s "$s" | sha256sum | awk '{print $1}' || echo NA)"
    elif command -v shasum >/dev/null 2>&1; then
        sha="$(printf %s "$s" | shasum -a 256 | awk '{print $1}' || echo NA)"
    fi
    echo "prompt_chars=$chars prompt_sha256=$sha"
}

extract_baseline_summary()
{
    in="$1"
    if [ ! -r "$in" ]; then
        return 0
    fi
    awk '
        found==1 {
            if ($0 ~ /^== /) exit
            print
        }
        $0 == "== baseline summary (approx) ==" { found=1 }
    ' "$in" 2>/dev/null || true
}

b64_enc()
{
    if [ "${1:-}" = "" ]; then
        return 0
    fi
    printf %s "$1" | base64 | tr -d '\n'
}

b64_dec()
{
    if [ "${1:-}" = "" ]; then
        return 0
    fi
    if command -v base64 >/dev/null 2>&1; then
        if printf %s "$1" | base64 -d >/dev/null 2>&1; then
            printf %s "$1" | base64 -d
            return 0
        fi
        if printf %s "$1" | base64 --decode >/dev/null 2>&1; then
            printf %s "$1" | base64 --decode
            return 0
        fi
        if printf %s "$1" | base64 -D >/dev/null 2>&1; then
            printf %s "$1" | base64 -D
            return 0
        fi
    fi
    python3 - <<'PY' "$1" 2>/dev/null || return 1
import base64,sys
print(base64.b64decode(sys.argv[1].encode("utf-8")).decode("utf-8"),end="")
PY
}

parse_env_kv_b64()
{
    if [ "${1:-}" = "" ]; then
        return 0
    fi
    python3 - <<'PY' "$1" 2>/dev/null || true
import base64, shlex, sys

s = sys.argv[1]
try:
    toks = shlex.split(s, posix=True)
except Exception:
    toks = s.split()

for t in toks:
    if "=" not in t:
        continue
    k, v = t.split("=", 1)
    if not k:
        continue
    b64 = base64.b64encode(v.encode("utf-8")).decode("utf-8")
    sys.stdout.write(k + "\t" + b64 + "\n")
PY
}

apply_overrides()
{
    env_str="${1:-}"
    scope="${2:-}"
    if [ "$env_str" = "" ]; then
        return 0
    fi
    parsed="$(parse_env_kv_b64 "$env_str" || true)"
    if [ "$parsed" = "" ]; then
        return 0
    fi
    tab="$(printf '\t')"
    while IFS="$tab" read -r k vb64; do
        if [ "$k" = "" ]; then
            continue
        fi
        v="$(b64_dec "$vb64" || echo "")"
        case "$scope:$k" in
            bench:ALLOW_FETCH|llama:ALLOW_FETCH|vllm:ALLOW_FETCH) ALLOW_FETCH="$v" ;;
            bench:ALLOW_BUILD|llama:ALLOW_BUILD|vllm:ALLOW_BUILD) ALLOW_BUILD="$v" ;;
            bench:ALLOW_RUN|llama:ALLOW_RUN|vllm:ALLOW_RUN) ALLOW_RUN="$v" ;;
            bench:GPU_SAMPLE|llama:GPU_SAMPLE|vllm:GPU_SAMPLE) GPU_SAMPLE="$v" ;;
            bench:GPU_SAMPLE_INTERVAL_S|llama:GPU_SAMPLE_INTERVAL_S|vllm:GPU_SAMPLE_INTERVAL_S) GPU_SAMPLE_INTERVAL_S="$v" ;;

            bench:SPARK_INVENTORY) SPARK_INVENTORY="$v" ;;
            bench:INVENTORY_DIRS) INVENTORY_DIRS="$v" ;;
            bench:INVENTORY_MAX_DEPTH) INVENTORY_MAX_DEPTH="$v" ;;
            bench:INVENTORY_MAX_FILES) INVENTORY_MAX_FILES="$v" ;;

            llama:LLAMA_DIR) LLAMA_DIR="$v" ;;
            llama:MODEL_GGUF) MODEL_GGUF="$v" ;;
            llama:LLAMA_CLI) LLAMA_CLI="$v" ;;
            llama:RUNTIME_LABEL) RUNTIME_LABEL="$v" ;;
            llama:MODEL_SOURCE) MODEL_SOURCE="$v" ;;
            llama:MODEL_QUANT) MODEL_QUANT="$v" ;;
            llama:LLAMA_PROMPT) LLAMA_PROMPT="$v" ;;
            llama:CTX) CTX="$v" ;;
            llama:N_TOKENS) N_TOKENS="$v" ;;
            llama:N_GPU_LAYERS) N_GPU_LAYERS="$v" ;;
            llama:EXTRA_ARGS) EXTRA_ARGS="$v" ;;
            llama:SKIP_MODEL_SHA) SKIP_MODEL_SHA="$v" ;;
            llama:LLAMA_SERVER_SWEEP) LLAMA_SERVER_SWEEP="$v" ;;
            llama:LLAMA_SERVER) LLAMA_SERVER="$v" ;;
            llama:LLAMA_SERVER_SWEEP_PORT) LLAMA_SERVER_SWEEP_PORT="$v" ;;
            llama:LLAMA_SERVER_SWEEP_CTX) LLAMA_SERVER_SWEEP_CTX="$v" ;;
            llama:LLAMA_SERVER_SWEEP_PROMPT_WORDS) LLAMA_SERVER_SWEEP_PROMPT_WORDS="$v" ;;
            llama:LLAMA_SERVER_SWEEP_N_PREDICT) LLAMA_SERVER_SWEEP_N_PREDICT="$v" ;;
            llama:LLAMA_SERVER_SWEEP_REPEATS) LLAMA_SERVER_SWEEP_REPEATS="$v" ;;
            llama:LLAMA_SERVER_SWEEP_CACHE_PROMPT) LLAMA_SERVER_SWEEP_CACHE_PROMPT="$v" ;;
            llama:LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S) LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S="$v" ;;
            llama:LLAMA_SERVER_SWEEP_POLL_S) LLAMA_SERVER_SWEEP_POLL_S="$v" ;;
            llama:LLAMA_SERVER_SWEEP_KEEP_SERVER) LLAMA_SERVER_SWEEP_KEEP_SERVER="$v" ;;
            llama:LLAMA_SERVER_SWEEP_SERVER_ARGS) LLAMA_SERVER_SWEEP_SERVER_ARGS="$v" ;;

            vllm:VLLM_MODEL) VLLM_MODEL="$v" ;;
            vllm:VLLM_PROMPT) VLLM_PROMPT="$v" ;;
            vllm:MAX_TOKENS) MAX_TOKENS="$v" ;;
            vllm:TENSOR_PARALLEL_SIZE) TENSOR_PARALLEL_SIZE="$v" ;;
            vllm:MEASURE_TTFT) MEASURE_TTFT="$v" ;;
        esac
    done <<EOF
$parsed
EOF
}

LLAMA_PROMPT_B64="$(b64_enc "$LLAMA_PROMPT")"
VLLM_PROMPT_B64="$(b64_enc "$VLLM_PROMPT")"
EXTRA_ARGS_B64="$(b64_enc "$EXTRA_ARGS")"
LLAMA_SERVER_SWEEP_SERVER_ARGS_B64="$(b64_enc "$LLAMA_SERVER_SWEEP_SERVER_ARGS")"

apply_overrides "$REMOTE_BENCH_ENV" bench
apply_overrides "${REMOTE_LLAMA_ENV:-$REMOTE_BENCH_ENV}" llama
apply_overrides "${REMOTE_VLLM_ENV:-$REMOTE_BENCH_ENV}" vllm

LLAMA_PROMPT_B64="$(b64_enc "$LLAMA_PROMPT")"
VLLM_PROMPT_B64="$(b64_enc "$VLLM_PROMPT")"
EXTRA_ARGS_B64="$(b64_enc "$EXTRA_ARGS")"
LLAMA_SERVER_SWEEP_SERVER_ARGS_B64="$(b64_enc "$LLAMA_SERVER_SWEEP_SERVER_ARGS")"

LLAMA_DIR_B64="$(b64_enc "$LLAMA_DIR")"
MODEL_GGUF_B64="$(b64_enc "$MODEL_GGUF")"
LLAMA_CLI_B64="$(b64_enc "$LLAMA_CLI")"
LLAMA_SERVER_B64="$(b64_enc "$LLAMA_SERVER")"
RUNTIME_LABEL_B64="$(b64_enc "$RUNTIME_LABEL")"
MODEL_SOURCE_B64="$(b64_enc "$MODEL_SOURCE")"
MODEL_QUANT_B64="$(b64_enc "$MODEL_QUANT")"
VLLM_MODEL_B64="$(b64_enc "$VLLM_MODEL")"
INVENTORY_DIRS_B64="$(b64_enc "$INVENTORY_DIRS")"

REMOTE_LLAMA_OUT_DIR="/tmp/baseline_llamacpp_${ts}"
REMOTE_LLAMA_SERVER_SWEEP_OUT_DIR="/tmp/baseline_llamacpp_server_sweep_${ts}"
REMOTE_VLLM_OUT_DIR="/tmp/baseline_vllm_${ts}"
REMOTE_INV_OUT_DIR="/tmp/baseline_spark_inventory_${ts}"

REMOTE_LLAMA_CMD="cat > /tmp/benchmark_llamacpp_spark.sh && chmod +x /tmp/benchmark_llamacpp_spark.sh && ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S SKIP_MODEL_SHA=$SKIP_MODEL_SHA LLAMA_DIR='' LLAMA_DIR_B64='${LLAMA_DIR_B64}' MODEL_GGUF='' MODEL_GGUF_B64='${MODEL_GGUF_B64}' LLAMA_CLI='' LLAMA_CLI_B64='${LLAMA_CLI_B64}' RUNTIME_LABEL='' RUNTIME_LABEL_B64='${RUNTIME_LABEL_B64}' MODEL_SOURCE='' MODEL_SOURCE_B64='${MODEL_SOURCE_B64}' MODEL_QUANT='' MODEL_QUANT_B64='${MODEL_QUANT_B64}' PROMPT_B64='${LLAMA_PROMPT_B64}' CTX='${CTX}' N_TOKENS='${N_TOKENS}' N_GPU_LAYERS='${N_GPU_LAYERS}' EXTRA_ARGS_B64='${EXTRA_ARGS_B64}' OUT_DIR='${REMOTE_LLAMA_OUT_DIR}' /tmp/benchmark_llamacpp_spark.sh"
REMOTE_LLAMA_CMD_PRINT="cat > /tmp/benchmark_llamacpp_spark.sh && chmod +x /tmp/benchmark_llamacpp_spark.sh && ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S SKIP_MODEL_SHA=$SKIP_MODEL_SHA LLAMA_DIR_B64='${LLAMA_DIR_B64}' MODEL_GGUF_B64='${MODEL_GGUF_B64}' LLAMA_CLI_B64='${LLAMA_CLI_B64}' RUNTIME_LABEL_B64='${RUNTIME_LABEL_B64}' MODEL_SOURCE_B64='${MODEL_SOURCE_B64}' MODEL_QUANT_B64='${MODEL_QUANT_B64}' PROMPT_B64='<omitted>' CTX='${CTX}' N_TOKENS='${N_TOKENS}' N_GPU_LAYERS='${N_GPU_LAYERS}' EXTRA_ARGS_B64='${EXTRA_ARGS_B64}' OUT_DIR='${REMOTE_LLAMA_OUT_DIR}' /tmp/benchmark_llamacpp_spark.sh"

REMOTE_LLAMA_SERVER_SWEEP_CMD="cat > /tmp/benchmark_llamacpp_server_sweep.py && chmod +x /tmp/benchmark_llamacpp_server_sweep.py && MODEL_GGUF='' MODEL_GGUF_B64='${MODEL_GGUF_B64}' LLAMA_SERVER='' LLAMA_SERVER_B64='${LLAMA_SERVER_B64}' SERVER_ARGS='' SERVER_ARGS_B64='${LLAMA_SERVER_SWEEP_SERVER_ARGS_B64}' OUT_DIR='${REMOTE_LLAMA_SERVER_SWEEP_OUT_DIR}' START_SERVER=1 KEEP_SERVER='${LLAMA_SERVER_SWEEP_KEEP_SERVER}' CACHE_PROMPT='${LLAMA_SERVER_SWEEP_CACHE_PROMPT}' WAIT_TIMEOUT_S='${LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S}' POLL_S='${LLAMA_SERVER_SWEEP_POLL_S}' PROMPT_WORDS='${LLAMA_SERVER_SWEEP_PROMPT_WORDS}' N_PREDICT='${LLAMA_SERVER_SWEEP_N_PREDICT}' REPEATS='${LLAMA_SERVER_SWEEP_REPEATS}' PORT='${LLAMA_SERVER_SWEEP_PORT}' CTX='${LLAMA_SERVER_SWEEP_CTX:-$CTX}' N_GPU_LAYERS='${N_GPU_LAYERS}' /tmp/benchmark_llamacpp_server_sweep.py"
REMOTE_LLAMA_SERVER_SWEEP_CMD_PRINT="cat > /tmp/benchmark_llamacpp_server_sweep.py && chmod +x /tmp/benchmark_llamacpp_server_sweep.py && MODEL_GGUF_B64='${MODEL_GGUF_B64}' LLAMA_SERVER_B64='${LLAMA_SERVER_B64}' SERVER_ARGS_B64='${LLAMA_SERVER_SWEEP_SERVER_ARGS_B64}' OUT_DIR='${REMOTE_LLAMA_SERVER_SWEEP_OUT_DIR}' START_SERVER=1 KEEP_SERVER='${LLAMA_SERVER_SWEEP_KEEP_SERVER}' CACHE_PROMPT='${LLAMA_SERVER_SWEEP_CACHE_PROMPT}' WAIT_TIMEOUT_S='${LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S}' POLL_S='${LLAMA_SERVER_SWEEP_POLL_S}' PROMPT_WORDS='${LLAMA_SERVER_SWEEP_PROMPT_WORDS}' N_PREDICT='${LLAMA_SERVER_SWEEP_N_PREDICT}' REPEATS='${LLAMA_SERVER_SWEEP_REPEATS}' PORT='${LLAMA_SERVER_SWEEP_PORT}' CTX='${LLAMA_SERVER_SWEEP_CTX:-$CTX}' N_GPU_LAYERS='${N_GPU_LAYERS}' /tmp/benchmark_llamacpp_server_sweep.py"

REMOTE_VLLM_CMD="cat > /tmp/benchmark_vllm_spark.sh && chmod +x /tmp/benchmark_vllm_spark.sh && ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S VLLM_MODEL='' VLLM_MODEL_B64='${VLLM_MODEL_B64}' PROMPT_B64='${VLLM_PROMPT_B64}' MAX_TOKENS='${MAX_TOKENS}' TENSOR_PARALLEL_SIZE='${TENSOR_PARALLEL_SIZE}' MEASURE_TTFT='${MEASURE_TTFT}' OUT_DIR='${REMOTE_VLLM_OUT_DIR}' /tmp/benchmark_vllm_spark.sh"
REMOTE_VLLM_CMD_PRINT="cat > /tmp/benchmark_vllm_spark.sh && chmod +x /tmp/benchmark_vllm_spark.sh && ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S VLLM_MODEL_B64='${VLLM_MODEL_B64}' PROMPT_B64='<omitted>' MAX_TOKENS='${MAX_TOKENS}' TENSOR_PARALLEL_SIZE='${TENSOR_PARALLEL_SIZE}' MEASURE_TTFT='${MEASURE_TTFT}' OUT_DIR='${REMOTE_VLLM_OUT_DIR}' /tmp/benchmark_vllm_spark.sh"

REMOTE_INV_CMD="cat > /tmp/benchmark_spark_inventory.sh && chmod +x /tmp/benchmark_spark_inventory.sh && INVENTORY_DIRS='' INVENTORY_DIRS_B64='${INVENTORY_DIRS_B64}' MAX_DEPTH='${INVENTORY_MAX_DEPTH}' MAX_FILES='${INVENTORY_MAX_FILES}' OUT_DIR='${REMOTE_INV_OUT_DIR}' /tmp/benchmark_spark_inventory.sh"
REMOTE_INV_CMD_PRINT="cat > /tmp/benchmark_spark_inventory.sh && chmod +x /tmp/benchmark_spark_inventory.sh && INVENTORY_DIRS_B64='${INVENTORY_DIRS_B64}' MAX_DEPTH='${INVENTORY_MAX_DEPTH}' MAX_FILES='${INVENTORY_MAX_FILES}' OUT_DIR='${REMOTE_INV_OUT_DIR}' /tmp/benchmark_spark_inventory.sh"

LLAMA_PROMPT_META="$(prompt_meta_line "$LLAMA_PROMPT")"
VLLM_PROMPT_META="$(prompt_meta_line "$VLLM_PROMPT")"

fetch_remote_artifacts()
{
    target_host="$1"
    remote_dir="$2"
    local_dir="$3"
    label="$4"
    if [ "$FETCH_REMOTE_ARTIFACTS" != "1" ]; then
        return 0
    fi
    if ! command -v scp >/dev/null 2>&1; then
        echo "missing scp; cannot fetch $label artifacts from spark"
        return 0
    fi
    if [ "$remote_dir" = "" ] || [ "$local_dir" = "" ]; then
        return 0
    fi
    mkdir -p "$local_dir"
    remote_parent="$(dirname "$remote_dir")"
    remote_base="$(basename "$remote_dir")"
    remote_tar="/tmp/ds4_on_spark_${label}_${ts}.tgz"
    local_tar="$local_dir/${label}.tgz"
    ssh $SSH_OPTS "$target_host" "
set -eu
tar -C '$remote_parent' -czf '$remote_tar' '$remote_base'
" >/dev/null 2>&1 || return 0
    scp $SSH_OPTS "$target_host:$remote_tar" "$local_tar" >/dev/null 2>&1 || return 0
    tar -C "$local_dir" -xzf "$local_tar" >/dev/null 2>&1 || true
    ssh $SSH_OPTS "$target_host" "rm -f '$remote_tar'" >/dev/null 2>&1 || true
}

{
    echo "# Existing Runtime Baseline (Spark)"
    echo
    echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "- ds4_on_spark commit: $repo_rev"
    echo "- target: $target"
    echo "- run_ds4_macos: $RUN_DS4_MACOS"
    echo "- gates: ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN"
    echo "- fetch_remote_artifacts: $FETCH_REMOTE_ARTIFACTS"
    echo
    echo "## Command Line (local)"
    echo
    echo '```sh'
    echo "RUN_DS4_MACOS=$RUN_DS4_MACOS ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN FETCH_REMOTE_ARTIFACTS=$FETCH_REMOTE_ARTIFACTS GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S LLAMA_DIR='$LLAMA_DIR' MODEL_GGUF='$MODEL_GGUF' LLAMA_CLI='$LLAMA_CLI' RUNTIME_LABEL='$RUNTIME_LABEL' MODEL_SOURCE='$MODEL_SOURCE' MODEL_QUANT='$MODEL_QUANT' LLAMA_PROMPT='<omitted>' LLAMA_PROMPT_META='$LLAMA_PROMPT_META' CTX='$CTX' N_TOKENS='$N_TOKENS' N_GPU_LAYERS='$N_GPU_LAYERS' EXTRA_ARGS='$EXTRA_ARGS' VLLM_MODEL='$VLLM_MODEL' VLLM_PROMPT='<omitted>' VLLM_PROMPT_META='$VLLM_PROMPT_META' MAX_TOKENS='$MAX_TOKENS' TENSOR_PARALLEL_SIZE='$TENSOR_PARALLEL_SIZE' MEASURE_TTFT='$MEASURE_TTFT' DS4_DIR='$DS4_DIR' DS4_MODEL_GGUF='$DS4_MODEL_GGUF' SSH_OPTS='$SSH_OPTS' $0 $target"
    echo '```'
    echo
    echo "## Inputs (optional)"
    echo
    echo "- GPU_SAMPLE: ${GPU_SAMPLE:-<default>}"
    echo "- GPU_SAMPLE_INTERVAL_S: ${GPU_SAMPLE_INTERVAL_S:-<default>}"
    echo "- LLAMA_DIR: ${LLAMA_DIR:-<default on spark>}"
    echo "- MODEL_GGUF (llama.cpp): ${MODEL_GGUF:-<unset>}"
    echo "- LLAMA_CLI (llama.cpp override): ${LLAMA_CLI:-<unset>}"
    echo "- RUNTIME_LABEL (llama.cpp): ${RUNTIME_LABEL:-<unset>}"
    echo "- MODEL_SOURCE (llama.cpp): ${MODEL_SOURCE:-<unset>}"
    echo "- MODEL_QUANT (llama.cpp): ${MODEL_QUANT:-<unset>}"
    echo "- LLAMA_PROMPT (llama.cpp): $(prompt_meta_line "$LLAMA_PROMPT")"
    echo "- CTX (llama.cpp): ${CTX:-<default>}"
    echo "- N_TOKENS (llama.cpp): ${N_TOKENS:-<default>}"
    echo "- N_GPU_LAYERS (llama.cpp): ${N_GPU_LAYERS:-<default>}"
    echo "- EXTRA_ARGS (llama.cpp): ${EXTRA_ARGS:-<default>}"
    echo "- LLAMA_SERVER_SWEEP (llama-server probe): ${LLAMA_SERVER_SWEEP:-<default>}"
    echo "- LLAMA_SERVER (llama-server override): ${LLAMA_SERVER:-<unset>}"
    echo "- LLAMA_SERVER_SWEEP_PORT: ${LLAMA_SERVER_SWEEP_PORT:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_CTX: ${LLAMA_SERVER_SWEEP_CTX:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_PROMPT_WORDS: ${LLAMA_SERVER_SWEEP_PROMPT_WORDS:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_N_PREDICT: ${LLAMA_SERVER_SWEEP_N_PREDICT:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_REPEATS: ${LLAMA_SERVER_SWEEP_REPEATS:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_CACHE_PROMPT: ${LLAMA_SERVER_SWEEP_CACHE_PROMPT:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S: ${LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_POLL_S: ${LLAMA_SERVER_SWEEP_POLL_S:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_KEEP_SERVER: ${LLAMA_SERVER_SWEEP_KEEP_SERVER:-<default>}"
    echo "- LLAMA_SERVER_SWEEP_SERVER_ARGS: ${LLAMA_SERVER_SWEEP_SERVER_ARGS:-<default>}"
    echo "- VLLM_MODEL (hf dir): ${VLLM_MODEL:-<unset>}"
    echo "- VLLM_PROMPT (vLLM): $(prompt_meta_line "$VLLM_PROMPT")"
    echo "- MAX_TOKENS (vLLM): ${MAX_TOKENS:-<default>}"
    echo "- TENSOR_PARALLEL_SIZE (vLLM): ${TENSOR_PARALLEL_SIZE:-<default>}"
    echo "- MEASURE_TTFT (vLLM): ${MEASURE_TTFT:-<default>}"
    echo "- DS4_DIR (macos): ${DS4_DIR:-<default local>}"
    echo "- DS4_MODEL_GGUF (macos): ${DS4_MODEL_GGUF:-<unset>}"
    echo "- SPARK_INVENTORY: ${SPARK_INVENTORY:-<default>}"
    echo "- INVENTORY_DIRS: ${INVENTORY_DIRS:-<remote default>}"
    echo "- INVENTORY_MAX_DEPTH: ${INVENTORY_MAX_DEPTH:-<remote default>}"
    echo "- INVENTORY_MAX_FILES: ${INVENTORY_MAX_FILES:-<remote default>}"
    echo "- FETCH_REMOTE_ARTIFACTS: ${FETCH_REMOTE_ARTIFACTS:-<default>}"
    echo
    echo "## Remote Commands"
    echo
    echo "These are the exact remote invocations used for the Spark sections."
    echo
    echo "llama.cpp:"
    echo
    echo '```sh'
    echo "ssh $SSH_OPTS $target \"$REMOTE_LLAMA_CMD_PRINT\" < scripts/benchmark_llamacpp_spark.sh"
    echo '```'
    echo
    echo "llama-server sweep (optional; LLAMA_SERVER_SWEEP=1):"
    echo
    echo '```sh'
    echo "ssh $SSH_OPTS $target \"$REMOTE_LLAMA_SERVER_SWEEP_CMD_PRINT\" < scripts/benchmark_llamacpp_server_sweep.py"
    echo '```'
    echo
    echo "vLLM:"
    echo
    echo '```sh'
    echo "ssh $SSH_OPTS $target \"$REMOTE_VLLM_CMD_PRINT\" < scripts/benchmark_vllm_spark.sh"
    echo '```'
    echo
    echo "inventory (optional; SPARK_INVENTORY=1):"
    echo
    echo '```sh'
    echo "ssh $SSH_OPTS $target \"$REMOTE_INV_CMD_PRINT\" < scripts/benchmark_spark_inventory.sh"
    echo '```'
    echo
    echo "## Safety Gates"
    echo
    echo "This run script only executes what the remote benchmark scripts allow."
    echo "Set gates via env vars (passed to remote runs for this session):"
    echo
    echo "- ALLOW_FETCH=1"
    echo "- ALLOW_BUILD=1"
    echo "- ALLOW_RUN=1"
    echo "- REMOTE_BENCH_ENV='...'"
    echo "- REMOTE_LLAMA_ENV='...'"
    echo "- REMOTE_VLLM_ENV='...'"
    echo
    echo "Remote llama env:"
    echo
    echo "Do not put secrets in REMOTE_* env values; this report records them."
    echo
    echo '```'
    echo "$REMOTE_LLAMA_ENV"
    echo '```'
    echo
    echo "Remote vLLM env:"
    echo
    echo '```'
    echo "$REMOTE_VLLM_ENV"
    echo '```'
    echo
    echo "## Spark Probe"
    echo
    echo '```'
    ssh $SSH_OPTS "$target" '
set -eu
echo "hostname=$(hostname)"
echo "uname=$(uname -a)"
echo
if command -v lscpu >/dev/null 2>&1; then
    echo "== lscpu =="
    lscpu || true
    echo
fi
if [ -r /proc/meminfo ]; then
    echo "== meminfo (head) =="
    head -n 50 /proc/meminfo || true
    echo
fi
if command -v free >/dev/null 2>&1; then
    echo "== free -h =="
    free -h || true
    echo
fi
if command -v df >/dev/null 2>&1; then
    echo "== df -h / =="
    df -h / || true
    echo
fi
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "== nvidia-smi =="
    nvidia-smi || true
    echo
    echo "== nvidia-smi -L =="
    nvidia-smi -L || true
    echo
fi
' || true
    echo '```'
    echo
} >"$REPORT_MD"

if [ "$SPARK_INVENTORY" = "1" ]; then
    echo "== running Spark inventory script (read-only) =="
    rc_inv=0
    ssh $SSH_OPTS "$target" "$REMOTE_INV_CMD" <"$repo_root/scripts/benchmark_spark_inventory.sh" \
        >"$OUT_DIR/remote_inventory_stdout.txt" 2>"$OUT_DIR/remote_inventory_stderr.txt" || rc_inv=$?

    INV_ARTIFACT_DIR="$OUT_DIR/spark_inventory_artifacts"
    fetch_remote_artifacts "$target" "$REMOTE_INV_OUT_DIR" "$INV_ARTIFACT_DIR" "inventory" || true

    {
        echo "## Spark Inventory (Spark)"
        echo
        echo "- ssh_exit_code: $rc_inv"
        echo "- spark_out_dir: $REMOTE_INV_OUT_DIR"
        echo "- spark_artifacts_local: $INV_ARTIFACT_DIR"
        echo
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/remote_inventory_stdout.txt"
        echo "- stderr: $OUT_DIR/remote_inventory_stderr.txt"
        echo
        echo "Stdout:"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/remote_inventory_stdout.txt" || true
        echo '```'
        echo
        echo "Stderr:"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/remote_inventory_stderr.txt" || true
        echo '```'
        echo
    } >>"$REPORT_MD"
fi

echo "== running llama.cpp benchmark script on spark (may be gated) =="
rc_llama=0
ssh $SSH_OPTS "$target" "$REMOTE_LLAMA_CMD" <"$repo_root/scripts/benchmark_llamacpp_spark.sh" \
    >"$OUT_DIR/remote_llamacpp_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_stderr.txt" || rc_llama=$?

LLAMA_ARTIFACT_DIR="$OUT_DIR/spark_llamacpp_artifacts"
fetch_remote_artifacts "$target" "$REMOTE_LLAMA_OUT_DIR" "$LLAMA_ARTIFACT_DIR" "llamacpp" || true

{
    echo "## llama.cpp (Spark)"
    echo
    echo "- ssh_exit_code: $rc_llama"
    echo "- spark_out_dir: $REMOTE_LLAMA_OUT_DIR"
    echo "- spark_artifacts_local: $LLAMA_ARTIFACT_DIR"
    echo
    echo "Summary (best-effort):"
    echo
    echo '```'
    extract_baseline_summary "$OUT_DIR/remote_llamacpp_stdout.txt"
    echo '```'
    echo
    echo "Full logs:"
    echo
    echo "- stdout: $OUT_DIR/remote_llamacpp_stdout.txt"
    echo "- stderr: $OUT_DIR/remote_llamacpp_stderr.txt"
    echo
    echo "Stdout:"
    echo
    echo '```'
    sed -n '1,200p' "$OUT_DIR/remote_llamacpp_stdout.txt" || true
    echo '```'
    echo
    echo "Stderr:"
    echo
    echo '```'
    sed -n '1,200p' "$OUT_DIR/remote_llamacpp_stderr.txt" || true
    echo '```'
    echo
} >>"$REPORT_MD"

if [ "$LLAMA_SERVER_SWEEP" = "1" ]; then
    echo "== running llama-server sweep on spark (may be gated; long model loads) =="
    rc_llama_server_sweep=0
    ssh $SSH_OPTS "$target" "$REMOTE_LLAMA_SERVER_SWEEP_CMD" <"$repo_root/scripts/benchmark_llamacpp_server_sweep.py" \
        >"$OUT_DIR/remote_llamacpp_server_sweep_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_server_sweep_stderr.txt" || rc_llama_server_sweep=$?

    LLAMA_SERVER_SWEEP_ARTIFACT_DIR="$OUT_DIR/spark_llamacpp_server_sweep_artifacts"
    fetch_remote_artifacts "$target" "$REMOTE_LLAMA_SERVER_SWEEP_OUT_DIR" "$LLAMA_SERVER_SWEEP_ARTIFACT_DIR" "llamacpp_server_sweep" || true

    {
        echo "## llama-server sweep (Spark)"
        echo
        echo "- ssh_exit_code: $rc_llama_server_sweep"
        echo "- spark_out_dir: $REMOTE_LLAMA_SERVER_SWEEP_OUT_DIR"
        echo "- spark_artifacts_local: $LLAMA_SERVER_SWEEP_ARTIFACT_DIR"
        echo
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/remote_llamacpp_server_sweep_stdout.txt"
        echo "- stderr: $OUT_DIR/remote_llamacpp_server_sweep_stderr.txt"
        echo
        echo "Stdout (head):"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/remote_llamacpp_server_sweep_stdout.txt" || true
        echo '```'
        echo
        echo "Stderr (head):"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/remote_llamacpp_server_sweep_stderr.txt" || true
        echo '```'
        echo
    } >>"$REPORT_MD"
fi

echo "== running vLLM probe script on spark =="
rc_vllm=0
ssh $SSH_OPTS "$target" "$REMOTE_VLLM_CMD" <"$repo_root/scripts/benchmark_vllm_spark.sh" \
    >"$OUT_DIR/remote_vllm_stdout.txt" 2>"$OUT_DIR/remote_vllm_stderr.txt" || rc_vllm=$?

VLLM_ARTIFACT_DIR="$OUT_DIR/spark_vllm_artifacts"
fetch_remote_artifacts "$target" "$REMOTE_VLLM_OUT_DIR" "$VLLM_ARTIFACT_DIR" "vllm" || true

{
    echo "## vLLM (Spark)"
    echo
    echo "- ssh_exit_code: $rc_vllm"
    echo "- spark_out_dir: $REMOTE_VLLM_OUT_DIR"
    echo "- spark_artifacts_local: $VLLM_ARTIFACT_DIR"
    echo
    echo "Summary (best-effort):"
    echo
    echo '```'
    extract_baseline_summary "$OUT_DIR/remote_vllm_stdout.txt"
    echo '```'
    echo
    echo "Full logs:"
    echo
    echo "- stdout: $OUT_DIR/remote_vllm_stdout.txt"
    echo "- stderr: $OUT_DIR/remote_vllm_stderr.txt"
    echo
    echo "Stdout:"
    echo
    echo '```'
    sed -n '1,200p' "$OUT_DIR/remote_vllm_stdout.txt" || true
    echo '```'
    echo
    echo "Stderr:"
    echo
    echo '```'
    sed -n '1,200p' "$OUT_DIR/remote_vllm_stderr.txt" || true
    echo '```'
    echo
} >>"$REPORT_MD"

if [ "$RUN_DS4_MACOS" = "1" ]; then
    echo "== running local ds4 benchmark (macos; may be gated) =="
    DS4_OUT_DIR="$OUT_DIR/ds4_macos"
    mkdir -p "$DS4_OUT_DIR"

    (OUT_DIR="$DS4_OUT_DIR" ALLOW_FETCH="$ALLOW_FETCH" ALLOW_BUILD="$ALLOW_BUILD" ALLOW_RUN="$ALLOW_RUN" DS4_DIR="$DS4_DIR" MODEL_GGUF="$DS4_MODEL_GGUF" "$repo_root/scripts/benchmark_ds4_macos.sh") \
        >"$OUT_DIR/local_ds4_stdout.txt" 2>"$OUT_DIR/local_ds4_stderr.txt" || true

    {
        echo "## antirez/ds4 (Mac / Metal)"
        echo
        echo "Summary (best-effort):"
        echo
        echo '```'
        extract_baseline_summary "$OUT_DIR/local_ds4_stdout.txt"
        echo '```'
        echo
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/local_ds4_stdout.txt"
        echo "- stderr: $OUT_DIR/local_ds4_stderr.txt"
        echo
        echo "Stdout:"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/local_ds4_stdout.txt" || true
        echo '```'
        echo
        echo "Stderr:"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/local_ds4_stderr.txt" || true
        echo '```'
        echo
    } >>"$REPORT_MD"
fi

echo "done: $REPORT_MD"
