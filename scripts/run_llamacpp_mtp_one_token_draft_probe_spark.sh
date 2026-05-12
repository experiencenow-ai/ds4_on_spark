#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_llamacpp_mtp_one_token_probe}"
REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV="${REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV:-}"
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

PATCH_LOCAL="$repo_root/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch"
HELPER_LOCAL="$repo_root/scripts/llamacpp_mtp_one_token_draft_probe_patch.sh"

REPORT_MD="$OUT_DIR/llamacpp_mtp_one_token_draft_probe_spark.md"

{
	echo "# llama.cpp One-Token MTP Draft Probe (Spark)"
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
	echo "Set env vars on Spark via REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV:"
	echo
	echo "- ALLOW_FETCH=1 (clone the llama.cpp fork if missing)"
	echo "- ALLOW_PATCH=1 (apply the one-token probe patch)"
	echo "- ALLOW_BUILD=1 (build llama-ds4-mtp-one-token-draft-probe)"
	echo "- ALLOW_RUN=1 (run the probe; loads trunk GGUF)"
	echo
	echo "Required when ALLOW_RUN=1 (Spark-side env vars):"
	echo
	echo "- TRUNK_GGUF=/abs/path/to/trunk.gguf (defaults to Spark0-staged antirez IQ2XXS trunk if readable)"
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (defaults to Spark0-staged sidecar if readable)"
	echo
	echo "Optional Spark-side env vars:"
	echo
	echo "- LLAMA_DIR=$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark"
	echo "- LLAMA_REPO=https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git"
	echo "- LLAMA_COMMIT=9222e55"
	echo "- PROMPT='Hello.'"
	echo "- SEED=1234"
	echo "- LOAD_SIDECAR_WEIGHTS=1 (loads sidecar tensor payloads into RAM)"
	echo
	echo "Remote env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo '```'
	echo "$REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV"
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

echo "== verifying llama.cpp one-token probe patch (local) =="
python3 "$repo_root/scripts/verify_llamacpp_mtp_one_token_draft_probe_patch.py" --patch "$PATCH_LOCAL" \
	>"$OUT_DIR/local_patch_verify_stdout.txt" 2>"$OUT_DIR/local_patch_verify_stderr.txt" || true

{
	echo "## Patch Verification (local)"
	echo
	echo "Command:"
	echo
	echo '```'
	echo "python3 scripts/verify_llamacpp_mtp_one_token_draft_probe_patch.py --patch $PATCH_LOCAL"
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
	--patch-kind one-token-binder \
	>"$OUT_DIR/local_tensor_list_verify_stdout.txt" 2>"$OUT_DIR/local_tensor_list_verify_stderr.txt" || true

{
	echo "## Tensor List Consistency (local)"
	echo
	echo "Command:"
	echo
	echo '```'
	echo "python3 scripts/verify_mtp_sidecar_expected_tensors_consistency.py --python-probe scripts/model_contract_probe_mtp_sidecar.py --patch $PATCH_LOCAL --patch-kind one-token-binder"
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

echo "== running llama.cpp-side one-token MTP draft probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/llamacpp_mtp_one_token_draft_probe_patch.sh && chmod +x /tmp/llamacpp_mtp_one_token_draft_probe_patch.sh" \
	<"$HELPER_LOCAL" \
	>"$OUT_DIR/remote_upload_helper_stdout.txt" 2>"$OUT_DIR/remote_upload_helper_stderr.txt" || true

ssh $SSH_OPTS "$target" "cat > /tmp/llamacpp_mtp_one_token_draft_probe.patch" \
	<"$PATCH_LOCAL" \
	>"$OUT_DIR/remote_upload_patch_stdout.txt" 2>"$OUT_DIR/remote_upload_patch_stderr.txt" || true

ssh $SSH_OPTS "$target" "$REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV sh -lc '
set -eu
PATCH_FILE=\"/tmp/llamacpp_mtp_one_token_draft_probe.patch\"
export PATCH_FILE
JSON_ONLY=1
export JSON_ONLY
/tmp/llamacpp_mtp_one_token_draft_probe_patch.sh
' " \
	>"$OUT_DIR/remote_probe_stdout.txt" 2>"$OUT_DIR/remote_probe_stderr.txt" || true

python3 - "$OUT_DIR/remote_probe_stdout.txt" "$OUT_DIR/mtp_one_token_probe.json" >"$OUT_DIR/mtp_one_token_probe_parse.json" 2>/dev/null <<'PY' || true
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

out = {"ok": False, "errors": [], "probe_ok": None}
try:
    doc = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(doc, dict):
        dst.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        out["probe_ok"] = bool(doc.get("ok", False))
        out["ok"] = out["probe_ok"]
        errs = doc.get("errors", [])
        if isinstance(errs, list):
            out["errors"] = [str(x) for x in errs[:64]]
    else:
        out["errors"].append("stdout JSON top-level is not an object")
except Exception as e:
    out["errors"].append(f"failed to parse stdout as JSON: {e}")
print(json.dumps(out, indent=2, sort_keys=True))
PY

echo "== validating one-token probe JSON (local; best-effort) =="
if [ -r "$OUT_DIR/mtp_one_token_probe.json" ]; then
	python3 "$repo_root/scripts/model_contract_validate_mtp_one_token_draft_probe.py" \
		--probe-json "$OUT_DIR/mtp_one_token_probe.json" \
		--json \
		>"$OUT_DIR/mtp_one_token_probe_validate.json" 2>"$OUT_DIR/mtp_one_token_probe_validate_stderr.txt" || true
else
	printf '%s\n' "{\"ok\":false,\"skipped\":true,\"reason\":\"mtp_one_token_probe.json missing\"}" >"$OUT_DIR/mtp_one_token_probe_validate.json"
	printf '%s\n' "" >"$OUT_DIR/mtp_one_token_probe_validate_stderr.txt"
fi

{
	echo "## Results"
	echo
	echo "This runner targets the **llama.cpp-side** one-token probe (`llama-ds4-mtp-one-token-draft-probe`)."
	echo "It can load the trunk GGUF when `ALLOW_RUN=1` is set, so keep it gated and coordinate with the baseline runtime loop."
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,80p' "$OUT_DIR/remote_probe_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Local validation (best-effort):"
	echo
	echo '```'
	cat "$OUT_DIR/mtp_one_token_probe_validate.json" 2>/dev/null || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/remote_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_probe_stderr.txt"
	echo "- parsed JSON: $OUT_DIR/mtp_one_token_probe.json"
	echo "- parse status: $OUT_DIR/mtp_one_token_probe_parse.json"
	echo "- validate JSON: $OUT_DIR/mtp_one_token_probe_validate.json"
	echo "- validate stderr: $OUT_DIR/mtp_one_token_probe_validate_stderr.txt"
	echo "- upload helper stderr: $OUT_DIR/remote_upload_helper_stderr.txt"
	echo "- upload patch stderr: $OUT_DIR/remote_upload_patch_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"

