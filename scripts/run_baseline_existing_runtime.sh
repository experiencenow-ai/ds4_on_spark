#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline}"
REMOTE_BENCH_ENV="${REMOTE_BENCH_ENV:-}"
REMOTE_LLAMA_ENV="${REMOTE_LLAMA_ENV:-$REMOTE_BENCH_ENV}"
REMOTE_VLLM_ENV="${REMOTE_VLLM_ENV:-$REMOTE_BENCH_ENV}"
REMOTE_GGUF_INSPECT_ENV="${REMOTE_GGUF_INSPECT_ENV:-$REMOTE_LLAMA_ENV}"
REMOTE_MTP_SIDECAR_ENV="${REMOTE_MTP_SIDECAR_ENV:-$REMOTE_BENCH_ENV}"
REMOTE_MTP_SIDECAR_ARGS="${REMOTE_MTP_SIDECAR_ARGS:---json --expect-deepseek-v4-flash}"
RUN_LABEL="${RUN_LABEL:-}"
MODEL_RUNS_CSV="${MODEL_RUNS_CSV:-}"
VLLM_MODEL_ID="${VLLM_MODEL_ID:-}"
VLLM_MODEL="${VLLM_MODEL:-}"
LLAMA_SCOPE="${LLAMA_SCOPE:-llamacpp}"
VLLM_SCOPE="${VLLM_SCOPE:-vllm}"
LLAMA_FATTN_PATCH_PROBE="${LLAMA_FATTN_PATCH_PROBE:-0}"
LLAMA_MULTISLOT_PATCH_PROBE="${LLAMA_MULTISLOT_PATCH_PROBE:-0}"
LLAMA_SERVER_SWEEP="${LLAMA_SERVER_SWEEP:-0}"
LLAMA_SERVER_THROUGHPUT_SWEEP="${LLAMA_SERVER_THROUGHPUT_SWEEP:-0}"
FETCH_LLAMA_OUT_DIR="${FETCH_LLAMA_OUT_DIR:-0}"
SKIP_GGUF_INSPECT="${SKIP_GGUF_INSPECT:-0}"
SKIP_LLAMA="${SKIP_LLAMA:-0}"
SKIP_MTP_SIDECAR="${SKIP_MTP_SIDECAR:-0}"
SKIP_VLLM="${SKIP_VLLM:-0}"
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
RUN_IDS_TSV="$OUT_DIR/model_run_ids.tsv"

echo "writing report to: $OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
git_dir=""
git_worktree="$repo_root"
if [ "${DS4_GIT_WORK_TREE:-}" != "" ]; then
    git_worktree="$DS4_GIT_WORK_TREE"
fi
if [ "${DS4_GIT_DIR:-}" != "" ] && [ -r "${DS4_GIT_DIR:-}/HEAD" ]; then
    git_dir="$DS4_GIT_DIR"
fi
if [ "$git_dir" = "" ] && [ -d "$repo_root/.codex_git" ] && [ -r "$repo_root/.codex_git/HEAD" ]; then
    git_dir="$repo_root/.codex_git"
fi
if [ "$git_dir" = "" ] && [ -d "$repo_root/git-local/baseline-runtime.git" ] && [ -r "$repo_root/git-local/baseline-runtime.git/HEAD" ]; then
    git_dir="$repo_root/git-local/baseline-runtime.git"
fi
if [ "$git_dir" = "" ] && [ -e "$repo_root/.git2/.git/HEAD" ]; then
    git_dir="$repo_root/.git2/.git"
fi
if [ "$git_dir" != "" ]; then
    repo_rev="$(GIT_DIR="$git_dir" GIT_WORK_TREE="$git_worktree" git rev-parse HEAD 2>/dev/null || echo unknown)"
elif [ -e "$repo_root/.git" ]; then
    repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/baseline_existing_runtime.md"

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

fetch_remote_dir_tar()
{
    remote_dir="${1:-}"
    local_tgz="${2:-}"
    if [ "$remote_dir" = "" ] || [ "$local_tgz" = "" ]; then
        return 0
    fi
    remote_name="${remote_dir##*/}"
    ssh $SSH_OPTS "$target" "if [ -d $remote_dir ]; then tar -C /tmp -czf - $remote_name; fi" >"$local_tgz" 2>"$local_tgz.stderr" || true
}

sh_quote()
{
    v="${1:-}"
    printf "'%s'" "$(printf %s "$v" | sed "s/'/'\\\\\\\\''/g")"
}

remote_env_prefix()
{
    out=""
    if [ "${LLAMA_DIR:-}" != "" ]; then
        out="$out LLAMA_DIR=$(sh_quote "$LLAMA_DIR")"
    fi
    if [ "${LLAMA_SERVER:-}" != "" ]; then
        out="$out LLAMA_SERVER=$(sh_quote "$LLAMA_SERVER")"
    fi
    if [ "${MODEL_GGUF:-}" != "" ]; then
        out="$out MODEL_GGUF=$(sh_quote "$MODEL_GGUF")"
    fi
    printf "%s" "$out"
}

