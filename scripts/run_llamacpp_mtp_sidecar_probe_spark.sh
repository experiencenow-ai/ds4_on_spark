#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_llamacpp_mtp_sidecar_probe}"
REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV="${REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV:-}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"

mkdir -p "$OUT_DIR"
echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -d "$repo_root/.codex_git" ]; then
	repo_rev="$(GIT_DIR="$repo_root/.codex_git" GIT_WORK_TREE="$repo_root" git rev-parse HEAD 2>/dev/null || echo unknown)"
elif [ -d "$repo_root/.git2/.git" ]; then
	repo_rev="$(GIT_DIR="$repo_root/.git2/.git" GIT_WORK_TREE="$repo_root" git rev-parse HEAD 2>/dev/null || echo unknown)"
elif [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

PATCH_LOCAL="$repo_root/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-sidecar-probe.patch"
HELPER_LOCAL="$repo_root/scripts/llamacpp_mtp_sidecar_probe_patch.sh"

REPORT_MD="$OUT_DIR/llamacpp_mtp_sidecar_probe_spark.md"

{
	echo "# llama.cpp MTP Sidecar Probe (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo "- patch: $PATCH_LOCAL"
	echo
	echo "## Safety Gates"
	echo
	echo "This runner is **gated** and does not clone/patch/build/run llama.cpp unless Spark-side env enables it."
	echo
	echo "Set env vars on Spark via REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV:"
	echo
	echo "- ALLOW_FETCH=1 (clone the llama.cpp fork if missing)"
	echo "- ALLOW_PATCH=1 (apply the sidecar probe patch)"
	echo "- ALLOW_BUILD=1 (build llama-ds4-mtp-sidecar-probe)"
	echo "- ALLOW_RUN=1 (run the probe against an already-staged sidecar GGUF)"
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (optional; defaults to Spark0-staged artifact if present)"
	echo
	echo "Optional Spark-side env vars:"
	echo
	echo "- LLAMA_DIR=$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark"
	echo "- LLAMA_REPO=https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git"
	echo "- LLAMA_COMMIT=94073e2"
	echo "- PAYLOAD_SAMPLE_BYTES=64"
	echo "- LOAD_WEIGHTS=1"
	echo
	echo "Remote env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo '```'
	echo "$REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV"
	echo '```'
	echo
	echo "## Spark Host Info"
	echo
	echo '```'
	ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true'
	echo '```'
	echo
} >"$REPORT_MD"

if [ ! -r "$PATCH_LOCAL" ]; then
	echo "patch not readable: $PATCH_LOCAL"
	exit 2
fi
if [ ! -r "$HELPER_LOCAL" ]; then
	echo "helper not readable: $HELPER_LOCAL"
	exit 3
fi

echo "== verifying llama.cpp probe patch (local) =="
python3 "$repo_root/scripts/verify_llamacpp_mtp_sidecar_probe_patch.py" --patch "$PATCH_LOCAL" \
	>"$OUT_DIR/local_patch_verify_stdout.txt" 2>"$OUT_DIR/local_patch_verify_stderr.txt" || true

{
	echo "## Patch Verification (local)"
	echo
	echo "Command:"
	echo
	echo '```'
	echo "python3 scripts/verify_llamacpp_mtp_sidecar_probe_patch.py --patch $PATCH_LOCAL"
	echo '```'
	echo
	echo "Stdout:"
	echo
	echo '```'
	sed -n '1,60p' "$OUT_DIR/local_patch_verify_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr:"
	echo
	echo '```'
	sed -n '1,60p' "$OUT_DIR/local_patch_verify_stderr.txt" || true
	echo '```'
	echo
} >>"$REPORT_MD"

echo "== verifying expected tensor list consistency (local) =="
python3 "$repo_root/scripts/verify_mtp_sidecar_expected_tensors_consistency.py" \
	--python-probe "$repo_root/scripts/model_contract_probe_mtp_sidecar.py" \
	--patch "$PATCH_LOCAL" \
	>"$OUT_DIR/local_tensor_list_verify_stdout.txt" 2>"$OUT_DIR/local_tensor_list_verify_stderr.txt" || true

{
	echo "## Tensor List Consistency (local)"
	echo
	echo "Command:"
	echo
	echo '```'
	echo "python3 scripts/verify_mtp_sidecar_expected_tensors_consistency.py --python-probe scripts/model_contract_probe_mtp_sidecar.py --patch $PATCH_LOCAL"
	echo '```'
	echo
	echo "Stdout:"
	echo
	echo '```'
	sed -n '1,60p' "$OUT_DIR/local_tensor_list_verify_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr:"
	echo
	echo '```'
	sed -n '1,60p' "$OUT_DIR/local_tensor_list_verify_stderr.txt" || true
	echo '```'
	echo
} >>"$REPORT_MD"

echo "== running llama.cpp-side MTP sidecar probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/llamacpp_mtp_sidecar_probe_patch.sh && chmod +x /tmp/llamacpp_mtp_sidecar_probe_patch.sh" \
	<"$HELPER_LOCAL" \
	>"$OUT_DIR/remote_llamacpp_mtp_sidecar_upload_helper_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_mtp_sidecar_upload_helper_stderr.txt" || true

ssh $SSH_OPTS "$target" "cat > /tmp/llamacpp_mtp_sidecar_probe.patch" \
	<"$PATCH_LOCAL" \
	>"$OUT_DIR/remote_llamacpp_mtp_sidecar_upload_patch_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_mtp_sidecar_upload_patch_stderr.txt" || true

ssh $SSH_OPTS "$target" "$REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV sh -lc '
set -eu
if [ \"${MTP_SIDECAR_GGUF:-}\" = \"\" ]; then
  for p in \
    /home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /home/spark1/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /home/spark/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /mnt/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf
  do
    if [ -r \"$p\" ]; then
      MTP_SIDECAR_GGUF=\"$p\"
      export MTP_SIDECAR_GGUF
      echo \"defaulted MTP_SIDECAR_GGUF=$p\" 1>&2
      break
    fi
  done
fi
PATCH_FILE=\"/tmp/llamacpp_mtp_sidecar_probe.patch\"
export PATCH_FILE
/tmp/llamacpp_mtp_sidecar_probe_patch.sh
' " \
	>"$OUT_DIR/remote_llamacpp_mtp_sidecar_probe_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_mtp_sidecar_probe_stderr.txt" || true

{
	echo "## Results"
	echo
	echo "This runner targets the **llama.cpp-side** metadata-only probe (`llama-ds4-mtp-sidecar-probe`)."
	echo "It does not require loading the trunk GGUF."
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_llamacpp_mtp_sidecar_probe_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_llamacpp_mtp_sidecar_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/remote_llamacpp_mtp_sidecar_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_llamacpp_mtp_sidecar_probe_stderr.txt"
	echo "- upload helper stderr: $OUT_DIR/remote_llamacpp_mtp_sidecar_upload_helper_stderr.txt"
	echo "- upload patch stderr: $OUT_DIR/remote_llamacpp_mtp_sidecar_upload_patch_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
