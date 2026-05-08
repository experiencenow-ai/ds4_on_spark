#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
RUN_DS4_MACOS="${RUN_DS4_MACOS:-0}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"

mkdir -p "$OUT_DIR"

echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -d "$repo_root/.git" ]; then
    repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/baseline_existing_runtime.md"

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

{
    echo "# Existing Runtime Baseline (Spark)"
    echo
    echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "- ds4_on_spark commit: $repo_rev"
    echo "- target: $target"
    echo "- run_ds4_macos: $RUN_DS4_MACOS"
    echo
    echo "## Safety Gates"
    echo
    echo "This run script only executes what the remote benchmark scripts allow."
    echo "Set gates via env vars (passed to remote runs for this session):"
    echo
    echo "- ALLOW_FETCH=1"
    echo "- ALLOW_BUILD=1"
    echo "- ALLOW_RUN=1"
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
ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_spark.sh && chmod +x /tmp/benchmark_llamacpp_spark.sh && ALLOW_FETCH=$ALLOW_FETCH ALLOW_BUILD=$ALLOW_BUILD ALLOW_RUN=$ALLOW_RUN /tmp/benchmark_llamacpp_spark.sh" <"$repo_root/scripts/benchmark_llamacpp_spark.sh" \
    >"$OUT_DIR/remote_llamacpp_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_stderr.txt" || true

{
    echo "## llama.cpp (Spark)"
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
ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_vllm_spark.sh && chmod +x /tmp/benchmark_vllm_spark.sh && ALLOW_RUN=$ALLOW_RUN /tmp/benchmark_vllm_spark.sh" <"$repo_root/scripts/benchmark_vllm_spark.sh" \
    >"$OUT_DIR/remote_vllm_stdout.txt" 2>"$OUT_DIR/remote_vllm_stderr.txt" || true

{
    echo "## vLLM (Spark)"
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

    (OUT_DIR="$DS4_OUT_DIR" ALLOW_FETCH="$ALLOW_FETCH" ALLOW_BUILD="$ALLOW_BUILD" ALLOW_RUN="$ALLOW_RUN" "$repo_root/scripts/benchmark_ds4_macos.sh") \
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
