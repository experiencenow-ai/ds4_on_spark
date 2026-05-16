#!/usr/bin/env sh
set -eu

target="${1:-spark0@172.16.11.228}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_antirez_ds4_mtp_multitoken_acceptance}"
REMOTE_ANTIREZ_DS4_MTP_ACCEPT_ENV="${REMOTE_ANTIREZ_DS4_MTP_ACCEPT_ENV:-}"
BASELINE_GENERATION_TPS="${BASELINE_GENERATION_TPS:-}"
MODEL_ID="${MODEL_ID:-DeepSeek-V4-Flash-IQ2XXS-chat-v2}"
RUNTIME_ID="${RUNTIME_ID:-antirez/ds4@3630e64+cuda-mtp}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph. Keep it concise, covering key features: append-only log, consumer groups, blocking reads, message persistence, and}"
PROMPT_HASH="${PROMPT_HASH:-}"
MTP_DRAFT="${MTP_DRAFT:-2}"
MTP_MARGIN="${MTP_MARGIN:-0}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ID="${RUN_ID:-$ts-mtp-draft-$MTP_DRAFT}"
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

HELPER_LOCAL="$repo_root/scripts/antirez_ds4_mtp_acceptance_probe_patch.sh"
PATCH_Q4K_LOCAL="$repo_root/docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch"
PATCH_CACHE_LOCAL="$repo_root/docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch"
PATCH_VERIFY_LOCAL="${PATCH_VERIFY_LOCAL:-$repo_root/docs/antirez-patches/ds4-3630e64-mtp-target-suffix-verify-k2.patch}"
EXTRACTOR_LOCAL="$repo_root/scripts/extract_antirez_ds4_mtp_conf_log.py"
SLOWPATH_LOCAL="$repo_root/scripts/build_ds4_mtp_slowpath_report.py"
SLOWPATH_VALIDATOR_LOCAL="$repo_root/scripts/validate_ds4_mtp_slowpath.py"

REPORT_MD="$OUT_DIR/antirez_ds4_mtp_multitoken_acceptance_probe_spark.md"

{
	echo "# antirez/ds4 MTP multi-token acceptance probe (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo
	echo "## Safety gates"
	echo
	echo "This runner is gated and does not clone/patch/build/run antirez/ds4 unless Spark-side env enables it."
	echo
	echo "Set env vars on Spark via REMOTE_ANTIREZ_DS4_MTP_ACCEPT_ENV:"
	echo
	echo "- ALLOW_FETCH=1 (clone antirez/ds4 if missing)"
	echo "- ALLOW_CLEAN=1 (git reset --hard && git clean -fd in DS4_DIR before patch)"
	echo "- ALLOW_PATCH=1 (apply the ds4 CUDA + MTP patches)"
	echo "- ALLOW_BUILD=1 (build ds4 via Makefile/nvcc)"
	echo "- ALLOW_RUN=1 (run the probe; loads trunk GGUF + MTP sidecar GGUF)"
	echo
	echo "Remote env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo '```'
	echo "$REMOTE_ANTIREZ_DS4_MTP_ACCEPT_ENV"
	echo '```'
	echo
	echo "## Spark host info"
	echo
	echo '```'
	ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true'
	echo '```'
	echo
	echo "## Patches"
	echo
	echo "- $PATCH_Q4K_LOCAL"
	echo "- $PATCH_CACHE_LOCAL"
	echo "- $PATCH_VERIFY_LOCAL"
	echo
} >"$REPORT_MD"

if [ ! -r "$HELPER_LOCAL" ]; then
	echo "helper not readable: $HELPER_LOCAL"
	exit 2
fi
if [ ! -r "$PATCH_Q4K_LOCAL" ] || [ ! -r "$PATCH_CACHE_LOCAL" ] || [ ! -r "$PATCH_VERIFY_LOCAL" ] || [ ! -r "$EXTRACTOR_LOCAL" ] || [ ! -r "$SLOWPATH_LOCAL" ] || [ ! -r "$SLOWPATH_VALIDATOR_LOCAL" ]; then
	echo "missing local file(s): helper/patches/extractor/slowpath"
	exit 3
fi

echo "== uploading helper + patches to spark =="
ssh $SSH_OPTS "$target" 'cat > /tmp/antirez_ds4_mtp_multitoken_acceptance_probe.sh && chmod +x /tmp/antirez_ds4_mtp_multitoken_acceptance_probe.sh' \
	<"$HELPER_LOCAL" \
	>"$OUT_DIR/remote_upload_helper_stdout.txt" 2>"$OUT_DIR/remote_upload_helper_stderr.txt" || true
ssh $SSH_OPTS "$target" 'cat > /tmp/ds4_cuda_mtp_q4k_and_sidecar_map.patch' \
	<"$PATCH_Q4K_LOCAL" \
	>"$OUT_DIR/remote_upload_patch_q4k_stdout.txt" 2>"$OUT_DIR/remote_upload_patch_q4k_stderr.txt" || true
ssh $SSH_OPTS "$target" 'cat > /tmp/ds4_cuda_multi_model_cache.patch' \
	<"$PATCH_CACHE_LOCAL" \
	>"$OUT_DIR/remote_upload_patch_cache_stdout.txt" 2>"$OUT_DIR/remote_upload_patch_cache_stderr.txt" || true
ssh $SSH_OPTS "$target" 'cat > /tmp/ds4_mtp_target_suffix_verify_k2.patch' \
	<"$PATCH_VERIFY_LOCAL" \
	>"$OUT_DIR/remote_upload_patch_verify_stdout.txt" 2>"$OUT_DIR/remote_upload_patch_verify_stderr.txt" || true

