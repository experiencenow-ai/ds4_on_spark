#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_mtp_oracle_vs_candidate_diff}"
REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV="${REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV:-}"
REMOTE_MTP_ONE_TOKEN_ENV="${REMOTE_MTP_ONE_TOKEN_ENV:-}"
REMOTE_MTP_ONE_TOKEN_CMD="${REMOTE_MTP_ONE_TOKEN_CMD:-}"
REMOTE_SIDE_CAR_PROBE_JSON="${REMOTE_SIDE_CAR_PROBE_JSON:-}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"
ORACLE_OUT="$OUT_DIR/oracle"
CAND_OUT="$OUT_DIR/candidate"

mkdir -p "$OUT_DIR" "$ORACLE_OUT" "$CAND_OUT"
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

REPORT_MD="$OUT_DIR/mtp_oracle_vs_candidate_diff_spark.md"

{
	echo "# MTP One-Token: antirez/ds4 oracle vs candidate diff (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo
	echo "## Safety Gates"
	echo
	echo "This wrapper runs two gated runners:"
	echo
	echo "- Oracle: `scripts/run_antirez_ds4_mtp_one_token_oracle_probe_spark.sh`"
	echo "- Candidate: `scripts/run_mtp_one_token_draft_probe_spark.sh`"
	echo
	echo "Neither does anything on Spark unless the corresponding `ALLOW_*` env vars are set there."
	echo
	echo "Remote env (recorded):"
	echo
	echo "Do not put secrets in REMOTE_* env values; this report records them."
	echo
	echo "Oracle env (REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV):"
	echo
	echo '```'
	echo "$REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV"
	echo '```'
	echo
	echo "Candidate env (REMOTE_MTP_ONE_TOKEN_ENV + inferred vars):"
	echo
	echo '```'
	echo "$REMOTE_MTP_ONE_TOKEN_ENV"
	echo '```'
	echo
	echo "Candidate cmd (REMOTE_MTP_ONE_TOKEN_CMD):"
	echo
	echo '```'
	echo "$REMOTE_MTP_ONE_TOKEN_CMD"
	echo '```'
	echo
	echo "Candidate sidecar-probe JSON (REMOTE_SIDE_CAR_PROBE_JSON):"
	echo
	echo '```'
	echo "$REMOTE_SIDE_CAR_PROBE_JSON"
	echo '```'
	echo
	echo "## Spark Host Info"
	echo
	echo '```'
	ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true'
	echo '```'
	echo
} >"$REPORT_MD"

echo "== running oracle runner (may be gated) =="
OUT_ROOT="$ORACLE_OUT" REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV="$REMOTE_ANTIREZ_DS4_MTP_ORACLE_ENV" \
	"$repo_root/scripts/run_antirez_ds4_mtp_one_token_oracle_probe_spark.sh" "$target" \
	>"$OUT_DIR/oracle_runner_stdout.txt" 2>"$OUT_DIR/oracle_runner_stderr.txt" || true

oracle_run_dir=""
if [ -d "$ORACLE_OUT" ]; then
	oracle_run_dir="$(ls -1t "$ORACLE_OUT" 2>/dev/null | head -n 1 || true)"
fi
ORACLE_JSON=""
if [ "$oracle_run_dir" != "" ] && [ -r "$ORACLE_OUT/$oracle_run_dir/mtp_one_token_probe.json" ]; then
	ORACLE_JSON="$ORACLE_OUT/$oracle_run_dir/mtp_one_token_probe.json"
fi

echo "== running candidate runner (may be gated) =="
OUT_ROOT="$CAND_OUT" REMOTE_MTP_ONE_TOKEN_ENV="$REMOTE_MTP_ONE_TOKEN_ENV" REMOTE_MTP_ONE_TOKEN_CMD="$REMOTE_MTP_ONE_TOKEN_CMD" REMOTE_SIDE_CAR_PROBE_JSON="$REMOTE_SIDE_CAR_PROBE_JSON" \
	"$repo_root/scripts/run_mtp_one_token_draft_probe_spark.sh" "$target" \
	>"$OUT_DIR/candidate_runner_stdout.txt" 2>"$OUT_DIR/candidate_runner_stderr.txt" || true

cand_run_dir=""
if [ -d "$CAND_OUT" ]; then
	cand_run_dir="$(ls -1t "$CAND_OUT" 2>/dev/null | head -n 1 || true)"
fi
CAND_JSON=""
if [ "$cand_run_dir" != "" ] && [ -r "$CAND_OUT/$cand_run_dir/mtp_one_token_probe.json" ]; then
	CAND_JSON="$CAND_OUT/$cand_run_dir/mtp_one_token_probe.json"
fi

echo "== diffing oracle vs candidate (local; best-effort) =="
DIFF_JSON="$OUT_DIR/oracle_vs_candidate_diff.json"
DIFF_STDERR="$OUT_DIR/oracle_vs_candidate_diff_stderr.txt"
if [ "$ORACLE_JSON" != "" ] && [ "$CAND_JSON" != "" ]; then
	python3 "$repo_root/scripts/diff_mtp_one_token_draft_probe.py" --a "$ORACLE_JSON" --b "$CAND_JSON" --json \
		>"$DIFF_JSON" 2>"$DIFF_STDERR" || true
else
	printf '%s\n' "{\"ok\":false,\"skipped\":true,\"reason\":\"missing oracle or candidate probe JSON\"}" >"$DIFF_JSON"
	printf '%s\n' "" >"$DIFF_STDERR"
fi

{
	echo "## Results"
	echo
	echo "Oracle probe JSON:"
	echo
	echo '```'
	echo "$ORACLE_JSON"
	echo '```'
	echo
	echo "Candidate probe JSON:"
	echo
	echo '```'
	echo "$CAND_JSON"
	echo '```'
	echo
	echo "Local diff output:"
	echo
	echo '```'
	sed -n '1,200p' "$DIFF_JSON" 2>/dev/null || true
	echo '```'
	echo
	echo "Artifacts:"
	echo
	echo "- report: $REPORT_MD"
	echo "- oracle runner stdout: $OUT_DIR/oracle_runner_stdout.txt"
	echo "- oracle runner stderr: $OUT_DIR/oracle_runner_stderr.txt"
	echo "- candidate runner stdout: $OUT_DIR/candidate_runner_stdout.txt"
	echo "- candidate runner stderr: $OUT_DIR/candidate_runner_stderr.txt"
	echo "- diff JSON: $DIFF_JSON"
	echo "- diff stderr: $DIFF_STDERR"
	echo
	echo "Next step: if the diff fails early, add more `*_fnv64` captures to the candidate probe before attempting acceptance sweeps."
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

diff = read_json(out_dir / "oracle_vs_candidate_diff.json")
ok = bool(diff.get("ok", False)) if isinstance(diff, dict) else False

summary = {
	"ok": ok,
	"artifacts": {
		"report_md": str(report_md),
		"diff_json": str(out_dir / "oracle_vs_candidate_diff.json"),
	},
	"diff": diff if isinstance(diff, dict) else None,
}

(out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "done: $REPORT_MD"
