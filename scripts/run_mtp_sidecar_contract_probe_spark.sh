#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_sidecar_probe}"
REMOTE_MTP_SIDECAR_ENV="${REMOTE_MTP_SIDECAR_ENV:-}"
REMOTE_MTP_SIDECAR_ARGS="${REMOTE_MTP_SIDECAR_ARGS:---json --expect-deepseek-v4-flash --payload-sample-bytes 64}"
SIDECAR_EXPECT_FILE_SIZE="${SIDECAR_EXPECT_FILE_SIZE:-}"
if [ "$SIDECAR_EXPECT_FILE_SIZE" != "" ]; then
	case " $REMOTE_MTP_SIDECAR_ARGS " in
		*" --expect-file-size "*)
			;;
		*)
			REMOTE_MTP_SIDECAR_ARGS="$REMOTE_MTP_SIDECAR_ARGS --expect-file-size $SIDECAR_EXPECT_FILE_SIZE"
			;;
	esac
fi
ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"

mkdir -p "$OUT_DIR"
echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -e "$repo_root/.git" ]; then
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
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (optional; defaults to Spark0-staged artifact if present; URL requires ALLOW_URL=1)"
	echo "- ALLOW_URL=1 (required when MTP_SIDECAR_GGUF is a URL)"
	echo
	echo "Optional local env vars:"
	echo
	echo "- SIDECAR_EXPECT_FILE_SIZE=3807602400 (pins the staged sidecar file size; appended as --expect-file-size)"
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
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_probe_mtp_sidecar.py && chmod +x /tmp/model_contract_probe_mtp_sidecar.py" \
	<"$repo_root/scripts/model_contract_probe_mtp_sidecar.py" \
	>"$OUT_DIR/remote_mtp_sidecar_probe_upload_stdout.txt" 2>"$OUT_DIR/remote_mtp_sidecar_probe_upload_stderr.txt" || true

ssh $SSH_OPTS "$target" "env $REMOTE_MTP_SIDECAR_ENV sh -s -- $REMOTE_MTP_SIDECAR_ARGS" \
	>"$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" 2>"$OUT_DIR/remote_mtp_sidecar_probe_stderr.txt" <<'SH' || true
set -eu
REMOTE_MTP_SIDECAR_ARGS="$*"
if [ "${ALLOW_RUN:-0}" != "1" ]; then
	echo "run skipped: set ALLOW_RUN=1 on Spark to enable"
	exit 0
fi
if [ "${MTP_SIDECAR_GGUF:-}" = "" ]; then
	for p in \
		/home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/home/spark1/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/home/spark/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/mnt/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
		/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf
	do
		if [ -r "$p" ]; then
			MTP_SIDECAR_GGUF="$p"
			export MTP_SIDECAR_GGUF
			echo "defaulted MTP_SIDECAR_GGUF=$p" 1>&2
			break
		fi
	done
fi
if [ "${MTP_SIDECAR_GGUF:-}" = "" ]; then
	echo "run skipped: set MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf" 1>&2
	exit 0
fi
case "${MTP_SIDECAR_GGUF}" in
	http://*|https://*)
		if [ "${ALLOW_URL:-0}" != "1" ]; then
			echo "run skipped: MTP_SIDECAR_GGUF is a URL; set ALLOW_URL=1 on Spark to enable URL range-read probe"
			exit 0
		fi
		python3 /tmp/model_contract_probe_mtp_sidecar.py --url "${MTP_SIDECAR_GGUF}" ${REMOTE_MTP_SIDECAR_ARGS}
		;;
	*)
		if [ ! -r "${MTP_SIDECAR_GGUF}" ]; then
			echo "run skipped: MTP_SIDECAR_GGUF not readable: ${MTP_SIDECAR_GGUF}"
			exit 0
		fi
		python3 /tmp/model_contract_probe_mtp_sidecar.py --path "${MTP_SIDECAR_GGUF}" ${REMOTE_MTP_SIDECAR_ARGS}
		;;
esac
SH

python3 - "$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" >"$OUT_DIR/contract_probe_parse.json" 2>/dev/null <<'PY' || true
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

python3 - "$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" "$OUT_DIR/contract_probe.json" 2>/dev/null <<'PY' || true
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

echo "== verifying sidecar payload fingerprints against pinned antirez reference (local) =="
if [ -r "$OUT_DIR/contract_probe.json" ]; then
	python3 "$repo_root/scripts/verify_mtp_sidecar_payload_fingerprint.py" \
		--probe-json "$OUT_DIR/contract_probe.json" \
		--json \
		>"$OUT_DIR/contract_probe_fingerprint_gate.json" 2>"$OUT_DIR/contract_probe_fingerprint_gate_stderr.txt" || true
else
	printf '%s\n' "{\"ok\":false,\"skipped\":true,\"reason\":\"contract_probe.json missing\"}" >"$OUT_DIR/contract_probe_fingerprint_gate.json"
	printf '%s\n' "" >"$OUT_DIR/contract_probe_fingerprint_gate_stderr.txt"
fi

{
	echo "## Results"
	echo
	echo 'This is a metadata-only sanity check for DS4-tuned MTP sidecars (e.g. `general.architecture=deepseek4_mtp_support` + 32 `mtp.0.*` tensors).'
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
	echo "- full JSON (if parseable): $OUT_DIR/contract_probe.json"
	echo "- parsed status: $OUT_DIR/contract_probe_parse.json"
	echo "- binder skeleton (if ok=true): $OUT_DIR/deepseek4_mtp_sidecar.hpp"
	echo "- fingerprint gate JSON (local): $OUT_DIR/contract_probe_fingerprint_gate.json"
	echo "- fingerprint gate stderr (local): $OUT_DIR/contract_probe_fingerprint_gate_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
