#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"
REMOTE_BENCH_ENV="${REMOTE_BENCH_ENV:-}"
REMOTE_LLAMA_ENV="${REMOTE_LLAMA_ENV:-$REMOTE_BENCH_ENV}"
REMOTE_VLLM_ENV="${REMOTE_VLLM_ENV:-$REMOTE_BENCH_ENV}"
REMOTE_MTP_SIDECAR_ENV="${REMOTE_MTP_SIDECAR_ENV:-$REMOTE_BENCH_ENV}"
REMOTE_MTP_SIDECAR_ARGS="${REMOTE_MTP_SIDECAR_ARGS:---json --expect-deepseek-v4-flash}"
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
    echo
    echo "## Safety Gates"
    echo
    echo "This run script only executes what the remote benchmark scripts allow."
    echo "Set gates on the Spark side via env vars:"
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
    echo "Remote MTP sidecar env:"
    echo
    echo "Used when running the sidecar contract probe (optional; set MTP_SIDECAR_GGUF on Spark)."
    echo "Do not put secrets in REMOTE_* env values; this report records them."
    echo
    echo '```'
    echo "$REMOTE_MTP_SIDECAR_ENV"
    echo '```'
    echo
    echo "Remote MTP sidecar args:"
    echo
    echo '```'
    echo "$REMOTE_MTP_SIDECAR_ARGS"
    echo '```'
    echo
    echo "## Spark Probe"
    echo
    echo '```'
    ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true'
    echo '```'
    echo
} >"$REPORT_MD"

echo "== running llama.cpp benchmark script on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_spark.sh && chmod +x /tmp/benchmark_llamacpp_spark.sh && $REMOTE_LLAMA_ENV /tmp/benchmark_llamacpp_spark.sh" <"$repo_root/scripts/benchmark_llamacpp_spark.sh" \
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

echo "== running MTP sidecar contract probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_probe_mtp_sidecar.py && chmod +x /tmp/model_contract_probe_mtp_sidecar.py && $REMOTE_MTP_SIDECAR_ENV sh -lc '
set -eu
if [ \"${ALLOW_RUN:-0}\" != \"1\" ]; then
  echo \"run skipped: set ALLOW_RUN=1 on Spark to enable\"
  exit 0
fi
if [ \"${MTP_SIDECAR_GGUF:-}\" = \"\" ]; then
  echo \"run skipped: set MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf\"
  exit 0
fi
if [ ! -r \"${MTP_SIDECAR_GGUF}\" ]; then
  echo \"run skipped: MTP_SIDECAR_GGUF not readable: ${MTP_SIDECAR_GGUF}\"
  exit 0
fi
python3 /tmp/model_contract_probe_mtp_sidecar.py --path \"${MTP_SIDECAR_GGUF}\" '"$REMOTE_MTP_SIDECAR_ARGS"'
' " <"$repo_root/scripts/model_contract_probe_mtp_sidecar.py" \
    >"$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" 2>"$OUT_DIR/remote_mtp_sidecar_probe_stderr.txt" || true

{
    echo "## MTP sidecar contract probe (Spark)"
    echo
    echo "This is a metadata-only sanity check for DS4-tuned MTP sidecars (e.g. `general.architecture=deepseek4_mtp_support` + 32 `mtp.0.*` tensors)."
    echo "It does not require loading the trunk GGUF or reading tensor payloads into RAM."
    echo
    echo "Summary (best-effort):"
    echo
    echo '```'
    sed -n '1,120p' "$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" || true
    echo '```'
    echo
    echo "Full logs:"
    echo
    echo "- stdout: $OUT_DIR/remote_mtp_sidecar_probe_stdout.txt"
    echo "- stderr: $OUT_DIR/remote_mtp_sidecar_probe_stderr.txt"
    echo
} >>"$REPORT_MD"

echo "== running vLLM probe script on spark =="
ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_vllm_spark.sh && chmod +x /tmp/benchmark_vllm_spark.sh && $REMOTE_VLLM_ENV /tmp/benchmark_vllm_spark.sh" <"$repo_root/scripts/benchmark_vllm_spark.sh" \
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

echo "done: $REPORT_MD"