echo "== running antirez/ds4 acceptance probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "$REMOTE_ANTIREZ_DS4_MTP_ACCEPT_ENV sh -lc '
set -eu
PATCH_Q4K_FILE=/tmp/ds4_cuda_mtp_q4k_and_sidecar_map.patch
PATCH_CACHE_FILE=/tmp/ds4_cuda_multi_model_cache.patch
PATCH_VERIFY_FILE=/tmp/ds4_mtp_target_suffix_verify_k2.patch
export PATCH_Q4K_FILE PATCH_CACHE_FILE PATCH_VERIFY_FILE
/tmp/antirez_ds4_mtp_multitoken_acceptance_probe.sh
' " \
	>"$OUT_DIR/remote_probe_stdout.txt" 2>"$OUT_DIR/remote_probe_stderr.txt" || true

cat "$OUT_DIR/remote_probe_stdout.txt" "$OUT_DIR/remote_probe_stderr.txt" >"$OUT_DIR/remote_probe_log.txt" 2>/dev/null || true

echo "== extracting acceptance summary (local) =="
python3 "$EXTRACTOR_LOCAL" --in "$OUT_DIR/remote_probe_stdout.txt" --in "$OUT_DIR/remote_probe_stderr.txt" \
	--out-json "$OUT_DIR/acceptance_summary.json" \
	--out-jsonl "$OUT_DIR/acceptance_events.jsonl" \
	>"$OUT_DIR/acceptance_summary_stdout.txt" 2>"$OUT_DIR/acceptance_summary_stderr.txt" || true

echo "== building slow-path telemetry (local) =="
if [ "$BASELINE_GENERATION_TPS" != "" ]; then
	python3 "$SLOWPATH_LOCAL" \
		--mtp-log "$OUT_DIR/remote_probe_stdout.txt" \
		--mtp-log "$OUT_DIR/remote_probe_stderr.txt" \
		--baseline-generation-tps "$BASELINE_GENERATION_TPS" \
		--run-id "$RUN_ID" \
		--model-id "$MODEL_ID" \
		--runtime-id "$RUNTIME_ID" \
		--prompt "$PROMPT" \
		--prompt-hash "$PROMPT_HASH" \
		--mtp-draft "$MTP_DRAFT" \
		--mtp-margin "$MTP_MARGIN" \
		--out-json "$OUT_DIR/mtp_slowpath.json" \
		>"$OUT_DIR/mtp_slowpath_stdout.txt" 2>"$OUT_DIR/mtp_slowpath_stderr.txt" || true
else
	python3 "$SLOWPATH_LOCAL" \
		--mtp-log "$OUT_DIR/remote_probe_stdout.txt" \
		--mtp-log "$OUT_DIR/remote_probe_stderr.txt" \
		--run-id "$RUN_ID" \
		--model-id "$MODEL_ID" \
		--runtime-id "$RUNTIME_ID" \
		--prompt "$PROMPT" \
		--prompt-hash "$PROMPT_HASH" \
		--mtp-draft "$MTP_DRAFT" \
		--mtp-margin "$MTP_MARGIN" \
		--out-json "$OUT_DIR/mtp_slowpath.json" \
		>"$OUT_DIR/mtp_slowpath_stdout.txt" 2>"$OUT_DIR/mtp_slowpath_stderr.txt" || true
fi
python3 "$SLOWPATH_VALIDATOR_LOCAL" "$OUT_DIR/mtp_slowpath.json" \
	>"$OUT_DIR/mtp_slowpath_validate.json" 2>"$OUT_DIR/mtp_slowpath_validate_stderr.txt" || true

{
	echo "## Results"
	echo
	echo "Artifacts:"
	echo
	echo "- report: $REPORT_MD"
	echo "- stdout: $OUT_DIR/remote_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_probe_stderr.txt"
	echo "- mixed log: $OUT_DIR/remote_probe_log.txt"
	echo "- acceptance summary: $OUT_DIR/acceptance_summary.json"
	echo "- acceptance events JSONL: $OUT_DIR/acceptance_events.jsonl"
	echo "- slow-path telemetry: $OUT_DIR/mtp_slowpath.json"
	echo "- slow-path validator: $OUT_DIR/mtp_slowpath_validate.json"
	echo "- extractor stderr: $OUT_DIR/acceptance_summary_stderr.txt"
	echo
	echo "Acceptance summary (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/acceptance_summary.json" 2>/dev/null || true
	echo '```'
	echo
	echo "Slow-path telemetry (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/mtp_slowpath.json" 2>/dev/null || true
	echo '```'
	echo
} >>"$REPORT_MD"

python3 - "$OUT_DIR" "$REPORT_MD" 2>/dev/null <<'PY' || true
import json
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
report_md = Path(sys.argv[2])

def read_json(p: Path):
	try:
		return json.loads(p.read_text(encoding="utf-8"))
	except Exception:
		return None

summary = read_json(out_dir / "acceptance_summary.json") or {}

doc = {
	"ok": bool(summary.get("ok", False)),
	"artifacts": {
		"report_md": str(report_md),
		"stdout": str(out_dir / "remote_probe_stdout.txt"),
		"stderr": str(out_dir / "remote_probe_stderr.txt"),
		"log": str(out_dir / "remote_probe_log.txt"),
		"acceptance_summary_json": str(out_dir / "acceptance_summary.json"),
		"acceptance_events_jsonl": str(out_dir / "acceptance_events.jsonl"),
		"mtp_slowpath_json": str(out_dir / "mtp_slowpath.json"),
		"mtp_slowpath_validate_json": str(out_dir / "mtp_slowpath_validate.json"),
	},
	"summary": summary,
}
(out_dir / "summary.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "done: $REPORT_MD"
