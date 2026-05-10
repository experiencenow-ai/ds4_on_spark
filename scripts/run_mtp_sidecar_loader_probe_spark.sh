#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_sidecar_loader_probe}"

REMOTE_MTP_SIDECAR_ENV="${REMOTE_MTP_SIDECAR_ENV:-}"
REMOTE_MTP_SIDECAR_ARGS="${REMOTE_MTP_SIDECAR_ARGS:---json --expect-deepseek-v4-flash --payload-sample-bytes 64}"

REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV="${REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV:-}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"

mkdir -p "$OUT_DIR"
echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -d "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

PATCH_LOCAL="$repo_root/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-sidecar-probe.patch"
HELPER_LOCAL="$repo_root/scripts/llamacpp_mtp_sidecar_probe_patch.sh"

REPORT_MD="$OUT_DIR/mtp_sidecar_loader_probe_spark.md"

{
	echo "# MTP Sidecar Loader Probe (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo
	echo "## What This Does"
	echo
	echo "This runner performs two *independent* validations against the same already-staged sidecar GGUF on Spark:"
	echo
	echo "1) **Contract probe (Python)**: reads GGUF metadata + tensor directory (and samples payload bytes) to validate the 32 `mtp.0.*` tensors."
	echo "2) **Loader probe (llama.cpp)**: builds/runs `llama-ds4-mtp-sidecar-probe` and (optionally) loads the sidecar tensor blob into RAM via `--load-weights`."
	echo
	echo "It does **not** load the trunk model GGUF."
	echo
	echo "## Safety Gates"
	echo
	echo "This runner is gated. Nothing runs on Spark unless the Spark-side env enables it."
	echo
	echo "### Contract probe gates (Python)"
	echo
	echo "Set Spark-side env vars via REMOTE_MTP_SIDECAR_ENV:"
	echo
	echo "- ALLOW_RUN=1"
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf"
	echo
	echo "Remote contract probe env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo '```'
	echo "$REMOTE_MTP_SIDECAR_ENV"
	echo '```'
	echo
	echo "Remote contract probe args (recorded):"
	echo
	echo '```'
	echo "$REMOTE_MTP_SIDECAR_ARGS"
	echo '```'
	echo
	echo "### Loader probe gates (llama.cpp)"
	echo
	echo "Set Spark-side env vars via REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV:"
	echo
	echo "- ALLOW_FETCH=1 (clone the llama.cpp fork if missing)"
	echo "- ALLOW_PATCH=1 (apply the sidecar probe patch)"
	echo "- ALLOW_BUILD=1 (build llama-ds4-mtp-sidecar-probe)"
	echo "- ALLOW_RUN=1 (run the probe against an already-staged sidecar GGUF)"
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf"
	echo
	echo "Optional Spark-side env vars:"
	echo
	echo "- LLAMA_DIR=$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark"
	echo "- LLAMA_REPO=https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git"
	echo "- LLAMA_COMMIT=9222e55"
	echo "- PAYLOAD_SAMPLE_BYTES=64"
	echo "- LOAD_WEIGHTS=1"
	echo
	echo "Remote loader probe env (recorded):"
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

echo "== running Python MTP sidecar contract probe on spark (may be gated) =="
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
	>"$OUT_DIR/remote_contract_probe_stdout.txt" 2>"$OUT_DIR/remote_contract_probe_stderr.txt" || true

{
	echo "## Contract Probe Results (Python)"
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_contract_probe_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_contract_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/remote_contract_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_contract_probe_stderr.txt"
	echo
} >>"$REPORT_MD"

if [ ! -r "$PATCH_LOCAL" ]; then
	echo "patch not readable: $PATCH_LOCAL"
	exit 2
fi
if [ ! -r "$HELPER_LOCAL" ]; then
	echo "helper not readable: $HELPER_LOCAL"
	exit 3
fi

echo "== running llama.cpp-side MTP sidecar loader probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/llamacpp_mtp_sidecar_probe_patch.sh && chmod +x /tmp/llamacpp_mtp_sidecar_probe_patch.sh" \
	<"$HELPER_LOCAL" \
	>"$OUT_DIR/remote_loader_upload_helper_stdout.txt" 2>"$OUT_DIR/remote_loader_upload_helper_stderr.txt" || true

ssh $SSH_OPTS "$target" "cat > /tmp/llamacpp_mtp_sidecar_probe.patch" \
	<"$PATCH_LOCAL" \
	>"$OUT_DIR/remote_loader_upload_patch_stdout.txt" 2>"$OUT_DIR/remote_loader_upload_patch_stderr.txt" || true

ssh $SSH_OPTS "$target" "$REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV sh -lc '
set -eu
PATCH_FILE=\"/tmp/llamacpp_mtp_sidecar_probe.patch\"
export PATCH_FILE
/tmp/llamacpp_mtp_sidecar_probe_patch.sh
' " \
	>"$OUT_DIR/remote_loader_probe_stdout.txt" 2>"$OUT_DIR/remote_loader_probe_stderr.txt" || true

{
	echo "## Loader Probe Results (llama.cpp)"
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_loader_probe_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_loader_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/remote_loader_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_loader_probe_stderr.txt"
	echo "- upload helper stderr: $OUT_DIR/remote_loader_upload_helper_stderr.txt"
	echo "- upload patch stderr: $OUT_DIR/remote_loader_upload_patch_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
