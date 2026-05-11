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
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (or https:// URL)"
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
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (file path; loader probe does not accept URLs)"
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
  echo \"run skipped: set MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (or https:// URL)\"
  exit 0
fi
case \"${MTP_SIDECAR_GGUF}\" in
  http://*|https://*)
    python3 /tmp/model_contract_probe_mtp_sidecar.py --url \"${MTP_SIDECAR_GGUF}\" '"$REMOTE_MTP_SIDECAR_ARGS"'
    ;;
  *)
    if [ ! -r \"${MTP_SIDECAR_GGUF}\" ]; then
      echo \"run skipped: MTP_SIDECAR_GGUF not readable: ${MTP_SIDECAR_GGUF}\"
      exit 0
    fi
    python3 /tmp/model_contract_probe_mtp_sidecar.py --path \"${MTP_SIDECAR_GGUF}\" '"$REMOTE_MTP_SIDECAR_ARGS"'
    ;;
esac
' " <"$repo_root/scripts/model_contract_probe_mtp_sidecar.py" \
	>"$OUT_DIR/remote_contract_probe_stdout.txt" 2>"$OUT_DIR/remote_contract_probe_stderr.txt" || true

python3 - "$OUT_DIR/remote_contract_probe_stdout.txt" >"$OUT_DIR/contract_probe_parse.json" 2>/dev/null <<'PY' || true
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
out = {"ok": False, "errors": [], "probe_ok": None}
try:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict):
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

python3 - "$OUT_DIR/remote_contract_probe_stdout.txt" "$OUT_DIR/contract_probe.json" 2>/dev/null <<'PY' || true
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
try:
    doc = json.loads(src.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
if not isinstance(doc, dict):
    raise SystemExit(0)
dst.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

if python3 - "$OUT_DIR/contract_probe_parse.json" 2>/dev/null <<'PY'; then
import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
doc = json.loads(p.read_text(encoding="utf-8"))
raise SystemExit(0 if bool(doc.get("ok", False)) else 1)
PY
	echo "== generating llama.cpp MTP sidecar binder skeleton (local) =="
	python3 "$repo_root/scripts/model_contract_generate_llamacpp_mtp_sidecar_binder.py" \
		--sidecar-probe-json "$OUT_DIR/contract_probe.json" \
		>"$OUT_DIR/deepseek4_mtp_sidecar.hpp" 2>/dev/null || true
fi

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
	echo "- full JSON (if parseable): $OUT_DIR/contract_probe.json"
	echo "- parsed status: $OUT_DIR/contract_probe_parse.json"
	echo "- binder skeleton (if ok=true): $OUT_DIR/deepseek4_mtp_sidecar.hpp"
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

echo "== verifying expected tensor list against upstream ds4 binder (local) =="
python3 "$repo_root/scripts/verify_mtp_sidecar_expected_tensors_vs_ds4.py" --json \
	>"$OUT_DIR/local_ds4_tensor_contract_stdout.txt" 2>"$OUT_DIR/local_ds4_tensor_contract_stderr.txt" || true

{
	echo "## Tensor Contract vs ds4 binder (local)"
	echo
	echo "Command:"
	echo
	echo '```'
	echo "python3 scripts/verify_mtp_sidecar_expected_tensors_vs_ds4.py --json"
	echo '```'
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,120p' "$OUT_DIR/local_ds4_tensor_contract_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,120p' "$OUT_DIR/local_ds4_tensor_contract_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/local_ds4_tensor_contract_stdout.txt"
	echo "- stderr: $OUT_DIR/local_ds4_tensor_contract_stderr.txt"
	echo
} >>"$REPORT_MD"

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

python3 - "$OUT_DIR/remote_loader_probe_stdout.txt" "$OUT_DIR/loader_probe.json" >"$OUT_DIR/loader_probe_parse.json" 2>/dev/null <<'PY' || true
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
out_json_path = Path(sys.argv[2])
txt = path.read_text(encoding="utf-8", errors="replace")

out = {"ok": False, "errors": [], "probe_ok": None, "extracted_json_bytes": 0}

decoder = json.JSONDecoder()
best_doc = None
best_len = 0

for m in re.finditer(r"^\\{", txt, flags=re.M):
    idx = m.start()
    try:
        doc, end = decoder.raw_decode(txt[idx:])
    except Exception:
        continue
    if isinstance(doc, dict):
        consumed = int(end)
        if consumed > best_len:
            best_len = consumed
            best_doc = doc

if best_doc is None:
    out["errors"].append(
        "unable to locate JSON object in stdout; set JSON_ONLY=1 in REMOTE_LLAMA_MTP_SIDECAR_PROBE_ENV for machine-parseable output"
    )
    print(json.dumps(out, indent=2, sort_keys=True))
    raise SystemExit(0)

try:
    if isinstance(best_doc, dict):
        out_json_path.write_text(json.dumps(best_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
except Exception:
    pass

out["extracted_json_bytes"] = best_len
out["probe_ok"] = bool(best_doc.get("ok", False))
out["ok"] = out["probe_ok"]
errs = best_doc.get("errors", [])
if isinstance(errs, list):
    out["errors"] = [str(x) for x in errs[:64]]

print(json.dumps(out, indent=2, sort_keys=True))
PY

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
	echo "- full JSON (if extracted): $OUT_DIR/loader_probe.json"
	echo "- parsed status: $OUT_DIR/loader_probe_parse.json"
	echo "- upload helper stderr: $OUT_DIR/remote_loader_upload_helper_stderr.txt"
	echo "- upload patch stderr: $OUT_DIR/remote_loader_upload_patch_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
