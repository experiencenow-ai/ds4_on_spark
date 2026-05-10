#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_sidecar_probe}"
REMOTE_MTP_SIDECAR_ENV="${REMOTE_MTP_SIDECAR_ENV:-}"
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

REPORT_MD="$OUT_DIR/mtp_sidecar_probe_spark.md"

{
	echo "# MTP Sidecar Contract Probe (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo
	echo "## Safety Gates"
	echo
	echo "This runner only executes the probe when the Spark side allows it."
	echo "Set env vars on Spark via REMOTE_MTP_SIDECAR_ENV:"
	echo
	echo "- ALLOW_RUN=1"
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf"
	echo
	echo "Remote MTP sidecar env:"
	echo
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
	echo "## Results"
	echo
	echo "This is a metadata-only sanity check for DS4-tuned MTP sidecars (e.g. `general.architecture=deepseek4_mtp_support` + 32 `mtp.0.*` tensors)."
	echo "It does not require loading the trunk GGUF or reading tensor payloads into RAM."
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_mtp_sidecar_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/remote_mtp_sidecar_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_mtp_sidecar_probe_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"

