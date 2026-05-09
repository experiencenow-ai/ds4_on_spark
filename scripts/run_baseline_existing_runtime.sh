#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
RUN_DS4_MACOS="${RUN_DS4_MACOS:-0}"
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
REMOTE_LLAMA_ENV="${REMOTE_LLAMA_ENV:-$REMOTE_BENCH_ENV}"
REMOTE_VLLM_ENV="${REMOTE_VLLM_ENV:-$REMOTE_BENCH_ENV}"
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

LLAMA_PROMPT_B64="$(b64_enc "$LLAMA_PROMPT")"
VLLM_PROMPT_B64="$(b64_enc "$VLLM_PROMPT")"
EXTRA_ARGS_B64="$(b64_enc "$EXTRA_ARGS")"

REMOTE_LLAMA_CMD="cat > /tmp/benchmark_llamacpp_spark.sh && chmod +x /tmp/benchmark_llamacpp_spark.sh && ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S LLAMA_DIR='${LLAMA_DIR}' MODEL_GGUF='${MODEL_GGUF}' LLAMA_CLI='${LLAMA_CLI}' RUNTIME_LABEL='${RUNTIME_LABEL}' MODEL_SOURCE='${MODEL_SOURCE}' MODEL_QUANT='${MODEL_QUANT}' PROMPT_B64='${LLAMA_PROMPT_B64}' CTX='${CTX}' N_TOKENS='${N_TOKENS}' N_GPU_LAYERS='${N_GPU_LAYERS}' EXTRA_ARGS_B64='${EXTRA_ARGS_B64}' OUT_DIR='/tmp/baseline_llamacpp_${ts}' /tmp/benchmark_llamacpp_spark.sh"
REMOTE_LLAMA_CMD_PRINT="cat > /tmp/benchmark_llamacpp_spark.sh && chmod +x /tmp/benchmark_llamacpp_spark.sh && ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S LLAMA_DIR='${LLAMA_DIR}' MODEL_GGUF='${MODEL_GGUF}' LLAMA_CLI='${LLAMA_CLI}' RUNTIME_LABEL='${RUNTIME_LABEL}' MODEL_SOURCE='${MODEL_SOURCE}' MODEL_QUANT='${MODEL_QUANT}' PROMPT_B64='<omitted>' CTX='${CTX}' N_TOKENS='${N_TOKENS}' N_GPU_LAYERS='${N_GPU_LAYERS}' EXTRA_ARGS_B64='${EXTRA_ARGS_B64}' OUT_DIR='/tmp/baseline_llamacpp_${ts}' /tmp/benchmark_llamacpp_spark.sh"

REMOTE_VLLM_CMD="cat > /tmp/benchmark_vllm_spark.sh && chmod +x /tmp/benchmark_vllm_spark.sh && ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S VLLM_MODEL='${VLLM_MODEL}' PROMPT_B64='${VLLM_PROMPT_B64}' MAX_TOKENS='${MAX_TOKENS}' TENSOR_PARALLEL_SIZE='${TENSOR_PARALLEL_SIZE}' MEASURE_TTFT='${MEASURE_TTFT}' OUT_DIR='/tmp/baseline_vllm_${ts}' /tmp/benchmark_vllm_spark.sh"
REMOTE_VLLM_CMD_PRINT="cat > /tmp/benchmark_vllm_spark.sh && chmod +x /tmp/benchmark_vllm_spark.sh && ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S VLLM_MODEL='${VLLM_MODEL}' PROMPT_B64='<omitted>' MAX_TOKENS='${MAX_TOKENS}' TENSOR_PARALLEL_SIZE='${TENSOR_PARALLEL_SIZE}' MEASURE_TTFT='${MEASURE_TTFT}' OUT_DIR='/tmp/baseline_vllm_${ts}' /tmp/benchmark_vllm_spark.sh"

