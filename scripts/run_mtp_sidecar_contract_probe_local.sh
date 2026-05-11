#!/usr/bin/env sh
set -eu

sidecar_arg="${1:-}"
MTP_SIDECAR_GGUF="${MTP_SIDECAR_GGUF:-$sidecar_arg}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_sidecar_probe_local}"
MTP_SIDECAR_ARGS="${MTP_SIDECAR_ARGS:---json --expect-deepseek-v4-flash --payload-sample-bytes 64}"
SIDECAR_EXPECT_FILE_SIZE="${SIDECAR_EXPECT_FILE_SIZE:-}"
if [ "$SIDECAR_EXPECT_FILE_SIZE" != "" ]; then
	case " $MTP_SIDECAR_ARGS " in
		*" --expect-file-size "*) ;;
		*) MTP_SIDECAR_ARGS="$MTP_SIDECAR_ARGS --expect-file-size $SIDECAR_EXPECT_FILE_SIZE" ;;
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

REPORT_MD="$OUT_DIR/mtp_sidecar_probe_local.md"

if [ "$MTP_SIDECAR_GGUF" = "" ]; then
	echo "usage: $0 /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf" 1>&2
	echo "or set: MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf" 1>&2
	echo "or set: MTP_SIDECAR_GGUF=https://.../DeepSeek-V4-Flash-MTP-*.gguf (metadata-only range reads)" 1>&2
	exit 2
fi

probe_mode="path"
case "$MTP_SIDECAR_GGUF" in
	http://*|https://*)
		probe_mode="url"
		;;
	*)
		if [ ! -r "$MTP_SIDECAR_GGUF" ]; then
			echo "sidecar not readable: $MTP_SIDECAR_GGUF" 1>&2
			exit 4
		fi
		;;
esac

{
	echo "# MTP Sidecar Contract Probe (local)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	if [ "$probe_mode" = "url" ]; then
		echo "- sidecar_url: $MTP_SIDECAR_GGUF"
	else
		echo "- sidecar_path: $MTP_SIDECAR_GGUF"
	fi
	echo
	echo "## Command"
	echo
	echo "This is a metadata-only sanity check for DS4-tuned MTP sidecars (e.g. `general.architecture=deepseek4_mtp_support` + 32 `mtp.0.*` tensors)."
	echo "It does not require loading the trunk GGUF or reading full tensor payloads into RAM."
	echo
	echo '```'
	if [ "$probe_mode" = "url" ]; then
		echo "python3 scripts/model_contract_probe_mtp_sidecar.py --url \"$MTP_SIDECAR_GGUF\" $MTP_SIDECAR_ARGS"
	else
		echo "python3 scripts/model_contract_probe_mtp_sidecar.py --path \"$MTP_SIDECAR_GGUF\" $MTP_SIDECAR_ARGS"
	fi
	echo '```'
	echo
} >"$REPORT_MD"

echo "== running MTP sidecar contract probe (local) =="
if [ "$probe_mode" = "url" ]; then
	python3 "$repo_root/scripts/model_contract_probe_mtp_sidecar.py" --url "$MTP_SIDECAR_GGUF" $MTP_SIDECAR_ARGS \
		>"$OUT_DIR/contract_probe_stdout.txt" 2>"$OUT_DIR/contract_probe_stderr.txt" || true
else
	python3 "$repo_root/scripts/model_contract_probe_mtp_sidecar.py" --path "$MTP_SIDECAR_GGUF" $MTP_SIDECAR_ARGS \
		>"$OUT_DIR/contract_probe_stdout.txt" 2>"$OUT_DIR/contract_probe_stderr.txt" || true
fi

python3 - "$OUT_DIR/contract_probe_stdout.txt" >"$OUT_DIR/contract_probe_parse.json" 2>/dev/null <<'PY' || true
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
out = {"ok": False, "errors": [], "probe_ok": None}
try:
    doc = json.loads(src.read_text(encoding="utf-8"))
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

python3 - "$OUT_DIR/contract_probe_stdout.txt" "$OUT_DIR/contract_probe.json" 2>/dev/null <<'PY' || true
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
	echo "## Results"
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/contract_probe_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/contract_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/contract_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/contract_probe_stderr.txt"
	echo "- full JSON (if parseable): $OUT_DIR/contract_probe.json"
	echo "- parsed status: $OUT_DIR/contract_probe_parse.json"
	echo "- binder skeleton (if ok=true): $OUT_DIR/deepseek4_mtp_sidecar.hpp"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
