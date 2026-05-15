#!/usr/bin/env sh
set -eu

target="${1:-spark0@172.16.11.228}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_llamacpp_mtp_one_token_probe}"
REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV="${REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV:-}"
PROMPT_FILE_LOCAL="${PROMPT_FILE_LOCAL:-}"
LLAMA_COMMIT="${LLAMA_COMMIT:-94073e2}"
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

HELPER_LOCAL="$repo_root/scripts/llamacpp_mtp_one_token_draft_probe_patch.sh"
PATCH_LOCAL="${PATCH_LOCAL:-}"
if [ "$PATCH_LOCAL" = "" ]; then
	PATCH_LOCAL="$repo_root/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-${LLAMA_COMMIT}-mtp-one-token-draft-probe-skeleton.patch"
fi
if [ ! -r "$PATCH_LOCAL" ] && [ "$LLAMA_COMMIT" = "94073e2" ] && [ -r "$repo_root/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch" ]; then
	PATCH_LOCAL="$repo_root/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch"
fi

REPORT_MD="$OUT_DIR/llamacpp_mtp_one_token_draft_probe_spark.md"
REMOTE_PROMPT_FILE=""
if [ "$PROMPT_FILE_LOCAL" != "" ]; then
	if [ ! -r "$PROMPT_FILE_LOCAL" ]; then
		echo "PROMPT_FILE_LOCAL not readable: $PROMPT_FILE_LOCAL"
		exit 4
	fi
	REMOTE_PROMPT_FILE="/tmp/llamacpp_mtp_one_token_prompts.txt"
fi

REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE="$REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV"
case " $REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE " in
	*" LLAMA_COMMIT="*)
		;;
	*)
		REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE="$REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE LLAMA_COMMIT=$LLAMA_COMMIT"
		;;
esac
if [ "$REMOTE_PROMPT_FILE" != "" ]; then
	case " $REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE " in
		*" PROMPT_FILE="*)
			;;
		*)
			REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE="$REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE PROMPT_FILE=$REMOTE_PROMPT_FILE"
			;;
	esac
fi