LLAMA_PROMPT_META="$(prompt_meta_line "$LLAMA_PROMPT")"
VLLM_PROMPT_META="$(prompt_meta_line "$VLLM_PROMPT")"

{
    echo "# Existing Runtime Baseline (Spark)"
    echo
    echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "- ds4_on_spark commit: $repo_rev"
    echo "- target: $target"
    echo "- run_ds4_macos: $RUN_DS4_MACOS"
    echo "- gates: ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN"
    echo
    echo "## Command Line (local)"
    echo
    echo '```sh'
    echo "RUN_DS4_MACOS=$RUN_DS4_MACOS ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN GPU_SAMPLE=$GPU_SAMPLE GPU_SAMPLE_INTERVAL_S=$GPU_SAMPLE_INTERVAL_S LLAMA_DIR='$LLAMA_DIR' MODEL_GGUF='$MODEL_GGUF' LLAMA_CLI='$LLAMA_CLI' RUNTIME_LABEL='$RUNTIME_LABEL' MODEL_SOURCE='$MODEL_SOURCE' MODEL_QUANT='$MODEL_QUANT' LLAMA_PROMPT='<omitted>' LLAMA_PROMPT_META='$LLAMA_PROMPT_META' CTX='$CTX' N_TOKENS='$N_TOKENS' N_GPU_LAYERS='$N_GPU_LAYERS' EXTRA_ARGS='$EXTRA_ARGS' VLLM_MODEL='$VLLM_MODEL' VLLM_PROMPT='<omitted>' VLLM_PROMPT_META='$VLLM_PROMPT_META' MAX_TOKENS='$MAX_TOKENS' TENSOR_PARALLEL_SIZE='$TENSOR_PARALLEL_SIZE' MEASURE_TTFT='$MEASURE_TTFT' DS4_DIR='$DS4_DIR' DS4_MODEL_GGUF='$DS4_MODEL_GGUF' SSH_OPTS='$SSH_OPTS' $0 $target"
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
    echo "- VLLM_MODEL (hf dir): ${VLLM_MODEL:-<unset>}"
    echo "- VLLM_PROMPT (vLLM): $(prompt_meta_line "$VLLM_PROMPT")"
    echo "- MAX_TOKENS (vLLM): ${MAX_TOKENS:-<default>}"
    echo "- TENSOR_PARALLEL_SIZE (vLLM): ${TENSOR_PARALLEL_SIZE:-<default>}"
    echo "- MEASURE_TTFT (vLLM): ${MEASURE_TTFT:-<default>}"
    echo "- DS4_DIR (macos): ${DS4_DIR:-<default local>}"
    echo "- DS4_MODEL_GGUF (macos): ${DS4_MODEL_GGUF:-<unset>}"
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
    echo "vLLM:"
    echo
    echo '```sh'
    echo "ssh $SSH_OPTS $target \"$REMOTE_VLLM_CMD_PRINT\" < scripts/benchmark_vllm_spark.sh"
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

echo "== running llama.cpp benchmark script on spark (may be gated) =="
rc_llama=0
ssh $SSH_OPTS "$target" "$REMOTE_LLAMA_CMD" <"$repo_root/scripts/benchmark_llamacpp_spark.sh" \
    >"$OUT_DIR/remote_llamacpp_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_stderr.txt" || rc_llama=$?

{
    echo "## llama.cpp (Spark)"
    echo
    echo "- ssh_exit_code: $rc_llama"
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

echo "== running vLLM probe script on spark =="
rc_vllm=0
ssh $SSH_OPTS "$target" "$REMOTE_VLLM_CMD" <"$repo_root/scripts/benchmark_vllm_spark.sh" \
    >"$OUT_DIR/remote_vllm_stdout.txt" 2>"$OUT_DIR/remote_vllm_stderr.txt" || rc_vllm=$?

{
    echo "## vLLM (Spark)"
    echo
    echo "- ssh_exit_code: $rc_vllm"
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
