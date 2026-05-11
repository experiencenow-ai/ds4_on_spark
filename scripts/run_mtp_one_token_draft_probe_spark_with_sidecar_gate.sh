#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_one_token_probe}"

REMOTE_MTP_ONE_TOKEN_ENV="${REMOTE_MTP_ONE_TOKEN_ENV:-}"
REMOTE_MTP_ONE_TOKEN_CMD="${REMOTE_MTP_ONE_TOKEN_CMD:-}"

REMOTE_MTP_SIDECAR_ENV="${REMOTE_MTP_SIDECAR_ENV:-}"
REMOTE_MTP_SIDECAR_ARGS="${REMOTE_MTP_SIDECAR_ARGS:---json --expect-deepseek-v4-flash --payload-sample-bytes 64}"
SIDECAR_EXPECT_FILE_SIZE="${SIDECAR_EXPECT_FILE_SIZE:-}"
if [ "$SIDECAR_EXPECT_FILE_SIZE" != "" ]; then
	case " $REMOTE_MTP_SIDECAR_ARGS " in
		*" --expect-file-size "*) ;;
		*) REMOTE_MTP_SIDECAR_ARGS="$REMOTE_MTP_SIDECAR_ARGS --expect-file-size $SIDECAR_EXPECT_FILE_SIZE" ;;
	esac
fi

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"

sh_quote()
{
	# Single-quote a string for safe embedding in the ssh command line.
	# Note: this quotes for the *local* shell; the remote command still runs under `sh -lc`.
	printf "'%s'" "$(printf "%s" "${1:-}" | sed "s/'/'\\\\''/g")"
}

remote_env="$REMOTE_MTP_ONE_TOKEN_ENV"
if [ "$REMOTE_MTP_ONE_TOKEN_CMD" != "" ]; then
	case " $remote_env " in
		*" MTP_ONE_TOKEN_CMD="*) ;;
		*) remote_env="$remote_env MTP_ONE_TOKEN_CMD=$(sh_quote "$REMOTE_MTP_ONE_TOKEN_CMD")" ;;
	esac
fi

mkdir -p "$OUT_DIR"
echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/mtp_one_token_draft_probe_spark.md"

