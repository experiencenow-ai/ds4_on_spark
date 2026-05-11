#!/usr/bin/env sh
set -eu

# Wrapper: antirez/ds4 baseline on the local Mac (Metal), with optional MODEL_RUNS_CSV append + scoring.
#
# Safety posture:
# - Does not download weights unless benchmark_ds4_macos.sh is run with ALLOW_FETCH=1 and you have approved it.
# - Does not build unless ALLOW_BUILD=1.
# - Does not run inference unless ALLOW_RUN=1.

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"
RUN_LABEL="${RUN_LABEL:-ds4-macos}"
MODEL_RUNS_CSV="${MODEL_RUNS_CSV:-}"
DS4_SCOPE="${DS4_SCOPE:-ds4_macos}"
DS4_MODEL_ID="${DS4_MODEL_ID:-antirez/ds4}"

PUBLIC_QUALITY_PRIOR="${PUBLIC_QUALITY_PRIOR:-}"
PUBLIC_QUALITY_BASIS="${PUBLIC_QUALITY_BASIS:-}"
PUBLIC_QUALITY_SOURCE="${PUBLIC_QUALITY_SOURCE:-}"
PASSED_TASKS="${PASSED_TASKS:-}"
TOTAL_TASKS="${TOTAL_TASKS:-}"
LOCAL_QUALITY_SCORE="${LOCAL_QUALITY_SCORE:-}"
QUALITY_SCORE="${QUALITY_SCORE:-}"

ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

DS4_DIR="${DS4_DIR:-}"
MODEL_GGUF="${MODEL_GGUF:-}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
CTX="${CTX:-32768}"
N_TOKENS="${N_TOKENS:-256}"
EXTRA_ARGS="${EXTRA_ARGS:---nothink}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"
if [ "$RUN_LABEL" != "" ]; then
	OUT_DIR="$OUT_ROOT/$ts-$RUN_LABEL"
fi
mkdir -p "$OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -e "$repo_root/.git2/.git" ]; then
	repo_rev="$(GIT_DIR="$repo_root/.git2/.git" GIT_WORK_TREE="$repo_root" git rev-parse HEAD 2>/dev/null || echo unknown)"
