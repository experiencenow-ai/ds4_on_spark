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
repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"

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
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_validate_mtp_one_token_draft_probe.py && chmod +x /tmp/model_contract_validate_mtp_one_token_draft_probe.py && $remote_env sh -lc '
set -eu
if [ \"${ALLOW_RUN:-0}\" != \"1\" ]; then
  echo \"run skipped: set ALLOW_RUN=1 on Spark to enable\"
  exit 0
fi
if [ \"${MTP_ONE_TOKEN_CMD:-}\" = \"\" ]; then
  echo \"run skipped: set MTP_ONE_TOKEN_CMD=\\\"...\\\" on Spark (full command line)\"
  exit 0
fi
out_json=\"/tmp/mtp_one_token_probe.json\"
rm -f \"$out_json\"
sh -lc \"$MTP_ONE_TOKEN_CMD\" >\"$out_json\"
python3 /tmp/model_contract_validate_mtp_one_token_draft_probe.py --probe-json \"$out_json\" --json
if [ \"${SIDE_CAR_PROBE_JSON:-}\" != \"\" ] && [ -r \"${SIDE_CAR_PROBE_JSON}\" ]; then
  python3 /tmp/model_contract_validate_mtp_one_token_draft_probe.py --probe-json \"$out_json\" --sidecar-probe-json \"${SIDE_CAR_PROBE_JSON}\" --json
fi
cat \"$out_json\"
' " <"$repo_root/scripts/model_contract_validate_mtp_one_token_draft_probe.py" \
	>"$OUT_DIR/remote_mtp_one_token_stdout.txt" 2>"$OUT_DIR/remote_mtp_one_token_stderr.txt" || true

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
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
