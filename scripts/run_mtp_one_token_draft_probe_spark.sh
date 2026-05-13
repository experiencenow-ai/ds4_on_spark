#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_one_token_probe}"
REMOTE_MTP_ONE_TOKEN_ENV="${REMOTE_MTP_ONE_TOKEN_ENV:-}"
REMOTE_MTP_ONE_TOKEN_CMD="${REMOTE_MTP_ONE_TOKEN_CMD:-}"
REMOTE_SIDE_CAR_PROBE_JSON="${REMOTE_SIDE_CAR_PROBE_JSON:-}"
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
if [ "$REMOTE_SIDE_CAR_PROBE_JSON" != "" ]; then
	case " $remote_env " in
		*" SIDE_CAR_PROBE_JSON="*) ;;
		*) remote_env="$remote_env SIDE_CAR_PROBE_JSON=$(sh_quote "$REMOTE_SIDE_CAR_PROBE_JSON")" ;;
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
	echo "# One-Token MTP Draft Probe (Spark)"
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
	echo "Remote MTP one-token env:"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo '```'
	echo "$remote_env"
	echo '```'
	echo
	echo "Remote MTP one-token command:"
	echo
	echo "The command is expected to write a single JSON object to stdout."
	echo "It should run quickly (1 prompt, 1 verify step, gamma=1)."
	echo
	echo '```'
	echo "$REMOTE_MTP_ONE_TOKEN_CMD"
	echo '```'
	echo
	echo "Optional sidecar-probe JSON (remote path):"
	echo
	echo '```'
	echo "$REMOTE_SIDE_CAR_PROBE_JSON"
	echo '```'
	echo
	echo "## Spark Probe"
	echo
	echo '```'
	ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true'
	echo '```'
	echo
} >"$REPORT_MD"

echo "== running one-token MTP draft probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_validate_mtp_one_token_draft_probe.py && chmod +x /tmp/model_contract_validate_mtp_one_token_draft_probe.py" \
	<"$repo_root/scripts/model_contract_validate_mtp_one_token_draft_probe.py" \
	>"$OUT_DIR/remote_upload_validator_stdout.txt" 2>"$OUT_DIR/remote_upload_validator_stderr.txt" || true

ssh $SSH_OPTS "$target" "$remote_env sh -s" \
	>"$OUT_DIR/remote_mtp_one_token_stdout.txt" 2>"$OUT_DIR/remote_mtp_one_token_stderr.txt" <<'SH' || true
set -eu
if [ "${ALLOW_RUN:-0}" != "1" ]; then
  echo "run skipped: set ALLOW_RUN=1 on Spark to enable"
  exit 0
fi
if [ "${MTP_ONE_TOKEN_CMD:-}" = "" ]; then
  echo "run skipped: set MTP_ONE_TOKEN_CMD=\"...\" on Spark (full command line)"
  exit 0
fi
out_json="/tmp/mtp_one_token_probe.json"
v1_json="/tmp/mtp_one_token_probe_validate.json"
v2_json="/tmp/mtp_one_token_probe_validate_sidecar.json"
rm -f "$out_json"
rm -f "$v1_json" "$v2_json"
sh -lc "$MTP_ONE_TOKEN_CMD" >"$out_json"
python3 /tmp/model_contract_validate_mtp_one_token_draft_probe.py --probe-json "$out_json" --json >"$v1_json" || true
if [ "${SIDE_CAR_PROBE_JSON:-}" != "" ] && [ -r "${SIDE_CAR_PROBE_JSON}" ]; then
  python3 /tmp/model_contract_validate_mtp_one_token_draft_probe.py --probe-json "$out_json" --sidecar-probe-json "${SIDE_CAR_PROBE_JSON}" --json >"$v2_json" || true
fi
if [ -r "$v1_json" ]; then
  echo "== validation (no sidecar) ==" 1>&2
  cat "$v1_json" 1>&2
fi
if [ -r "$v2_json" ]; then
  echo "== validation (sidecar cross-check) ==" 1>&2
  cat "$v2_json" 1>&2
fi
cat "$out_json"
SH

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

echo "== fetching remote one-token validation JSON (best-effort) =="
ssh $SSH_OPTS "$target" "cat /tmp/mtp_one_token_probe_validate.json" \
	>"$OUT_DIR/mtp_one_token_probe_validate_remote.json" 2>"$OUT_DIR/mtp_one_token_probe_validate_remote_stderr.txt" || true
ssh $SSH_OPTS "$target" "cat /tmp/mtp_one_token_probe_validate_sidecar.json" \
	>"$OUT_DIR/mtp_one_token_probe_validate_sidecar_remote.json" 2>"$OUT_DIR/mtp_one_token_probe_validate_sidecar_remote_stderr.txt" || true

{
	echo "## Results"
	echo
	echo "This runner does not build or fetch anything. It only runs the command provided via Spark env."
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
	echo "- validate JSON (remote; best-effort): $OUT_DIR/mtp_one_token_probe_validate_remote.json"
	echo "- validate stderr (remote; best-effort): $OUT_DIR/mtp_one_token_probe_validate_remote_stderr.txt"
	echo "- validate sidecar JSON (remote; best-effort): $OUT_DIR/mtp_one_token_probe_validate_sidecar_remote.json"
	echo "- validate sidecar stderr (remote; best-effort): $OUT_DIR/mtp_one_token_probe_validate_sidecar_remote_stderr.txt"
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
v1 = read_json(out_dir / "mtp_one_token_probe_validate_remote.json")
v2 = read_json(out_dir / "mtp_one_token_probe_validate_sidecar_remote.json")

probe_ok = bool(probe_parse.get("ok", False))
validate_ok = bool(v1.get("ok", False)) if isinstance(v1, dict) else False
validate_sidecar_ok = bool(v2.get("ok", False)) if isinstance(v2, dict) else False

summary = {
	"ok": bool(probe_ok and validate_ok),
	"probe_ok": probe_ok,
	"validate_ok": validate_ok,
	"validate_sidecar_ok": validate_sidecar_ok,
	"artifacts": {
		"report_md": str(report_md),
		"probe_json": str(out_dir / "mtp_one_token_probe.json"),
		"probe_parse_json": str(out_dir / "mtp_one_token_probe_parse.json"),
		"validate_remote_json": str(out_dir / "mtp_one_token_probe_validate_remote.json"),
		"validate_sidecar_remote_json": str(out_dir / "mtp_one_token_probe_validate_sidecar_remote.json"),
	},
	"probe_parse": probe_parse,
	"validate_remote": v1 if isinstance(v1, dict) else None,
	"validate_sidecar_remote": v2 if isinstance(v2, dict) else None,
}

(out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