elif [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/baseline_ds4_macos.md"
DS4_STDOUT="$OUT_DIR/ds4_macos_stdout.txt"
DS4_STDERR="$OUT_DIR/ds4_macos_stderr.txt"

extract_baseline_summary()
{
	in="$1"
	if [ ! -r "$in" ]; then
		return 0
	fi
	awk '
		found==1 {
			if ($0 ~ /^== /) exit
			print
		}
		$0 == "== baseline summary (approx) ==" { found=1 }
	' "$in" 2>/dev/null || true
}

append_model_runs_csv()
{
	summary_path="$1"
	if [ "$MODEL_RUNS_CSV" = "" ] || [ "$summary_path" = "" ] || [ ! -r "$summary_path" ]; then
		return 0
	fi
	run_id="$ts-$DS4_SCOPE"
	if [ "$RUN_LABEL" != "" ]; then
		run_id="$ts-$RUN_LABEL-$DS4_SCOPE"
	fi
	python3 - "$MODEL_RUNS_CSV" "$DS4_MODEL_ID" "$run_id" "$DS4_SCOPE" "$PUBLIC_QUALITY_PRIOR" "$PUBLIC_QUALITY_BASIS" "$PUBLIC_QUALITY_SOURCE" "$PASSED_TASKS" "$TOTAL_TASKS" "$LOCAL_QUALITY_SCORE" "$QUALITY_SCORE" "$summary_path" 2>/dev/null <<'PY' || true
import csv
import os
import sys

csv_path = sys.argv[1]
model = sys.argv[2]
run_id = sys.argv[3]
scope = sys.argv[4]
public_quality_prior = sys.argv[5].strip()
public_quality_basis = sys.argv[6].strip()
public_quality_source = sys.argv[7].strip()
passed_tasks = sys.argv[8].strip()
total_tasks = sys.argv[9].strip()
local_quality_score = sys.argv[10].strip()
quality_score = sys.argv[11].strip()
summary_path = sys.argv[12]

kv = {}
try:
    summary_text = open(summary_path, "r", encoding="utf-8").read()
except OSError:
    summary_text = ""
for raw_line in summary_text.splitlines():
    line = raw_line.strip()
    if not line or "=" not in line:
        continue
    k, v = line.split("=", 1)
    k = k.strip()
    v = v.strip()
    if k:
        kv[k] = v

def _get(*names: str) -> str:
    for n in names:
        v = kv.get(n, "").strip()
        if v:
            return v
    return ""

row = {
    "model": model,
    "run_id": run_id,
    "scope": scope,
    "public_quality_prior": public_quality_prior,
    "public_quality_basis": public_quality_basis,
    "public_quality_source": public_quality_source,
    "passed_tasks": passed_tasks,
    "total_tasks": total_tasks,
    "local_quality_score": local_quality_score,
    "quality_score": quality_score,
    "decode_tps": _get("generation_tps", "decode_tps"),
    "prefill_tps": _get("prefill_tps"),
    "ttft_s": _get("ttft_first_output_s", "ttft_s"),
    "total_wall_s": _get("wall_s", "total_wall_s"),
    "output_tokens": _get("output_tokens", "generated_tokens"),
}

header = [
    "model",
    "run_id",
    "scope",
    "public_quality_prior",
    "public_quality_basis",
    "public_quality_source",
    "passed_tasks",
    "total_tasks",
    "local_quality_score",
    "quality_score",
    "decode_tps",
    "prefill_tps",
    "ttft_s",
    "total_wall_s",
    "output_tokens",
]

need_header = True
if os.path.exists(csv_path):
    try:
        need_header = (os.stat(csv_path).st_size == 0)
    except OSError:
        need_header = True

os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
with open(csv_path, "a", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=header)
    if need_header:
        w.writeheader()
    w.writerow({k: row.get(k, "") for k in header})
PY
}

score_model_runs_csv()
{
	if [ "$MODEL_RUNS_CSV" = "" ] || [ ! -r "$MODEL_RUNS_CSV" ]; then
		return 0
	fi
	if [ ! -r "$repo_root/scripts/model_quality_speed_score.py" ]; then
		return 0
	fi
	python3 "$repo_root/scripts/model_quality_speed_score.py" "$MODEL_RUNS_CSV" >"$OUT_DIR/model_quality_speed_score.md" 2>"$OUT_DIR/model_quality_speed_score_stderr.txt" || true
	python3 "$repo_root/scripts/model_quality_speed_score.py" "$MODEL_RUNS_CSV" --json >"$OUT_DIR/model_quality_speed_score.json" 2>>"$OUT_DIR/model_quality_speed_score_stderr.txt" || true
}

{
	echo "# Baseline: antirez/ds4 (Mac / Metal)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- Host: $(hostname 2>/dev/null || echo unknown)"
	echo "- uname: $(uname -a 2>/dev/null || echo unknown)"
	echo
	echo "## Command"
	echo
	echo "Environment:"
	echo
	echo '```text'
	echo "ALLOW_FETCH=$ALLOW_FETCH"
	echo "ALLOW_BUILD=$ALLOW_BUILD"
	echo "ALLOW_RUN=$ALLOW_RUN"
	if [ "$DS4_DIR" != "" ]; then echo "DS4_DIR=$DS4_DIR"; fi
	if [ "$MODEL_GGUF" != "" ]; then echo "MODEL_GGUF=$MODEL_GGUF"; fi
	echo "PROMPT=$PROMPT"
	echo "CTX=$CTX"
	echo "N_TOKENS=$N_TOKENS"
	echo "EXTRA_ARGS=$EXTRA_ARGS"
	echo '```'
	echo
	echo "Runner:"
	echo
	echo '```sh'
	echo "OUT_DIR='$OUT_DIR' \\"
	echo "ALLOW_FETCH='$ALLOW_FETCH' ALLOW_BUILD='$ALLOW_BUILD' ALLOW_RUN='$ALLOW_RUN' \\"
	if [ "$DS4_DIR" != "" ]; then echo "DS4_DIR='$DS4_DIR' \\"; fi
	if [ "$MODEL_GGUF" != "" ]; then echo "MODEL_GGUF='$MODEL_GGUF' \\"; fi
	echo "PROMPT='$PROMPT' CTX='$CTX' N_TOKENS='$N_TOKENS' EXTRA_ARGS='$EXTRA_ARGS' \\"
	echo "scripts/benchmark_ds4_macos.sh"
	echo '```'
	echo
} >"$REPORT_MD"

OUT_DIR="$OUT_DIR" ALLOW_FETCH="$ALLOW_FETCH" ALLOW_BUILD="$ALLOW_BUILD" ALLOW_RUN="$ALLOW_RUN" DS4_DIR="$DS4_DIR" MODEL_GGUF="$MODEL_GGUF" PROMPT="$PROMPT" CTX="$CTX" N_TOKENS="$N_TOKENS" EXTRA_ARGS="$EXTRA_ARGS" \
	scripts/benchmark_ds4_macos.sh >"$DS4_STDOUT" 2>"$DS4_STDERR" || true

append_model_runs_csv "$DS4_STDOUT"
score_model_runs_csv

{
	echo "## ds4 (Mac / Metal)"
	echo
	echo "Summary (best-effort):"
	echo
	echo '```text'
	extract_baseline_summary "$DS4_STDOUT"
	echo '```'
	echo
	echo "Full logs:"
	echo
	echo "- stdout: $DS4_STDOUT"
	echo "- stderr: $DS4_STDERR"
	echo
	if [ "$MODEL_RUNS_CSV" != "" ]; then
		echo "## Quality/speed scoring (local)"
		echo
		echo "- model_runs_csv: $MODEL_RUNS_CSV"
		echo "- score_md: $OUT_DIR/model_quality_speed_score.md"
		echo "- score_json: $OUT_DIR/model_quality_speed_score.json"
		echo
	fi
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