{
	echo "# One-Token MTP Draft Probe (Spark, sidecar-gated)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo
	echo "## Safety Gates"
	echo
	echo "This runner only executes when explicitly enabled on Spark."
	echo "Set env vars on Spark via REMOTE_MTP_ONE_TOKEN_ENV:"
	echo
	echo "- ALLOW_RUN=1"
	echo "- MTP_ONE_TOKEN_CMD='...'"
	echo
	echo "Optional sidecar gate (Spark-side):"
	echo
	echo "- MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf (optional; defaults to Spark-staged artifact if readable; URL requires ALLOW_URL=1)"
	echo "- ALLOW_URL=1 (required when MTP_SIDECAR_GGUF is a URL)"
	echo
	echo "Remote one-token env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo '```'
	echo "$remote_env"
	echo '```'
	echo
	echo "Remote sidecar env (recorded):"
	echo
	echo '```'
	echo "$REMOTE_MTP_SIDECAR_ENV"
	echo '```'
	echo
	echo "Remote sidecar args (recorded):"
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

echo "== uploading sidecar probe script to spark =="
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_probe_mtp_sidecar.py && chmod +x /tmp/model_contract_probe_mtp_sidecar.py" \
	<"$repo_root/scripts/model_contract_probe_mtp_sidecar.py" \
	>"$OUT_DIR/remote_sidecar_upload_stdout.txt" 2>"$OUT_DIR/remote_sidecar_upload_stderr.txt" || true

echo "== running one-token MTP draft probe on spark (with sidecar gate; may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_validate_mtp_one_token_draft_probe.py && chmod +x /tmp/model_contract_validate_mtp_one_token_draft_probe.py && $remote_env $REMOTE_MTP_SIDECAR_ENV sh -lc '
set -eu
if [ \"${ALLOW_RUN:-0}\" != \"1\" ]; then
  echo \"run skipped: set ALLOW_RUN=1 on Spark to enable\"
  exit 0
fi
if [ \"${MTP_ONE_TOKEN_CMD:-}\" = \"\" ]; then
  echo \"run skipped: set MTP_ONE_TOKEN_CMD=\\\"...\\\" on Spark (full command line)\"
  exit 0
fi

sidecar_out_json=\"/tmp/mtp_sidecar_probe.json\"
sidecar_err_txt=\"/tmp/mtp_sidecar_probe.stderr.txt\"
rm -f \"$sidecar_out_json\" \"$sidecar_err_txt\"

sidecar_ok=0
if [ \"${MTP_SIDECAR_GGUF:-}\" = \"\" ]; then
  for p in \
    /home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /home/spark1/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /home/spark/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /mnt/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
    /models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf
  do
    if [ -r \"$p\" ]; then
      MTP_SIDECAR_GGUF=\"$p\"
      export MTP_SIDECAR_GGUF
      echo \"defaulted MTP_SIDECAR_GGUF=$p\" 1>&2
      break
    fi
  done
fi

if [ \"${MTP_SIDECAR_GGUF:-}\" != \"\" ]; then
  case \"${MTP_SIDECAR_GGUF}\" in
    http://*|https://*)
      if [ \"${ALLOW_URL:-0}\" != \"1\" ]; then
        echo \"sidecar gate skipped: MTP_SIDECAR_GGUF is a URL; set ALLOW_URL=1 on Spark to enable URL range-read probe\" 1>&2
      else
        python3 /tmp/model_contract_probe_mtp_sidecar.py --url \"${MTP_SIDECAR_GGUF}\" '"$REMOTE_MTP_SIDECAR_ARGS"' >\"$sidecar_out_json\" 2>\"$sidecar_err_txt\" || true
      fi
      ;;
    *)
      if [ ! -r \"${MTP_SIDECAR_GGUF}\" ]; then
        echo \"sidecar gate skipped: MTP_SIDECAR_GGUF not readable: ${MTP_SIDECAR_GGUF}\" 1>&2
      else
        python3 /tmp/model_contract_probe_mtp_sidecar.py --path \"${MTP_SIDECAR_GGUF}\" '"$REMOTE_MTP_SIDECAR_ARGS"' >\"$sidecar_out_json\" 2>\"$sidecar_err_txt\" || true
      fi
      ;;
  esac
fi

if [ -r \"$sidecar_out_json\" ]; then
  python3 - \"$sidecar_out_json\" 2>/dev/null <<\"PY\" && sidecar_ok=1 || true
import json
import sys
from pathlib import Path
p = Path(sys.argv[1])
doc = json.loads(p.read_text(encoding=\"utf-8\"))
raise SystemExit(0 if isinstance(doc, dict) and bool(doc.get(\"ok\", False)) else 1)
PY
fi

out_json=\"/tmp/mtp_one_token_probe.json\"
v1_json=\"/tmp/mtp_one_token_probe_validate.json\"
v2_json=\"/tmp/mtp_one_token_probe_validate_sidecar.json\"
rm -f \"$out_json\" \"$v1_json\" \"$v2_json\"

sh -lc \"$MTP_ONE_TOKEN_CMD\" >\"$out_json\"
python3 /tmp/model_contract_validate_mtp_one_token_draft_probe.py --probe-json \"$out_json\" --json >\"$v1_json\" || true

if [ $sidecar_ok -eq 1 ]; then
  python3 /tmp/model_contract_validate_mtp_one_token_draft_probe.py --probe-json \"$out_json\" --sidecar-probe-json \"$sidecar_out_json\" --json >\"$v2_json\" || true
fi

if [ -r \"$sidecar_out_json\" ]; then
  echo \"== sidecar gate (probe JSON prefix) ==\" 1>&2
  sed -n \"1,120p\" \"$sidecar_out_json\" 1>&2 || true
fi
if [ -r \"$sidecar_err_txt\" ]; then
  echo \"== sidecar gate (stderr prefix) ==\" 1>&2
  sed -n \"1,120p\" \"$sidecar_err_txt\" 1>&2 || true
fi
if [ -r \"$v1_json\" ]; then
  echo \"== validation (no sidecar) ==\" 1>&2
  cat \"$v1_json\" 1>&2
fi
if [ -r \"$v2_json\" ]; then
  echo \"== validation (sidecar cross-check) ==\" 1>&2
  cat \"$v2_json\" 1>&2
fi
cat \"$out_json\"
' " <"$repo_root/scripts/model_contract_validate_mtp_one_token_draft_probe.py" \
	>"$OUT_DIR/remote_mtp_one_token_stdout.txt" 2>"$OUT_DIR/remote_mtp_one_token_stderr.txt" || true

echo "== fetching sidecar probe JSON from spark (best-effort) =="
ssh $SSH_OPTS "$target" "cat /tmp/mtp_sidecar_probe.json" \
	>"$OUT_DIR/sidecar_probe_remote.json" 2>"$OUT_DIR/sidecar_probe_remote_stderr.txt" || true

echo "== verifying sidecar payload fingerprints against pinned antirez reference (local; best-effort) =="
if [ -r "$OUT_DIR/sidecar_probe_remote.json" ]; then
	python3 "$repo_root/scripts/verify_mtp_sidecar_payload_fingerprint.py" \
		--probe-json "$OUT_DIR/sidecar_probe_remote.json" \
		--json \
		>"$OUT_DIR/sidecar_probe_fingerprint_gate.json" 2>"$OUT_DIR/sidecar_probe_fingerprint_gate_stderr.txt" || true
else
	printf '%s\n' "{\"ok\":false,\"skipped\":true,\"reason\":\"sidecar_probe_remote.json missing\"}" >"$OUT_DIR/sidecar_probe_fingerprint_gate.json"
	printf '%s\n' "" >"$OUT_DIR/sidecar_probe_fingerprint_gate_stderr.txt"
fi

python3 - "$OUT_DIR/remote_mtp_one_token_stdout.txt" "$OUT_DIR/mtp_one_token_probe.json" >"$OUT_DIR/mtp_one_token_probe_parse.json" 2>/dev/null <<'PY' || true
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

{
	echo "## Results"
	echo
	echo "This runner does not fetch/build. It runs the command provided via Spark env, then (optionally) cross-checks MTP params against a Spark-side sidecar contract probe."
	echo
	echo "Stdout (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_mtp_one_token_stdout.txt" || true
	echo '```'
	echo
	echo "Stderr (prefix):"
	echo
	echo '```'
	sed -n '1,200p' "$OUT_DIR/remote_mtp_one_token_stderr.txt" || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $OUT_DIR/remote_mtp_one_token_stdout.txt"
	echo "- stderr: $OUT_DIR/remote_mtp_one_token_stderr.txt"
	echo "- probe JSON (if parseable): $OUT_DIR/mtp_one_token_probe.json"
	echo "- parsed status: $OUT_DIR/mtp_one_token_probe_parse.json"
	echo "- sidecar probe JSON (best-effort): $OUT_DIR/sidecar_probe_remote.json"
	echo "- sidecar probe fetch stderr: $OUT_DIR/sidecar_probe_remote_stderr.txt"
	echo "- sidecar fingerprint gate JSON (local): $OUT_DIR/sidecar_probe_fingerprint_gate.json"
	echo "- sidecar fingerprint gate stderr (local): $OUT_DIR/sidecar_probe_fingerprint_gate_stderr.txt"
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
