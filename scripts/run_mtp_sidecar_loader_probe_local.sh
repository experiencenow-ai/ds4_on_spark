#!/usr/bin/env sh
set -eu

sidecar_arg="${1:-}"
MTP_SIDECAR_GGUF="${MTP_SIDECAR_GGUF:-$sidecar_arg}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_sidecar_loader_probe_local}"
MTP_SIDECAR_ARGS="${MTP_SIDECAR_ARGS:---json --expect-deepseek-v4-flash --payload-sample-bytes 64}"

ALLOW_URL="${ALLOW_URL:-0}"
ALLOW_LLAMA_RUN="${ALLOW_LLAMA_RUN:-0}"
LLAMA_DIR="${LLAMA_DIR:-}"
LLAMA_PROBE_BIN="${LLAMA_PROBE_BIN:-}"
PAYLOAD_SAMPLE_BYTES="${PAYLOAD_SAMPLE_BYTES:-0}"
LOAD_WEIGHTS="${LOAD_WEIGHTS:-0}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"

mkdir -p "$OUT_DIR"
echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/mtp_sidecar_loader_probe_local.md"

if [ "$MTP_SIDECAR_GGUF" = "" ]; then
	echo "usage: $0 /abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf" 1>&2
	echo "or set: MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf" 1>&2
	exit 2
fi

is_url="0"
case "$MTP_SIDECAR_GGUF" in
	http://*|https://*)
		is_url="1"
		;;
esac

contract_src_flag="--path"
contract_src_value="$MTP_SIDECAR_GGUF"
if [ "$is_url" = "1" ]; then
	contract_src_flag="--url"
	if [ "$ALLOW_URL" != "1" ]; then
		echo "refusing URL input for local runner unless ALLOW_URL=1: $MTP_SIDECAR_GGUF" 1>&2
		echo "note: URL mode uses HTTP Range reads and refuses full downloads when Range is not honored." 1>&2
		exit 3
	fi
else
	if [ ! -r "$MTP_SIDECAR_GGUF" ]; then
		echo "sidecar not readable: $MTP_SIDECAR_GGUF" 1>&2
		exit 4
	fi
fi

if [ "$LLAMA_PROBE_BIN" = "" ] && [ "$LLAMA_DIR" != "" ]; then
	LLAMA_PROBE_BIN="$LLAMA_DIR/build/bin/llama-ds4-mtp-sidecar-probe"
fi

{
	echo "# MTP Sidecar Loader Probe (local file)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- sidecar: $MTP_SIDECAR_GGUF"
	echo
	echo "## What This Does"
	echo
	echo "This runner performs two *independent* validations against the same local MTP sidecar GGUF:"
	echo
	echo "1) **Contract probe (Python)**: reads GGUF metadata + tensor directory (and samples payload bytes) to validate the 32 `mtp.0.*` tensors."
	echo "2) **Loader probe (llama.cpp)** (optional): runs `llama-ds4-mtp-sidecar-probe --json` if enabled and available."
	echo
	echo "It does **not** load the trunk GGUF."
	echo
	echo "## Contract Probe Command"
	echo
	echo '```'
	echo "python3 scripts/model_contract_probe_mtp_sidecar.py $contract_src_flag \"$contract_src_value\" $MTP_SIDECAR_ARGS"
	echo '```'
	echo
	echo "## Loader Probe Gates (llama.cpp)"
	echo
	echo "- Set `ALLOW_LLAMA_RUN=1` to run the llama.cpp probe."
	echo "- Provide `LLAMA_PROBE_BIN=/abs/path/to/llama-ds4-mtp-sidecar-probe` or `LLAMA_DIR=/path/to/llama.cpp-deepseek-v4-flash-cuda-spark`."
	echo "- Note: the loader probe requires a local file; URL-only runs skip llama.cpp."
	echo "- Optional: `PAYLOAD_SAMPLE_BYTES=64` and/or `LOAD_WEIGHTS=1`."
	echo
	echo "Recorded loader env:"
	echo
	echo '```'
	echo "ALLOW_URL=$ALLOW_URL"
	echo "ALLOW_LLAMA_RUN=$ALLOW_LLAMA_RUN"
	echo "LLAMA_DIR=$LLAMA_DIR"
	echo "LLAMA_PROBE_BIN=$LLAMA_PROBE_BIN"
	echo "PAYLOAD_SAMPLE_BYTES=$PAYLOAD_SAMPLE_BYTES"
	echo "LOAD_WEIGHTS=$LOAD_WEIGHTS"
	echo '```'
	echo
} >"$REPORT_MD"

echo "== running Python MTP sidecar contract probe (local) =="
python3 "$repo_root/scripts/model_contract_probe_mtp_sidecar.py" $contract_src_flag "$contract_src_value" $MTP_SIDECAR_ARGS \
	>"$OUT_DIR/contract_probe_stdout.txt" 2>"$OUT_DIR/contract_probe_stderr.txt" || true

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
	echo "## Contract Probe Results (Python)"
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

