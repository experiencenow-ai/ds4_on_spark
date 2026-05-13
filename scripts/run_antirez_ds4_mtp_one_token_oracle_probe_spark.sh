#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_antirez_ds4_mtp_one_token_oracle}"
REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV="${REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV:-}"
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

HELPER_LOCAL="$repo_root/scripts/antirez_ds4_mtp_one_token_oracle_patch.sh"
PATCH_Q4K_LOCAL="$repo_root/docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch"
PATCH_CACHE_LOCAL="$repo_root/docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch"
PATCH_PROBE_LOCAL="$repo_root/docs/antirez-patches/ds4-3630e64-mtp-one-token-json-probe.patch"

REPORT_MD="$OUT_DIR/antirez_ds4_mtp_one_token_oracle_probe_spark.md"

{
	echo "# antirez/ds4 One-Token MTP Oracle Probe (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo
	echo "## Safety Gates"
	echo
	echo "This runner is gated and does not clone/patch/build/run antirez/ds4 unless Spark-side env enables it."
	echo
	echo "Set env vars on Spark via REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV:"
	echo
	echo "- ALLOW_FETCH=1 (clone antirez/ds4 if missing)"
	echo "- ALLOW_PATCH=1 (apply the ds4 CUDA + one-token oracle patches)"
	echo "- ALLOW_BUILD=1 (build ds4 via Makefile/nvcc)"
	echo "- ALLOW_RUN=1 (run the probe; loads trunk GGUF + MTP sidecar GGUF)"
	echo
	echo "Required when ALLOW_RUN=1 (Spark-side env vars):"
	echo
	echo "- TRUNK_GGUF=/abs/path/to/trunk.gguf (defaults to Spark-staged antirez IQ2XXS trunk if readable)"
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (defaults to Spark-staged sidecar if readable)"
	echo
	echo "Optional Spark-side env vars:"
	echo
	echo "- DS4_DIR=$HOME/src/ds4"
	echo "- DS4_REPO=https://github.com/antirez/ds4.git"
	echo "- DS4_COMMIT=3630e64"
	echo "- DS4_EXTRA_ARGS='--nothink' (forwarded into the ds4 CLI invocation)"
	echo "- PROMPT='Hello.'"
	echo "- SEED=1234"
	echo "- CTX=32768"
	echo
	echo "Remote env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo '```'
	echo "$REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV"
	echo '```'
	echo
	echo "## Spark Host Info"
	echo
	echo '```'
	ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true'
	echo '```'
	echo
	echo "## Patches"
	echo
	echo "- $PATCH_Q4K_LOCAL"
	echo "- $PATCH_CACHE_LOCAL"
	echo "- $PATCH_PROBE_LOCAL"
	echo
} >"$REPORT_MD"

if [ ! -r "$HELPER_LOCAL" ]; then
	echo "helper not readable: $HELPER_LOCAL"
	exit 2
fi
if [ ! -r "$PATCH_Q4K_LOCAL" ] || [ ! -r "$PATCH_CACHE_LOCAL" ] || [ ! -r "$PATCH_PROBE_LOCAL" ]; then
	echo "missing antirez patch file(s) under docs/antirez-patches"
	exit 3
fi

echo "== uploading helper + patches to spark =="
ssh $SSH_OPTS "$target" 'cat > /tmp/antirez_ds4_mtp_one_token_oracle_patch.sh && chmod +x /tmp/antirez_ds4_mtp_one_token_oracle_patch.sh' \
	<"$HELPER_LOCAL" \
	>"$OUT_DIR/remote_upload_helper_stdout.txt" 2>"$OUT_DIR/remote_upload_helper_stderr.txt" || true
ssh $SSH_OPTS "$target" 'cat > /tmp/ds4_cuda_mtp_q4k_and_sidecar_map.patch' \
	<"$PATCH_Q4K_LOCAL" \
	>"$OUT_DIR/remote_upload_patch_q4k_stdout.txt" 2>"$OUT_DIR/remote_upload_patch_q4k_stderr.txt" || true
ssh $SSH_OPTS "$target" 'cat > /tmp/ds4_cuda_multi_model_cache.patch' \
	<"$PATCH_CACHE_LOCAL" \
	>"$OUT_DIR/remote_upload_patch_cache_stdout.txt" 2>"$OUT_DIR/remote_upload_patch_cache_stderr.txt" || true
ssh $SSH_OPTS "$target" 'cat > /tmp/ds4_mtp_one_token_json_probe.patch' \
	<"$PATCH_PROBE_LOCAL" \
	>"$OUT_DIR/remote_upload_patch_probe_stdout.txt" 2>"$OUT_DIR/remote_upload_patch_probe_stderr.txt" || true

echo "== running antirez/ds4 oracle one-token probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "$REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV sh -lc '
set -eu
PATCH_Q4K_FILE=/tmp/ds4_cuda_mtp_q4k_and_sidecar_map.patch
PATCH_CACHE_FILE=/tmp/ds4_cuda_multi_model_cache.patch
PATCH_PROBE_FILE=/tmp/ds4_mtp_one_token_json_probe.patch
export PATCH_Q4K_FILE PATCH_CACHE_FILE PATCH_PROBE_FILE
JSON_ONLY=1
export JSON_ONLY
/tmp/antirez_ds4_mtp_one_token_oracle_patch.sh
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

echo "== validating oracle probe JSON (local; best-effort) =="
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
	echo "This runner targets the antirez/ds4 oracle path and can load the trunk GGUF when ALLOW_RUN=1 is set."
	echo "Coordinate with the baseline runtime loop before running it on Spark."
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
	sed -n '1,120p' "$OUT_DIR/mtp_one_token_probe_validate.json" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- report: $REPORT_MD"
	echo "- stdout: $OUT_DIR/remote_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_probe_stderr.txt"
	echo "- probe JSON (if parseable): $OUT_DIR/mtp_one_token_probe.json"
	echo "- parsed status: $OUT_DIR/mtp_one_token_probe_parse.json"
	echo "- validate JSON: $OUT_DIR/mtp_one_token_probe_validate.json"
	echo "- validate stderr: $OUT_DIR/mtp_one_token_probe_validate_stderr.txt"
	echo
	echo "Next step: diff against a candidate probe JSON:"
	echo
	echo '```sh'
	echo "python3 $repo_root/scripts/diff_mtp_one_token_draft_probe.py --a $OUT_DIR/mtp_one_token_probe.json --b /path/to/candidate_probe.json --json"
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

probe_parse = read_json(out_dir / "mtp_one_token_probe_parse.json") or {}
v1 = read_json(out_dir / "mtp_one_token_probe_validate.json")

probe_ok = bool(probe_parse.get("ok", False))
validate_ok = bool(v1.get("ok", False)) if isinstance(v1, dict) else False

summary = {
	"ok": bool(probe_ok and validate_ok),
	"probe_ok": probe_ok,
	"validate_ok": validate_ok,
	"artifacts": {
		"report_md": str(report_md),
		"probe_json": str(out_dir / "mtp_one_token_probe.json"),
		"probe_parse_json": str(out_dir / "mtp_one_token_probe_parse.json"),
		"validate_json": str(out_dir / "mtp_one_token_probe_validate.json"),
	},
	"probe_parse": probe_parse,
	"validate": v1 if isinstance(v1, dict) else None,
}

(out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "done: $REPORT_MD"
