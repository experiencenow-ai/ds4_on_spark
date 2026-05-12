#!/usr/bin/env sh
set -eu

# Remote baseline wrapper for antirez/ds4 on a Spark / GB10 Linux host.
#
# Safety posture:
# - Does not download model weights.
# - Does not clone ds4 unless ALLOW_FETCH=1.
# - Does not build unless ALLOW_BUILD=1.
# - Does not run inference unless ALLOW_RUN=1 and MODEL_GGUF points to a
#   remote, already-staged GGUF.

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"
RUN_LABEL="${RUN_LABEL:-antirez-ds4-spark}"
MODEL_RUNS_CSV="${MODEL_RUNS_CSV:-}"
DS4_SCOPE="${DS4_SCOPE:-antirez_ds4_spark}"
DS4_MODEL_ID="${DS4_MODEL_ID:-antirez/ds4}"

REMOTE_WORK_ROOT="${REMOTE_WORK_ROOT:-}"
DS4_DIR="${DS4_DIR:-}"
MODEL_GGUF="${MODEL_GGUF:-}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
CTX="${CTX:-32768}"
N_TOKENS="${N_TOKENS:-256}"
EXTRA_ARGS="${EXTRA_ARGS:---nothink}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

PUBLIC_QUALITY_PRIOR="${PUBLIC_QUALITY_PRIOR:-}"
PUBLIC_QUALITY_BASIS="${PUBLIC_QUALITY_BASIS:-}"
PUBLIC_QUALITY_SOURCE="${PUBLIC_QUALITY_SOURCE:-}"
PASSED_TASKS="${PASSED_TASKS:-}"
TOTAL_TASKS="${TOTAL_TASKS:-}"
LOCAL_QUALITY_SCORE="${LOCAL_QUALITY_SCORE:-}"
QUALITY_SCORE="${QUALITY_SCORE:-}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"
if [ "$RUN_LABEL" != "" ]; then
	OUT_DIR="$OUT_ROOT/$ts-$RUN_LABEL"
fi
mkdir -p "$OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -d "$repo_root/.codex_git" ]; then
	repo_rev="$(GIT_DIR="$repo_root/.codex_git" GIT_WORK_TREE="$repo_root" git rev-parse HEAD 2>/dev/null || echo unknown)"
elif [ -e "$repo_root/.git2/.git" ]; then
	repo_rev="$(GIT_DIR="$repo_root/.git2/.git" GIT_WORK_TREE="$repo_root" git rev-parse HEAD 2>/dev/null || echo unknown)"