echo "== running llama.cpp-side MTP sidecar loader probe (local; may be gated) =="
if [ "$is_url" = "1" ]; then
	printf '%s\n' "run skipped: sidecar is a URL; loader probe requires a readable local file" >"$OUT_DIR/loader_probe_stdout.txt"
	printf '%s\n' "" >"$OUT_DIR/loader_probe_stderr.txt"
else
	if [ "$ALLOW_LLAMA_RUN" != "1" ]; then
		printf '%s\n' "run skipped: set ALLOW_LLAMA_RUN=1 to enable" >"$OUT_DIR/loader_probe_stdout.txt"
		printf '%s\n' "" >"$OUT_DIR/loader_probe_stderr.txt"
	else
		if [ "$LLAMA_PROBE_BIN" = "" ]; then
			printf '%s\n' "run skipped: set LLAMA_PROBE_BIN=/abs/path/to/llama-ds4-mtp-sidecar-probe (or LLAMA_DIR=...)" >"$OUT_DIR/loader_probe_stdout.txt"
			printf '%s\n' "" >"$OUT_DIR/loader_probe_stderr.txt"
		else
			if [ ! -x "$LLAMA_PROBE_BIN" ]; then
				printf '%s\n' "run skipped: LLAMA_PROBE_BIN not executable: $LLAMA_PROBE_BIN" >"$OUT_DIR/loader_probe_stdout.txt"
				printf '%s\n' "" >"$OUT_DIR/loader_probe_stderr.txt"
			else
				loader_args="--path \"$MTP_SIDECAR_GGUF\" --json"
				if [ "$PAYLOAD_SAMPLE_BYTES" != "0" ]; then
					loader_args="$loader_args --payload-sample-bytes $PAYLOAD_SAMPLE_BYTES"
				fi
				if [ "$LOAD_WEIGHTS" = "1" ]; then
					loader_args="$loader_args --load-weights"
				fi
				sh -lc "\"$LLAMA_PROBE_BIN\" $loader_args" >"$OUT_DIR/loader_probe_stdout.txt" 2>"$OUT_DIR/loader_probe_stderr.txt" || true
			fi
		fi
	fi
fi

python3 - "$OUT_DIR/loader_probe_stdout.txt" "$OUT_DIR/loader_probe.json" >"$OUT_DIR/loader_probe_parse.json" 2>/dev/null <<'PY' || true
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
out_json_path = Path(sys.argv[2])

out = {"ok": False, "errors": [], "probe_ok": None}
try:
    doc = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(doc, dict):
        out_json_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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

echo "== cross-checking Python contract probe JSON vs llama.cpp probe JSON (local) =="
if [ "$is_url" = "1" ]; then
	printf '%s\n' "{\"ok\":false,\"skipped\":true,\"reason\":\"sidecar is URL (no llama.cpp probe)\",\"errors\":[]}" >"$OUT_DIR/contract_vs_loader_probe_parse.json"
	printf '%s\n' "" >"$OUT_DIR/contract_vs_loader_probe_stderr.txt"
else
	python3 "$repo_root/scripts/verify_mtp_sidecar_contract_vs_llamacpp_probe_json.py" \
		--contract-probe-json "$OUT_DIR/contract_probe.json" \
		--llamacpp-probe-json "$OUT_DIR/loader_probe.json" \
		--json \
		>"$OUT_DIR/contract_vs_loader_probe_parse.json" 2>"$OUT_DIR/contract_vs_loader_probe_stderr.txt" || true
fi

{
	echo "## Loader Probe Results (llama.cpp)"
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/loader_probe_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/loader_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/loader_probe_stdout.txt"
	echo "- stderr: $OUT_DIR/loader_probe_stderr.txt"
	echo "- full JSON (if parseable): $OUT_DIR/loader_probe.json"
	echo "- parsed status: $OUT_DIR/loader_probe_parse.json"
	echo
} >>"$REPORT_MD"

{
	echo "## Contract vs Loader Cross-check (local)"
	echo
	echo "Command:"
	echo
	echo '```'
	echo "python3 scripts/verify_mtp_sidecar_contract_vs_llamacpp_probe_json.py --contract-probe-json $OUT_DIR/contract_probe.json --llamacpp-probe-json $OUT_DIR/loader_probe.json --json"
	echo '```'
	echo
	echo "Stdout:"
	echo
	echo '```'
	sed -n '1,120p' "$OUT_DIR/contract_vs_loader_probe_parse.json" || true
	echo '```'
	echo
	echo "Stderr:"
	echo
	echo '```'
	sed -n '1,120p' "$OUT_DIR/contract_vs_loader_probe_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/contract_vs_loader_probe_parse.json"
	echo "- stderr: $OUT_DIR/contract_vs_loader_probe_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
