#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: run_ds4_mtp_acceptance_probe_spark.sh [user@host]

Run a *multi-token* DS4 MTP acceptance probe on Spark (remote) and parse the
resulting `DS4_MTP_CONF_LOG=1` output into JSONL + a summary.

This runner is safety-gated on Spark:
  - requires ALLOW_RUN=1
  - requires MTP_ACCEPT_CMD="..." (full remote command line)

It records exact remote env + command string in the report, then extracts:
  - drafted/committed histograms
  - estimated draft-token acceptance rate
  - target_next vs draft_next mismatches
  - token strings via fixtures/model_contract/deepseek_v4_flash/tokenizer.json

Examples:
  REMOTE_MTP_ACCEPT_ENV="ALLOW_RUN=1 DS4_MTP_CONF_LOG=1" \\
  REMOTE_MTP_ACCEPT_CMD='~/src/ds4/ds4 --cuda ... --mtp-draft 2 -n 32' \\
  ./scripts/run_ds4_mtp_acceptance_probe_spark.sh spark0@172.16.11.228
EOF
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

target="${1:-spark0@172.16.11.228}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_acceptance_probe}"
REMOTE_MTP_ACCEPT_ENV="${REMOTE_MTP_ACCEPT_ENV:-}"
REMOTE_MTP_ACCEPT_CMD="${REMOTE_MTP_ACCEPT_CMD:-}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"
mkdir -p "$OUT_DIR"
echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/ds4_mtp_acceptance_probe_spark.md"
STDOUT_TXT="$OUT_DIR/remote_accept_stdout.txt"
STDERR_TXT="$OUT_DIR/remote_accept_stderr.txt"

sh_quote()
{
	printf "'%s'" "$(printf "%s" "${1:-}" | sed "s/'/'\\\\''/g")"
}

remote_env="$REMOTE_MTP_ACCEPT_ENV"
if [ "$REMOTE_MTP_ACCEPT_CMD" != "" ]; then
	case " $remote_env " in
		*" MTP_ACCEPT_CMD="*) ;;
		*) remote_env="$remote_env MTP_ACCEPT_CMD=$(sh_quote "$REMOTE_MTP_ACCEPT_CMD")" ;;
	esac
fi

{
	echo "# DS4 MTP Acceptance Probe (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo
	echo "## Safety Gates"
	echo
	echo "This runner only runs when Spark-side env explicitly enables it:"
	echo "- ALLOW_RUN=1"
	echo "- MTP_ACCEPT_CMD='...'"
	echo
	echo "Remote env (verbatim):"
	echo
	echo '```'
	echo "$remote_env"
	echo '```'
	echo
	echo "Remote command (verbatim):"
	echo
	echo '```'
	echo "$REMOTE_MTP_ACCEPT_CMD"
	echo '```'
	echo
	echo "## Spark Host"
	echo
	echo '```'
	ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true' || true
	echo '```'
	echo
} >"$REPORT_MD"

echo "== running remote acceptance probe (may be gated) =="
ssh $SSH_OPTS "$target" "$remote_env sh -s" >"$STDOUT_TXT" 2>"$STDERR_TXT" <<'SH' || true
set -eu
if [ "${ALLOW_RUN:-0}" != "1" ]; then
  echo "run skipped: set ALLOW_RUN=1 on Spark to enable"
  exit 0
fi
if [ "${MTP_ACCEPT_CMD:-}" = "" ]; then
  echo "run skipped: set MTP_ACCEPT_CMD=\"...\" on Spark (full command line)"
  exit 0
fi
sh -lc "$MTP_ACCEPT_CMD"
SH

echo "== extracting ds4: mtp conf/timing events =="
python3 "$repo_root/scripts/extract_ds4_mtp_conf_log_events.py" \
	--in "$STDOUT_TXT" \
	--in "$STDERR_TXT" \
	--out-dir "$OUT_DIR/extract" \
	>"$OUT_DIR/extract_stdout.txt" 2>"$OUT_DIR/extract_stderr.txt" || true

echo "== enriching events with tokens =="
python3 "$repo_root/scripts/enrich_mtp_acceptance_events_with_tokens.py" \
	--in-jsonl "$OUT_DIR/extract/events.jsonl" \
	--tokenizer-json "$repo_root/fixtures/model_contract/deepseek_v4_flash/tokenizer.json" \
	--out-jsonl "$OUT_DIR/extract/events.tokens.jsonl" \
	--out-report-json "$OUT_DIR/extract/mismatch_report.json" \
	>"$OUT_DIR/enrich_stdout.txt" 2>"$OUT_DIR/enrich_stderr.txt" || true

{
	echo "## Results"
	echo
	echo "Artifacts:"
	echo
	echo "- stdout: $STDOUT_TXT"
	echo "- stderr: $STDERR_TXT"
	echo "- extracted events: $OUT_DIR/extract/events.jsonl"
	echo "- extracted summary: $OUT_DIR/extract/summary.json"
	echo "- enriched events: $OUT_DIR/extract/events.tokens.jsonl"
	echo "- mismatch report: $OUT_DIR/extract/mismatch_report.json"
	echo
	echo "Summary (best-effort):"
	echo
	echo '```'
	sed -n '1,120p' "$OUT_DIR/extract/summary.json" 2>/dev/null || true
	echo '```'
	echo
} >>"$REPORT_MD"

echo "done: $REPORT_MD"