remote_server_sweep_env()
{
    base="$REMOTE_LLAMA_ENV $(remote_env_prefix)"
    out="$base"
    if [ "${LLAMA_SERVER_SWEEP_PORT:-}" != "" ]; then out="$out PORT=$(sh_quote "$LLAMA_SERVER_SWEEP_PORT")"; fi
    if [ "${LLAMA_SERVER_SWEEP_CTX:-}" != "" ]; then out="$out CTX=$(sh_quote "$LLAMA_SERVER_SWEEP_CTX")"; fi
    if [ "${LLAMA_SERVER_SWEEP_PROMPT_WORDS:-}" != "" ]; then out="$out PROMPT_WORDS=$(sh_quote "$LLAMA_SERVER_SWEEP_PROMPT_WORDS")"; fi
    if [ "${LLAMA_SERVER_SWEEP_N_PREDICT:-}" != "" ]; then out="$out N_PREDICT=$(sh_quote "$LLAMA_SERVER_SWEEP_N_PREDICT")"; fi
    if [ "${LLAMA_SERVER_SWEEP_REPEATS:-}" != "" ]; then out="$out REPEATS=$(sh_quote "$LLAMA_SERVER_SWEEP_REPEATS")"; fi
    if [ "${LLAMA_SERVER_SWEEP_START_SERVER:-}" != "" ]; then out="$out START_SERVER=$(sh_quote "$LLAMA_SERVER_SWEEP_START_SERVER")"; fi
    if [ "${LLAMA_SERVER_SWEEP_KEEP_SERVER:-}" != "" ]; then out="$out KEEP_SERVER=$(sh_quote "$LLAMA_SERVER_SWEEP_KEEP_SERVER")"; fi
    if [ "${LLAMA_SERVER_SWEEP_CACHE_PROMPT:-}" != "" ]; then out="$out CACHE_PROMPT=$(sh_quote "$LLAMA_SERVER_SWEEP_CACHE_PROMPT")"; fi
    if [ "${LLAMA_SERVER_SWEEP_SCRAPE_METRICS:-}" != "" ]; then out="$out SCRAPE_METRICS=$(sh_quote "$LLAMA_SERVER_SWEEP_SCRAPE_METRICS")"; fi
    if [ "${LLAMA_SERVER_SWEEP_METRICS_TIMEOUT_S:-}" != "" ]; then out="$out METRICS_TIMEOUT_S=$(sh_quote "$LLAMA_SERVER_SWEEP_METRICS_TIMEOUT_S")"; fi
    if [ "${LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S:-}" != "" ]; then out="$out WAIT_TIMEOUT_S=$(sh_quote "$LLAMA_SERVER_SWEEP_WAIT_TIMEOUT_S")"; fi
    if [ "${LLAMA_SERVER_SWEEP_POLL_S:-}" != "" ]; then out="$out POLL_S=$(sh_quote "$LLAMA_SERVER_SWEEP_POLL_S")"; fi
    if [ "${LLAMA_SERVER_SWEEP_SERVER_ARGS:-}" != "" ]; then out="$out SERVER_ARGS=$(sh_quote "$LLAMA_SERVER_SWEEP_SERVER_ARGS")"; fi
    printf "%s" "$out"
}

remote_throughput_sweep_env()
{
    base="$REMOTE_LLAMA_ENV $(remote_env_prefix)"
    out="$base"
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_PORT:-}" != "" ]; then out="$out PORT=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_PORT")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_CTX:-}" != "" ]; then out="$out CTX=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_CTX")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_PROMPT_WORDS:-}" != "" ]; then out="$out PROMPT_WORDS=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_PROMPT_WORDS")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_N_PREDICT:-}" != "" ]; then out="$out N_PREDICT=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_N_PREDICT")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_CONCURRENCY:-}" != "" ]; then out="$out CONCURRENCY=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_CONCURRENCY")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_PARALLEL_VALUES:-}" != "" ]; then out="$out PARALLEL_VALUES=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_PARALLEL_VALUES")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_BATCH_VALUES:-}" != "" ]; then out="$out BATCH_VALUES=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_BATCH_VALUES")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_UBATCH_VALUES:-}" != "" ]; then out="$out UBATCH_VALUES=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_UBATCH_VALUES")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_PARALLEL_FLAG:-}" != "" ]; then out="$out PARALLEL_FLAG=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_PARALLEL_FLAG")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_BATCH_FLAG:-}" != "" ]; then out="$out BATCH_FLAG=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_BATCH_FLAG")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_UBATCH_FLAG:-}" != "" ]; then out="$out UBATCH_FLAG=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_UBATCH_FLAG")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_RESTART_PER_COMBO:-}" != "" ]; then out="$out RESTART_PER_COMBO=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_RESTART_PER_COMBO")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_RESTART_SLEEP_S:-}" != "" ]; then out="$out RESTART_SLEEP_S=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_RESTART_SLEEP_S")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_START_SERVER:-}" != "" ]; then out="$out START_SERVER=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_START_SERVER")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_KEEP_SERVER:-}" != "" ]; then out="$out KEEP_SERVER=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_KEEP_SERVER")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_CACHE_PROMPT:-}" != "" ]; then out="$out CACHE_PROMPT=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_CACHE_PROMPT")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_SCRAPE_METRICS:-}" != "" ]; then out="$out SCRAPE_METRICS=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_SCRAPE_METRICS")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_METRICS_TIMEOUT_S:-}" != "" ]; then out="$out METRICS_TIMEOUT_S=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_METRICS_TIMEOUT_S")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_WAIT_TIMEOUT_S:-}" != "" ]; then out="$out WAIT_TIMEOUT_S=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_WAIT_TIMEOUT_S")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_POLL_S:-}" != "" ]; then out="$out POLL_S=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_POLL_S")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_REQUEST_TIMEOUT_S:-}" != "" ]; then out="$out REQUEST_TIMEOUT_S=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_REQUEST_TIMEOUT_S")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_SERVER_ARGS:-}" != "" ]; then out="$out SERVER_ARGS=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_SERVER_ARGS")"; fi
    if [ "${LLAMA_SERVER_THROUGHPUT_SWEEP_PRESET:-}" != "" ]; then out="$out PRESET=$(sh_quote "$LLAMA_SERVER_THROUGHPUT_SWEEP_PRESET")"; fi
    printf "%s" "$out"
}