{
	echo "# llama.cpp One-Token MTP Draft Probe (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo "- llama_commit: $LLAMA_COMMIT"
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
	echo "Recommended preflight (no trunk load): run scripts/run_mtp_sidecar_loader_probe_spark.sh first to validate the sidecar contract + (optionally) the llama.cpp-side sidecar probe before enabling ALLOW_RUN=1 here."
	echo
	echo "Optional Spark-side env vars:"
	echo
	echo "- LLAMA_DIR=$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark"
	echo "- LLAMA_REPO=https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git"
	echo "- LLAMA_COMMIT=94073e2"
	echo "- CUDACXX=/abs/path/to/nvcc (optional; overrides auto-detect if CMake cannot find CUDA)"
	echo "- PROMPT='Hello.'"
	echo "- SEED=1234"
	echo "- LOAD_SIDECAR_WEIGHTS=1 (loads sidecar tensor payloads into RAM)"
	echo "- PROMPT_FILE=/abs/path/to/prompts.txt (one non-empty prompt per line; emits a batch JSON wrapper)"
	echo
	echo "Remote env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	if [ "$PROMPT_FILE_LOCAL" != "" ]; then
		echo "Local prompt file: $PROMPT_FILE_LOCAL"
	fi
	echo
	echo '```'
	echo "$REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE"
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

if [ "$PROMPT_FILE_LOCAL" != "" ]; then
	ssh $SSH_OPTS "$target" "cat > $REMOTE_PROMPT_FILE" \
		<"$PROMPT_FILE_LOCAL" \
		>"$OUT_DIR/remote_upload_prompt_file_stdout.txt" 2>"$OUT_DIR/remote_upload_prompt_file_stderr.txt" || true
else
	printf '%s\n' '' >"$OUT_DIR/remote_upload_prompt_file_stdout.txt"
	printf '%s\n' '' >"$OUT_DIR/remote_upload_prompt_file_stderr.txt"
fi

ssh $SSH_OPTS "$target" "$REMOTE_LLAMA_MTP_ONE_TOKEN_PROBE_ENV_EFFECTIVE sh -lc '
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

out = {"ok": False, "errors": [], "probe_ok": None, "json_start": None, "json_end": None}
text = src.read_text(encoding="utf-8")
decoder = json.JSONDecoder()
best = None
for idx, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        doc, end = decoder.raw_decode(text[idx:])
    except json.JSONDecodeError:
        continue
    if not isinstance(doc, dict):
        continue
    if "ok" not in doc or "errors" not in doc:
        continue
    abs_end = idx + end
    score = (1 if "runtime_commit" in doc else 0, abs_end, end)
    if best is None or score > best[0]:
        best = (score, doc, idx, abs_end)
if best is None:
    out["errors"].append("failed to find probe JSON object in stdout")
else:
    _, doc, start, end = best
    dst.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out["json_start"] = int(start)
    out["json_end"] = int(end)
    out["probe_ok"] = bool(doc.get("ok", False))
    out["ok"] = out["probe_ok"]
    errs = doc.get("errors", [])
    if isinstance(errs, list):
        out["errors"] = [str(x) for x in errs[:64]]
print(json.dumps(out, indent=2, sort_keys=True))
PY

echo "== validating one-token probe JSON (local; best-effort) =="
if [ -r "$OUT_DIR/mtp_one_token_probe.json" ]; then
	if python3 - "$OUT_DIR/mtp_one_token_probe.json" <<'PY' >/dev/null 2>&1
import json
import sys
from pathlib import Path
obj = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if isinstance(obj, dict) and isinstance(obj.get("results"), list) else 1)
PY
	then
		python3 "$repo_root/scripts/model_contract_validate_mtp_one_token_batch_probe.py" \
			--batch-json "$OUT_DIR/mtp_one_token_probe.json" \
			--json \
			>"$OUT_DIR/mtp_one_token_probe_validate.json" 2>"$OUT_DIR/mtp_one_token_probe_validate_stderr.txt" || true
	else
		python3 "$repo_root/scripts/model_contract_validate_mtp_one_token_draft_probe.py" \
			--probe-json "$OUT_DIR/mtp_one_token_probe.json" \
			--json \
			>"$OUT_DIR/mtp_one_token_probe_validate.json" 2>"$OUT_DIR/mtp_one_token_probe_validate_stderr.txt" || true
	fi
else
	printf '%s\n' '{"ok":false,"skipped":true,"reason":"mtp_one_token_probe.json missing"}' >"$OUT_DIR/mtp_one_token_probe_validate.json"
	printf '%s\n' "" >"$OUT_DIR/mtp_one_token_probe_validate_stderr.txt"
fi

{
	echo "## Results"
	echo
	echo "This runner targets the llama.cpp-side one-token probe (llama-ds4-mtp-one-token-draft-probe)."
	echo "It can load the trunk GGUF when ALLOW_RUN=1 is set, so keep it gated and coordinate with the baseline runtime loop."
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
	echo "- upload prompt file stderr: $OUT_DIR/remote_upload_prompt_file_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"

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

probe_parse = read_json(out_dir / "mtp_one_token_probe_parse.json") or {}
probe_validate = read_json(out_dir / "mtp_one_token_probe_validate.json") or {}

probe_ok = bool(probe_parse.get("ok", False))
validate_ok = bool(probe_validate.get("ok", False))

summary = {
	"ok": bool(probe_ok and validate_ok),
	"probe_ok": probe_ok,
	"validate_ok": validate_ok,
	"artifacts": {
		"report_md": str(report_md),
		"probe_json": str(out_dir / "mtp_one_token_probe.json"),
		"probe_parse_json": str(out_dir / "mtp_one_token_probe_parse.json"),
		"validate_json": str(out_dir / "mtp_one_token_probe_validate.json"),
		"validate_stderr": str(out_dir / "mtp_one_token_probe_validate_stderr.txt"),
	},
	"probe_parse": probe_parse,
	"validate": probe_validate,
}

(out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