elif [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/baseline_antirez_ds4_spark.md"
STDOUT_TXT="$OUT_DIR/antirez_ds4_spark_stdout.txt"
STDERR_TXT="$OUT_DIR/antirez_ds4_spark_stderr.txt"
SUMMARY_TXT="$OUT_DIR/antirez_ds4_spark_summary.txt"

sh_quote()
{
	printf "'%s'" "$(printf %s "${1:-}" | sed "s/'/'\\\\''/g")"
}

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
	if [ "$MODEL_RUNS_CSV" = "" ] || [ ! -r "$SUMMARY_TXT" ]; then
		return 0
	fi
	run_id="$ts-$DS4_SCOPE"
	if [ "$RUN_LABEL" != "" ]; then
		run_id="$ts-$RUN_LABEL-$DS4_SCOPE"
	fi
	python3 - "$MODEL_RUNS_CSV" "$DS4_MODEL_ID" "$run_id" "$DS4_SCOPE" "$PUBLIC_QUALITY_PRIOR" "$PUBLIC_QUALITY_BASIS" "$PUBLIC_QUALITY_SOURCE" "$PASSED_TASKS" "$TOTAL_TASKS" "$LOCAL_QUALITY_SCORE" "$QUALITY_SCORE" "$SUMMARY_TXT" <<'PY' || true
import csv
import os
import sys

csv_path, model, run_id, scope = sys.argv[1:5]
public_quality_prior, public_quality_basis, public_quality_source = sys.argv[5:8]
passed_tasks, total_tasks, local_quality_score, quality_score = [x.strip() for x in sys.argv[8:12]]
summary_path = sys.argv[12]

kv = {}
try:
    text = open(summary_path, "r", encoding="utf-8").read()
except OSError:
    text = ""
for raw in text.splitlines():
    line = raw.strip()
    if "=" not in line:
        continue
    k, v = line.split("=", 1)
    kv[k.strip()] = v.strip()

def get(*names):
    for name in names:
        value = kv.get(name, "").strip()
        if value:
            return value
    return ""

if not local_quality_score and passed_tasks and total_tasks:
    try:
        p = float(passed_tasks)
        t = float(total_tasks)
        if t > 0:
            local_quality_score = f"{(100.0 * p / t):.6f}"
    except Exception:
        pass

header = [
    "model", "run_id", "scope", "public_quality_prior",
    "public_quality_basis", "public_quality_source", "passed_tasks",
    "total_tasks", "local_quality_score", "quality_score", "decode_tps",
    "prefill_tps", "ttft_s", "total_wall_s", "output_tokens",
]
row = {
    "model": model,
    "run_id": run_id,
    "scope": scope,
    "public_quality_prior": public_quality_prior.strip(),
    "public_quality_basis": public_quality_basis.strip(),
    "public_quality_source": public_quality_source.strip(),
    "passed_tasks": passed_tasks,
    "total_tasks": total_tasks,
    "local_quality_score": local_quality_score,
    "quality_score": quality_score,
    "decode_tps": get("decode_tps", "generation_tps"),
    "prefill_tps": get("prefill_tps"),
    "ttft_s": get("ttft_s", "ttft_first_output_s"),
    "total_wall_s": get("total_wall_s", "wall_s"),
    "output_tokens": get("output_tokens", "generated_tokens"),
}

need_header = True
if os.path.exists(csv_path):
    try:
        need_header = os.stat(csv_path).st_size == 0
    except OSError:
        need_header = True
os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
with open(csv_path, "a", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=header)
    if need_header:
        writer.writeheader()
    writer.writerow({k: row.get(k, "") for k in header})
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

remote_env="OUT_DIR=$(sh_quote "$OUT_DIR") REMOTE_WORK_ROOT=$(sh_quote "$REMOTE_WORK_ROOT") DS4_DIR=$(sh_quote "$DS4_DIR") MODEL_GGUF=$(sh_quote "$MODEL_GGUF") PROMPT=$(sh_quote "$PROMPT") CTX=$(sh_quote "$CTX") N_TOKENS=$(sh_quote "$N_TOKENS") EXTRA_ARGS=$(sh_quote "$EXTRA_ARGS") ALLOW_FETCH=$(sh_quote "$ALLOW_FETCH") ALLOW_BUILD=$(sh_quote "$ALLOW_BUILD") ALLOW_RUN=$(sh_quote "$ALLOW_RUN")"

{
	echo "# Baseline: antirez/ds4 (Spark / CUDA)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- ds4_on_spark commit: $repo_rev"
	echo "- target: $target"
	echo "- scope: $DS4_SCOPE"
	echo "- model_id: $DS4_MODEL_ID"
	echo
	echo "## Command"
	echo
	echo '```sh'
	echo "ALLOW_RUN=$ALLOW_RUN ALLOW_BUILD=$ALLOW_BUILD ALLOW_FETCH=$ALLOW_FETCH \\"
	echo "DS4_DIR='$DS4_DIR' MODEL_GGUF='$MODEL_GGUF' \\"
	echo "PROMPT='$PROMPT' CTX='$CTX' N_TOKENS='$N_TOKENS' EXTRA_ARGS='$EXTRA_ARGS' \\"
	echo "scripts/run_baseline_antirez_ds4_spark.sh '$target'"
	echo '```'
	echo
} >"$REPORT_MD"

ssh $SSH_OPTS "$target" "$remote_env sh -s" >"$STDOUT_TXT" 2>"$STDERR_TXT" <<'REMOTE' || true
set -eu
mkdir -p "$OUT_DIR"
if [ "$REMOTE_WORK_ROOT" = "" ]; then
	REMOTE_WORK_ROOT="$HOME/ds4_on_spark"
fi
if [ "$DS4_DIR" = "" ]; then
	DS4_DIR="$REMOTE_WORK_ROOT/ds4"
fi

echo "== antirez/ds4 Spark baseline =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo "host=$(hostname 2>/dev/null || echo unknown)"
echo "uname=$(uname -a 2>/dev/null || echo unknown)"
echo "ds4_dir=$DS4_DIR"
echo "model_gguf=$MODEL_GGUF"
echo

if command -v nvidia-smi >/dev/null 2>&1; then
	echo "== nvidia-smi before =="
	nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader 2>/dev/null || true
	echo
fi

if [ ! -d "$DS4_DIR" ]; then
	echo "missing DS4_DIR=$DS4_DIR"
	if [ "$ALLOW_FETCH" = "1" ]; then
		mkdir -p "$REMOTE_WORK_ROOT"
		git clone https://github.com/antirez/ds4.git "$DS4_DIR"
	else
		echo "set ALLOW_FETCH=1 to clone antirez/ds4 on the Spark host"
		exit 2
	fi
fi

echo "== ds4 revision =="
if [ -d "$DS4_DIR/.git" ]; then
	(cd "$DS4_DIR" && git rev-parse HEAD) || true
fi
echo

if [ "$ALLOW_BUILD" = "1" ]; then
	echo "== build (make) =="
	(cd "$DS4_DIR" && make)
	echo
else
	echo "== build skipped =="
	echo "set ALLOW_BUILD=1 to compile ds4 on the Spark host"
	echo
fi

if [ "$ALLOW_RUN" != "1" ]; then
	echo "== run skipped =="
	echo "set ALLOW_RUN=1 and MODEL_GGUF=/remote/path/to/ds4flash.gguf to run"
	exit 0
fi

DS4_BIN="$DS4_DIR/ds4"
if [ ! -x "$DS4_BIN" ]; then
	echo "ds4 binary not found: $DS4_BIN"
	echo "set ALLOW_BUILD=1 to build first"
	exit 3
fi

if [ "$MODEL_GGUF" = "" ]; then
	if [ -r "$DS4_DIR/ds4flash.gguf" ]; then
		MODEL_GGUF="$DS4_DIR/ds4flash.gguf"
	fi
fi
if [ "$MODEL_GGUF" = "" ]; then
	echo "MODEL_GGUF is required (or place ds4flash.gguf under DS4_DIR)"
	echo "do not run upstream model download scripts unless a human approved the large download"
	exit 4
fi
if [ ! -r "$MODEL_GGUF" ]; then
	echo "MODEL_GGUF not readable: $MODEL_GGUF"
	exit 5
fi

echo "== model artifact =="
ls -lh "$MODEL_GGUF" || true
if command -v sha256sum >/dev/null 2>&1; then
	sha256sum "$MODEL_GGUF" || true
fi
echo

python3 - "$DS4_BIN" "$MODEL_GGUF" "$PROMPT" "$N_TOKENS" "$CTX" "$EXTRA_ARGS" <<'PY'
import os
import re
import resource
import shlex
import subprocess
import sys
import time

ds4_bin, model, prompt, n_tokens, ctx, extra_args = sys.argv[1:]
cmd = [ds4_bin, "-m", model, "-p", prompt, "-n", n_tokens, "-c", ctx]
if extra_args.strip():
    cmd.extend(shlex.split(extra_args))

print("== run ==")
print("cmd=" + " ".join(shlex.quote(x) for x in cmd))
print()
sys.stdout.flush()

start = time.monotonic()
first_output_s = None
prefill_tps = None
generation_tps = None
prefill_re = re.compile(r"ds4:\s+prefill:\s+([0-9]+(?:\.[0-9]+)?)\s+t/s,\s+generation:\s+([0-9]+(?:\.[0-9]+)?)\s+t/s")

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
for line in proc.stdout:
    if first_output_s is None and line:
        first_output_s = time.monotonic() - start
    m = prefill_re.search(line)
    if m:
        prefill_tps = float(m.group(1))
        generation_tps = float(m.group(2))
    sys.stdout.write(line)
    sys.stdout.flush()
rc = proc.wait()
end = time.monotonic()
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
max_rss_bytes = int(ru.ru_maxrss) * 1024

summary = [
    f"exit_code={rc}",
    "ttft_first_output_s=NA" if first_output_s is None else f"ttft_first_output_s={first_output_s:.6f}",
    "ttft_s=NA" if first_output_s is None else f"ttft_s={first_output_s:.6f}",
    f"wall_s={end - start:.6f}",
    f"total_wall_s={end - start:.6f}",
    f"max_rss_bytes={max_rss_bytes}",
]
if prefill_tps is not None:
    summary.append(f"prefill_tps={prefill_tps:.6f}")
if generation_tps is not None:
    summary.append(f"generation_tps={generation_tps:.6f}")
    summary.append(f"decode_tps={generation_tps:.6f}")
try:
    summary.append(f"output_tokens={int(n_tokens)}")
except Exception:
    pass

print("\n== baseline summary (approx) ==")
print("\n".join(summary))
sys.exit(rc)
PY

if command -v nvidia-smi >/dev/null 2>&1; then
	echo
	echo "== nvidia-smi after =="
	nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader 2>/dev/null || true
fi
REMOTE

extract_baseline_summary "$STDOUT_TXT" >"$SUMMARY_TXT"
append_model_runs_csv
score_model_runs_csv

{
	echo "## antirez/ds4 Spark result"
	echo
	echo "Summary:"
	echo
	echo '```text'
	cat "$SUMMARY_TXT" 2>/dev/null || true
	echo '```'
	echo
	echo "Logs:"
	echo
	echo "- stdout: $STDOUT_TXT"
	echo "- stderr: $STDERR_TXT"
	echo
	if [ "$MODEL_RUNS_CSV" != "" ]; then
		echo "## Quality/speed scoring"
		echo
		echo "- model_runs_csv: $MODEL_RUNS_CSV"
		echo "- score_md: $OUT_DIR/model_quality_speed_score.md"
		echo "- score_json: $OUT_DIR/model_quality_speed_score.json"
		echo
	fi
} >>"$REPORT_MD"

echo "done: $REPORT_MD"