append_model_runs_csv()
{
    scope="$1"
    model="$2"
    summary_path="$3"
    if [ "$MODEL_RUNS_CSV" = "" ] || [ "$summary_path" = "" ] || [ ! -r "$summary_path" ]; then
        return 0
    fi
    run_id="$ts-$scope"
    if [ "$RUN_LABEL" != "" ]; then
        run_id="$ts-$RUN_LABEL-$scope"
    fi
    printf '%s\t%s\t%s\n' "$run_id" "$scope" "$model" >>"$RUN_IDS_TSV" 2>/dev/null || true
    python3 - "$MODEL_RUNS_CSV" "$model" "$run_id" "$scope" "$PUBLIC_QUALITY_PRIOR" "$PUBLIC_QUALITY_BASIS" "$PUBLIC_QUALITY_SOURCE" "$PASSED_TASKS" "$TOTAL_TASKS" "$LOCAL_QUALITY_SCORE" "$QUALITY_SCORE" "$summary_path" 2>/dev/null <<'PY' || true
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
passed_tasks_arg = sys.argv[8].strip()
total_tasks_arg = sys.argv[9].strip()
local_quality_score_arg = sys.argv[10].strip()
quality_score_arg = sys.argv[11].strip()
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

def _prefer(arg: str, *names: str) -> str:
    v = (arg or "").strip()
    if v:
        return v
    return _get(*names)

passed_tasks = _prefer(passed_tasks_arg, "passed_tasks")
total_tasks = _prefer(total_tasks_arg, "total_tasks")
local_quality_score = _prefer(local_quality_score_arg, "local_quality_score")
quality_score = _prefer(quality_score_arg, "quality_score")

if not local_quality_score and passed_tasks and total_tasks:
    try:
        p = float(passed_tasks)
        t = float(total_tasks)
        if t > 0:
            local_quality_score = f"{(100.0 * p / t):.6f}"
    except Exception:
        pass

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
    "output_tokens": _get("output_tokens", "generated_tokens", "token_trace_events", "n_tokens"),
    "speculative_method": _get("speculative_method"),
    "speculative_draft_model": _get("speculative_draft_model"),
    "speculative_num_speculative_tokens": _get("speculative_num_speculative_tokens"),
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
    "speculative_method",
    "speculative_draft_model",
    "speculative_num_speculative_tokens",
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

emit_scored_run_summaries()
{
    if [ "$MODEL_RUNS_CSV" = "" ] || [ ! -r "$OUT_DIR/model_quality_speed_score.json" ] || [ ! -r "$RUN_IDS_TSV" ]; then
        return 0
    fi
    python3 - "$OUT_DIR/model_quality_speed_score.json" "$RUN_IDS_TSV" >"$OUT_DIR/model_quality_speed_scored_summary.txt" 2>/dev/null <<'PY' || true
import json
import sys

score_json_path = sys.argv[1]
run_ids_path = sys.argv[2]

try:
    rows = json.load(open(score_json_path, "r", encoding="utf-8"))
except OSError:
    rows = []
except json.JSONDecodeError:
    rows = []

by_run = {}
for r in rows:
    rid = str(r.get("run_id", "") or "")
    if rid:
        by_run[rid] = r

def _fmt(v):
    if v is None:
        return ""
    try:
        fv = float(v)
    except Exception:
        return str(v)
    return f"{fv:.6f}"

for raw_line in open(run_ids_path, "r", encoding="utf-8").read().splitlines():
    parts = raw_line.split("\t")
    run_id = parts[0].strip() if len(parts) > 0 else ""
    scope = parts[1].strip() if len(parts) > 1 else ""
    model = parts[2].strip() if len(parts) > 2 else ""
    if not run_id:
        continue
    r = by_run.get(run_id, {})
    print(f"== scored summary ({scope}) ==")
    if model:
        print(f"model={model}")
    print(f"run_id={run_id}")
    for k in [
        "public_quality_prior",
        "public_quality_basis",
        "public_quality_source",
        "passed_tasks",
        "total_tasks",
        "local_quality_score",
        "quality_score",
        "decode_tps",
        "total_wall_s",
        "output_tokens",
        "quality_adjusted_decode_tps",
        "correct_task_rate",
        "correct_tasks_per_s",
        "tokens_per_success",
        "dominated_by",
    ]:
        v = r.get(k, "")
        if v is None:
            v = ""
        if isinstance(v, (int, float)):
            v = _fmt(v)
        else:
            v = str(v)
        print(f"{k}={v}")
    print("")
PY
}

{
    echo "# Existing Runtime Baseline (Spark)"
    echo
    echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "- ds4_on_spark commit: $repo_rev"
    echo "- target: $target"
    if [ "$RUN_LABEL" != "" ]; then
        echo "- run_label: $RUN_LABEL"
    fi
    if [ "$MODEL_RUNS_CSV" != "" ]; then
        echo "- model_runs_csv: $MODEL_RUNS_CSV"
        echo "- llama_scope: ${LLAMA_SCOPE:-llamacpp}"
        echo "- vllm_scope: ${VLLM_SCOPE:-vllm}"
        echo "- skip_gguf_inspect: ${SKIP_GGUF_INSPECT:-0}"
        echo "- skip_llama: ${SKIP_LLAMA:-0}"
        echo "- skip_mtp_sidecar: ${SKIP_MTP_SIDECAR:-0}"
        echo "- skip_vllm: ${SKIP_VLLM:-0}"
    fi
    echo
    if [ "$MODEL_RUNS_CSV" != "" ] || [ "$PUBLIC_QUALITY_PRIOR" != "" ] || [ "$PUBLIC_QUALITY_BASIS" != "" ] || [ "$PUBLIC_QUALITY_SOURCE" != "" ] || [ "$PASSED_TASKS" != "" ] || [ "$TOTAL_TASKS" != "" ] || [ "$LOCAL_QUALITY_SCORE" != "" ] || [ "$QUALITY_SCORE" != "" ]; then
        echo "## Quality Metadata (Local)"
        echo
        echo "These fields are recorded into \`MODEL_RUNS_CSV\` when enabled, and should be copied into committed baseline reports when doing multi-model comparisons."
        echo
        echo "- public_quality_prior: ${PUBLIC_QUALITY_PRIOR:-NA}"
        echo "- public_quality_basis: ${PUBLIC_QUALITY_BASIS:-NA}"
        echo "- public_quality_source: ${PUBLIC_QUALITY_SOURCE:-NA}"
        echo "- passed_tasks: ${PASSED_TASKS:-NA}"
        echo "- total_tasks: ${TOTAL_TASKS:-NA}"
        echo "- local_quality_score: ${LOCAL_QUALITY_SCORE:-NA}"
        echo "- quality_score: ${QUALITY_SCORE:-NA}"
        echo
    fi
    echo "## Safety Gates"
    echo
    echo "This run script only executes what the remote benchmark scripts allow."
    echo "Set gates on the Spark side via env vars:"
    echo
    echo "- ALLOW_FETCH=1"
    echo "- ALLOW_BUILD=1"
    echo "- ALLOW_MODEL_INSPECT=1"
    echo "- ALLOW_RUN=1"
    echo "- REMOTE_BENCH_ENV='...'"
    echo "- REMOTE_LLAMA_ENV='...'"
    echo "- REMOTE_VLLM_ENV='...'"
    echo "- REMOTE_GGUF_INSPECT_ENV='...'"
    echo
    echo "Remote llama env:"
    echo
    echo "Do not put secrets in REMOTE_* env values; this report records them."
    echo
    echo '```'
    echo "$REMOTE_LLAMA_ENV"
    echo '```'
    echo
    echo "Remote vLLM env:"
    echo
    echo '```'
    echo "$REMOTE_VLLM_ENV"
    echo '```'
    echo
    echo "Remote GGUF inspector env:"
    echo
    echo "This is used for a metadata-only GGUF header + tensor-key inspection pass."
    echo "Do not put secrets in REMOTE_* env values; this report records them."
    echo
    echo '```'
    echo "$REMOTE_GGUF_INSPECT_ENV"
    echo '```'
    echo
    echo "Remote MTP sidecar env:"
    echo
    echo "Used when running the sidecar contract probe (optional; set MTP_SIDECAR_GGUF on Spark)."
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

if [ "$SKIP_GGUF_INSPECT" != "1" ]; then
echo "== running GGUF contract inspector on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_inspect_quantized_artifact.py && chmod +x /tmp/model_contract_inspect_quantized_artifact.py" <"$repo_root/scripts/model_contract_inspect_quantized_artifact.py" \
    >/dev/null 2>"$OUT_DIR/remote_gguf_inspect_copy_stderr.txt" || true
ssh $SSH_OPTS "$target" "cat > /tmp/deepseek_v4_flash_contract_summary.json" <"$repo_root/fixtures/model_contract/deepseek_v4_flash/contract_summary.json" \
    >/dev/null 2>"$OUT_DIR/remote_gguf_inspect_contract_copy_stderr.txt" || true

ssh $SSH_OPTS "$target" "$REMOTE_GGUF_INSPECT_ENV sh -lc '
set -eu
if [ \"\${ALLOW_MODEL_INSPECT:-0}\" != \"1\" ]; then
  echo \"inspect skipped: set ALLOW_MODEL_INSPECT=1 on Spark to enable\"
  exit 0
fi
if [ \"\${MODEL_GGUF:-}\" = \"\" ]; then
  echo \"inspect skipped: set MODEL_GGUF=/abs/path/to/model.gguf\"
  exit 0
fi
if [ ! -r \"\${MODEL_GGUF}\" ]; then
  echo \"inspect skipped: MODEL_GGUF not readable: \${MODEL_GGUF}\"
  exit 0
fi
python3 /tmp/model_contract_inspect_quantized_artifact.py --path \"\${MODEL_GGUF}\" --contract-summary /tmp/deepseek_v4_flash_contract_summary.json --json
' " >"$OUT_DIR/remote_gguf_inspect_stdout.txt" 2>"$OUT_DIR/remote_gguf_inspect_stderr.txt" || true

{
    echo "## GGUF contract inspector (Spark)"
    echo
    echo 'This is a metadata-only inspection pass for the `MODEL_GGUF` file.'
    echo "It does not load the full model into GPU memory."
    echo
    echo "Summary (best-effort):"
    echo
    echo '```'
    sed -n '1,80p' "$OUT_DIR/remote_gguf_inspect_stdout.txt" || true
    echo '```'
    echo
    echo "Full logs:"
    echo
    echo "- stdout: $OUT_DIR/remote_gguf_inspect_stdout.txt"
    echo "- stderr: $OUT_DIR/remote_gguf_inspect_stderr.txt"
    echo
} >>"$REPORT_MD"
fi

REMOTE_PROBE_ENV="$(remote_env_prefix)"

if [ "$SKIP_LLAMA" != "1" ] && [ "$LLAMA_FATTN_PATCH_PROBE" = "1" ]; then
    echo "== running llama.cpp fattn patch source probe on spark (read-only) =="
    ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_fattn_patch_probe.py && chmod +x /tmp/benchmark_llamacpp_fattn_patch_probe.py && $REMOTE_LLAMA_ENV $REMOTE_PROBE_ENV python3 /tmp/benchmark_llamacpp_fattn_patch_probe.py" <"$repo_root/scripts/benchmark_llamacpp_fattn_patch_probe.py" \
        >"$OUT_DIR/remote_fattn_patch_probe_stdout.txt" 2>"$OUT_DIR/remote_fattn_patch_probe_stderr.txt" || true
    {
        echo "## llama.cpp fattn patch probe (Spark)"
        echo
        echo "Summary (best-effort):"
        echo
        echo '```'
        sed -n "1,80p" "$OUT_DIR/remote_fattn_patch_probe_stdout.txt" || true
        echo '```'
        echo
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/remote_fattn_patch_probe_stdout.txt"
        echo "- stderr: $OUT_DIR/remote_fattn_patch_probe_stderr.txt"
        echo
    } >>"$REPORT_MD"
fi

if [ "$SKIP_LLAMA" != "1" ] && [ "$LLAMA_MULTISLOT_PATCH_PROBE" = "1" ]; then
    echo "== running llama.cpp multislot patch source probe on spark (read-only) =="
    ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_multislot_patch_probe.py && chmod +x /tmp/benchmark_llamacpp_multislot_patch_probe.py && $REMOTE_LLAMA_ENV $REMOTE_PROBE_ENV python3 /tmp/benchmark_llamacpp_multislot_patch_probe.py" <"$repo_root/scripts/benchmark_llamacpp_multislot_patch_probe.py" \
        >"$OUT_DIR/remote_multislot_patch_probe_stdout.txt" 2>"$OUT_DIR/remote_multislot_patch_probe_stderr.txt" || true
    {
        echo "## llama.cpp multislot patch probe (Spark)"
        echo
        echo "Summary (best-effort):"
        echo
        echo '```'
        sed -n "1,100p" "$OUT_DIR/remote_multislot_patch_probe_stdout.txt" || true
        echo '```'
        echo
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/remote_multislot_patch_probe_stdout.txt"
        echo "- stderr: $OUT_DIR/remote_multislot_patch_probe_stderr.txt"
        echo
    } >>"$REPORT_MD"
fi

if [ "$SKIP_LLAMA" = "1" ]; then
    echo "== skipping llama.cpp probe/bench =="
else
echo "== running llama.cpp benchmark script on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_spark.sh && chmod +x /tmp/benchmark_llamacpp_spark.sh && $REMOTE_LLAMA_ENV $REMOTE_PROBE_ENV /tmp/benchmark_llamacpp_spark.sh" <"$repo_root/scripts/benchmark_llamacpp_spark.sh" \
    >"$OUT_DIR/remote_llamacpp_stdout.txt" 2>"$OUT_DIR/remote_llamacpp_stderr.txt" || true

append_model_runs_csv "${LLAMA_SCOPE:-llamacpp}" "${MODEL_SOURCE:-llamacpp}" "$OUT_DIR/remote_llamacpp_stdout.txt"

LLAMACPP_REMOTE_OUT_DIR=""
if [ -r "$OUT_DIR/remote_llamacpp_stdout.txt" ]; then
    LLAMACPP_REMOTE_OUT_DIR="$(awk -F= '$1 == "out_dir" {print $2; exit}' "$OUT_DIR/remote_llamacpp_stdout.txt" 2>/dev/null || true)"
fi

{
    echo "## llama.cpp (Spark)"
    echo
    echo "Summary (best-effort):"
    echo
    echo '```'
    extract_baseline_summary "$OUT_DIR/remote_llamacpp_stdout.txt"
    echo '```'
    echo
    echo "Full logs:"
    echo
    echo "- stdout: $OUT_DIR/remote_llamacpp_stdout.txt"
    echo "- stderr: $OUT_DIR/remote_llamacpp_stderr.txt"
    echo
    echo "Stdout:"
    echo
    echo '```'
    sed -n '1,200p' "$OUT_DIR/remote_llamacpp_stdout.txt" || true
    echo '```'
    echo
    echo "Stderr:"
    echo
    echo '```'
    sed -n '1,200p' "$OUT_DIR/remote_llamacpp_stderr.txt" || true
    echo '```'
    echo
} >>"$REPORT_MD"
fi

if [ "$SKIP_LLAMA" != "1" ] && [ "$FETCH_LLAMA_OUT_DIR" = "1" ] && [ "${LLAMACPP_REMOTE_OUT_DIR:-}" != "" ]; then
    case "$LLAMACPP_REMOTE_OUT_DIR" in
        /tmp/*)
            echo "== fetching llama.cpp out_dir tarball from spark (opt-in) =="
            fetch_remote_dir_tar "$LLAMACPP_REMOTE_OUT_DIR" "$OUT_DIR/remote_llamacpp_out_dir.tgz"
            if [ -s "$OUT_DIR/remote_llamacpp_out_dir.tgz" ]; then
                mkdir -p "$OUT_DIR/llamacpp_out_dir"
                tar -xzf "$OUT_DIR/remote_llamacpp_out_dir.tgz" -C "$OUT_DIR/llamacpp_out_dir" >/dev/null 2>&1 || true
            fi
            {
                echo "## llama.cpp out_dir artifacts (Spark)"
                echo
                echo "This is an opt-in tarball fetch of the remote llama.cpp runner output directory."
                echo "It is useful for preserving \`fattn_cli_probe.json\` and the raw runner logs alongside the baseline report."
                echo
                echo "Artifacts:"
                echo
                echo "- remote_out_dir: $LLAMACPP_REMOTE_OUT_DIR"
                echo "- tarball: $OUT_DIR/remote_llamacpp_out_dir.tgz"
                echo "- unpacked_dir: $OUT_DIR/llamacpp_out_dir"
                if [ -r "$OUT_DIR/llamacpp_out_dir/fattn_cli_probe.json" ]; then
                    echo "- fattn_cli_probe: $OUT_DIR/llamacpp_out_dir/fattn_cli_probe.json"
                fi
                echo
            } >>"$REPORT_MD"
            ;;
        *)
            echo "note: llama.cpp out_dir not under /tmp; skipping fetch: $LLAMACPP_REMOTE_OUT_DIR" >&2
            ;;
    esac
fi

if [ "$SKIP_LLAMA" != "1" ] && [ "$LLAMA_SERVER_SWEEP" = "1" ]; then
    echo "== running llama-server prompt sweep on spark (may be gated) =="
    remote_dir="/tmp/ds4_llama_server_sweep_$ts"
    ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_server_sweep.py && chmod +x /tmp/benchmark_llamacpp_server_sweep.py && $(remote_server_sweep_env) OUT_DIR=$remote_dir python3 /tmp/benchmark_llamacpp_server_sweep.py" <"$repo_root/scripts/benchmark_llamacpp_server_sweep.py" \
        >"$OUT_DIR/remote_llama_server_sweep_stdout.txt" 2>"$OUT_DIR/remote_llama_server_sweep_stderr.txt" || true
    fetch_remote_dir_tar "$remote_dir" "$OUT_DIR/remote_llama_server_sweep.tgz"
    if [ -s "$OUT_DIR/remote_llama_server_sweep.tgz" ]; then
        mkdir -p "$OUT_DIR/llama_server_sweep"
        tar -xzf "$OUT_DIR/remote_llama_server_sweep.tgz" -C "$OUT_DIR/llama_server_sweep" >/dev/null 2>&1 || true
    fi
    {
        echo "## llama-server prompt sweep (Spark)"
        echo
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/remote_llama_server_sweep_stdout.txt"
        echo "- stderr: $OUT_DIR/remote_llama_server_sweep_stderr.txt"
        echo "- tarball: $OUT_DIR/remote_llama_server_sweep.tgz"
        echo
} >>"$REPORT_MD"
fi

if [ "$SKIP_LLAMA" != "1" ] && [ "$LLAMA_SERVER_THROUGHPUT_SWEEP" = "1" ]; then
    echo "== running llama-server throughput sweep on spark (may be gated) =="
    remote_dir="/tmp/ds4_llama_server_throughput_sweep_$ts"
    ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_llamacpp_server_throughput_sweep.py && chmod +x /tmp/benchmark_llamacpp_server_throughput_sweep.py && $(remote_throughput_sweep_env) OUT_DIR=$remote_dir python3 /tmp/benchmark_llamacpp_server_throughput_sweep.py" <"$repo_root/scripts/benchmark_llamacpp_server_throughput_sweep.py" \
        >"$OUT_DIR/remote_llama_server_throughput_sweep_stdout.txt" 2>"$OUT_DIR/remote_llama_server_throughput_sweep_stderr.txt" || true
    fetch_remote_dir_tar "$remote_dir" "$OUT_DIR/remote_llama_server_throughput_sweep.tgz"
    if [ -s "$OUT_DIR/remote_llama_server_throughput_sweep.tgz" ]; then
        mkdir -p "$OUT_DIR/llama_server_throughput_sweep"
        tar -xzf "$OUT_DIR/remote_llama_server_throughput_sweep.tgz" -C "$OUT_DIR/llama_server_throughput_sweep" >/dev/null 2>&1 || true
    fi
    best_decode_json="$OUT_DIR/llama_server_throughput_sweep/throughput_best_decode.json"
    best_decode_summary="$OUT_DIR/llama_server_throughput_best_decode_summary.txt"
    if [ -r "$best_decode_json" ]; then
        python3 - "$best_decode_json" >"$best_decode_summary" 2>/dev/null <<'PY' || true
import json
import sys

path = sys.argv[1]
try:
    data = json.load(open(path, "r", encoding="utf-8"))
except OSError:
    data = {}
except json.JSONDecodeError:
    data = {}

def _v(k, default=""):
    v = data.get(k, default)
    if v is None:
        return ""
    return str(v)

print("decode_tps=" + _v("agg_generated_tok_s"))
print("prefill_tps=" + _v("agg_prompt_tok_s"))
print("wall_s=" + _v("wave_wall_s"))
print("output_tokens=" + _v("agg_generated_tokens"))
for k in [
    "parallel",
    "batch",
    "ubatch",
    "prompt_words",
    "concurrency",
    "repeats",
    "ok",
    "errors",
    "fattn_disabled",
    "fattn_backend0_only",
    "multislot_sched_reserve_fail",
]:
    if k in data:
        print(f"llama_server_{k}=" + _v(k))
PY
        append_model_runs_csv "${LLAMA_SERVER_THROUGHPUT_SCOPE:-llama_server_throughput}" "${LLAMA_SERVER_MODEL_ID:-${MODEL_SOURCE:-llama-server}}" "$best_decode_summary"
    fi
    {
        echo "## llama-server throughput sweep (Spark)"
        echo
        if [ -r "$best_decode_summary" ]; then
            echo "Best decode row (best-effort):"
            echo
            echo '```'
            cat "$best_decode_summary" 2>/dev/null || true
            echo '```'
            echo
        fi
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/remote_llama_server_throughput_sweep_stdout.txt"
        echo "- stderr: $OUT_DIR/remote_llama_server_throughput_sweep_stderr.txt"
        echo "- tarball: $OUT_DIR/remote_llama_server_throughput_sweep.tgz"
        if [ -r "$best_decode_summary" ]; then
            echo "- best_decode_summary: $best_decode_summary"
        fi
        echo
} >>"$REPORT_MD"
fi

if [ "$SKIP_MTP_SIDECAR" = "1" ]; then
    echo "== skipping MTP sidecar contract probe =="
else
echo "== running MTP sidecar contract probe on spark (may be gated) =="
ssh $SSH_OPTS "$target" "cat > /tmp/model_contract_probe_mtp_sidecar.py && chmod +x /tmp/model_contract_probe_mtp_sidecar.py && $REMOTE_MTP_SIDECAR_ENV sh -lc '
set -eu
if [ \"\${ALLOW_RUN:-0}\" != \"1\" ]; then
  echo \"run skipped: set ALLOW_RUN=1 on Spark to enable\"
  exit 0
fi
if [ \"\${MTP_SIDECAR_GGUF:-}\" = \"\" ]; then
  echo \"run skipped: set MTP_SIDECAR_GGUF=/abs/path/to/DeepSeek-V4-Flash-MTP-*.gguf\"
  exit 0
fi
if [ ! -r \"\${MTP_SIDECAR_GGUF}\" ]; then
  echo \"run skipped: MTP_SIDECAR_GGUF not readable: \${MTP_SIDECAR_GGUF}\"
  exit 0
fi
python3 /tmp/model_contract_probe_mtp_sidecar.py --path \"\${MTP_SIDECAR_GGUF}\" '"$REMOTE_MTP_SIDECAR_ARGS"'
' " <"$repo_root/scripts/model_contract_probe_mtp_sidecar.py" \
    >"$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" 2>"$OUT_DIR/remote_mtp_sidecar_probe_stderr.txt" || true

{
    echo "## MTP sidecar contract probe (Spark)"
    echo
    echo 'This is a metadata-only sanity check for DS4-tuned MTP sidecars (e.g. `general.architecture=deepseek4_mtp_support` + 32 `mtp.0.*` tensors).'
    echo "It does not require loading the trunk GGUF or reading tensor payloads into RAM."
    echo
    echo "Summary (best-effort):"
    echo
    echo '```'
    sed -n '1,120p' "$OUT_DIR/remote_mtp_sidecar_probe_stdout.txt" || true
    echo '```'
    echo
    echo "Full logs:"
    echo
    echo "- stdout: $OUT_DIR/remote_mtp_sidecar_probe_stdout.txt"
    echo "- stderr: $OUT_DIR/remote_mtp_sidecar_probe_stderr.txt"
    echo
} >>"$REPORT_MD"
fi

if [ "$SKIP_VLLM" = "1" ]; then
    echo "== skipping vLLM probe =="
else
    echo "== running vLLM probe script on spark =="
    ssh $SSH_OPTS "$target" "cat > /tmp/benchmark_vllm_spark.sh && chmod +x /tmp/benchmark_vllm_spark.sh && $REMOTE_VLLM_ENV /tmp/benchmark_vllm_spark.sh" <"$repo_root/scripts/benchmark_vllm_spark.sh" \
        >"$OUT_DIR/remote_vllm_stdout.txt" 2>"$OUT_DIR/remote_vllm_stderr.txt" || true

    vllm_model_label="$VLLM_MODEL"
    if [ "$VLLM_MODEL_ID" != "" ]; then
        vllm_model_label="$VLLM_MODEL_ID"
    fi
    append_model_runs_csv "${VLLM_SCOPE:-vllm}" "${vllm_model_label:-vllm}" "$OUT_DIR/remote_vllm_stdout.txt"

    {
        echo "## vLLM (Spark)"
        echo
        echo "Summary (best-effort):"
        echo
        echo '```'
        extract_baseline_summary "$OUT_DIR/remote_vllm_stdout.txt"
        echo '```'
        echo
        echo "Full logs:"
        echo
        echo "- stdout: $OUT_DIR/remote_vllm_stdout.txt"
        echo "- stderr: $OUT_DIR/remote_vllm_stderr.txt"
        echo
        echo "Stdout:"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/remote_vllm_stdout.txt" || true
        echo '```'
        echo
        echo "Stderr:"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/remote_vllm_stderr.txt" || true
        echo '```'
        echo
    } >>"$REPORT_MD"
fi

score_model_runs_csv
emit_scored_run_summaries

if [ "$MODEL_RUNS_CSV" != "" ]; then
{
    echo "## Quality/speed scoring (local)"
    echo
    echo "- model_runs_csv: $MODEL_RUNS_CSV"
    echo "- score_md: $OUT_DIR/model_quality_speed_score.md"
    echo "- score_json: $OUT_DIR/model_quality_speed_score.json"
    if [ -r "$OUT_DIR/model_quality_speed_scored_summary.txt" ]; then
        echo "- scored_summary: $OUT_DIR/model_quality_speed_scored_summary.txt"
    fi
    echo
    if [ -r "$OUT_DIR/model_quality_speed_score.md" ]; then
        echo "Summary (best-effort):"
        echo
        echo '```'
        sed -n '1,20p' "$OUT_DIR/model_quality_speed_score.md" || true
        echo '```'
        echo
    fi
    if [ -r "$OUT_DIR/model_quality_speed_scored_summary.txt" ]; then
        echo "Scored summary (best-effort):"
        echo
        echo '```'
        sed -n '1,200p' "$OUT_DIR/model_quality_speed_scored_summary.txt" || true
        echo '```'
        echo
    fi
} >>"$REPORT_MD"
fi

echo "done: $REPORT_MD"
