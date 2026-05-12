#!/usr/bin/env sh
set -eu

# Local bundle wrapper for running a vLLM Ling/Qwen/DFlash matrix on Spark and
# collecting all per-row reports + a single scored summary in one output dir.
#
# This does not install runtimes or download weights. Spark-side gates still apply.

target="${1:-spark0@aitopatom-9ab9.local}"
matrix_tsv="${2:-}"

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
if [ "$git_dir" = "" ] && [ -d "$repo_root/.codex_git_worktree" ] && [ -r "$repo_root/.codex_git_worktree/HEAD" ]; then
    git_dir="$repo_root/.codex_git_worktree"
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

if [ "$matrix_tsv" = "" ]; then
    matrix_tsv="$repo_root/fixtures/baseline/vllm_matrix_template.tsv"
fi
if [ ! -r "$matrix_tsv" ]; then
    echo "matrix TSV not found/readable: $matrix_tsv" >&2
    echo "usage: scripts/run_baseline_vllm_matrix_bundle.sh <spark-ssh-target> <matrix.tsv>" >&2
    exit 2
fi

BUNDLE_LABEL="${BUNDLE_LABEL:-vllm-matrix}"
OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_baseline_matrix}"

ALLOW_RUN="${ALLOW_RUN:-0}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
MAX_TOKENS="${MAX_TOKENS:-64}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
DFLASH_NUM_SPEC_TOKENS="${DFLASH_NUM_SPEC_TOKENS:-15}"
SMOKE_EVAL="${SMOKE_EVAL:-1}"
SMOKE_MAX_TOKENS_PER_TASK="${SMOKE_MAX_TOKENS_PER_TASK:-64}"

PUBLIC_QUALITY_PRIOR="${PUBLIC_QUALITY_PRIOR:-}"
PUBLIC_QUALITY_BASIS="${PUBLIC_QUALITY_BASIS:-}"
PUBLIC_QUALITY_SOURCE="${PUBLIC_QUALITY_SOURCE:-}"
PASSED_TASKS="${PASSED_TASKS:-}"
TOTAL_TASKS="${TOTAL_TASKS:-}"
LOCAL_QUALITY_SCORE="${LOCAL_QUALITY_SCORE:-}"
QUALITY_SCORE="${QUALITY_SCORE:-}"

SKIP_GGUF_INSPECT="${SKIP_GGUF_INSPECT:-1}"
SKIP_LLAMA="${SKIP_LLAMA:-1}"
SKIP_MTP_SIDECAR="${SKIP_MTP_SIDECAR:-1}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
bundle_dir="$OUT_ROOT/$ts-$BUNDLE_LABEL"
mkdir -p "$bundle_dir"

matrix_copy="$bundle_dir/matrix.tsv"
cp "$matrix_tsv" "$matrix_copy"

csv_path="$bundle_dir/model_runs.csv"
: >"$csv_path"

report_md="$bundle_dir/baseline_vllm_matrix_bundle.md"
{
    echo "# Baseline: vLLM matrix bundle"
    echo
    echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "- ds4_on_spark commit: $repo_rev"
    echo "- target: $target"
    echo "- matrix_tsv_src: $matrix_tsv"
    echo "- matrix_tsv_copy: $matrix_copy"
    echo "- bundle_dir: $bundle_dir"
    echo
    echo "## Command"
    echo
    echo '```sh'
    echo "BUNDLE_LABEL='$BUNDLE_LABEL' OUT_ROOT='$OUT_ROOT' \\"
    echo "ALLOW_RUN='$ALLOW_RUN' ALLOW_FETCH='$ALLOW_FETCH' \\"
    echo "PROMPT='$PROMPT' MAX_TOKENS='$MAX_TOKENS' TENSOR_PARALLEL_SIZE='$TENSOR_PARALLEL_SIZE' \\"
    echo "DFLASH_NUM_SPEC_TOKENS='$DFLASH_NUM_SPEC_TOKENS' \\"
    echo "SMOKE_EVAL='$SMOKE_EVAL' SMOKE_MAX_TOKENS_PER_TASK='$SMOKE_MAX_TOKENS_PER_TASK' \\"
    echo "SKIP_GGUF_INSPECT='$SKIP_GGUF_INSPECT' SKIP_LLAMA='$SKIP_LLAMA' SKIP_MTP_SIDECAR='$SKIP_MTP_SIDECAR' \\"
    echo "PUBLIC_QUALITY_PRIOR='$PUBLIC_QUALITY_PRIOR' PUBLIC_QUALITY_BASIS='$PUBLIC_QUALITY_BASIS' PUBLIC_QUALITY_SOURCE='$PUBLIC_QUALITY_SOURCE' \\"
    echo "PASSED_TASKS='$PASSED_TASKS' TOTAL_TASKS='$TOTAL_TASKS' LOCAL_QUALITY_SCORE='$LOCAL_QUALITY_SCORE' QUALITY_SCORE='$QUALITY_SCORE' \\"
    echo "scripts/run_baseline_vllm_matrix_bundle.sh '$target' '$matrix_tsv'"
    echo '```'
    echo
    echo "## Artifacts"
    echo
    echo "- matrix copy: $matrix_copy"
    echo "- matrix stdout: $bundle_dir/matrix_stdout.txt"
    echo "- matrix stderr: $bundle_dir/matrix_stderr.txt"
    echo "- model runs CSV: $csv_path"
    echo "- scored table: $bundle_dir/model_quality_speed_score.md"
    echo "- scored JSON: $bundle_dir/model_quality_speed_score.json"
    echo "- scored summary: $bundle_dir/model_quality_speed_scored_summary.txt"
    echo
} >"$report_md"

echo "bundle_dir=$bundle_dir"
echo "model_runs_csv=$csv_path"
echo "matrix_tsv=$matrix_copy"
echo

MODEL_RUNS_CSV="$csv_path" OUT_ROOT="$bundle_dir" ALLOW_RUN="$ALLOW_RUN" ALLOW_FETCH="$ALLOW_FETCH" PROMPT="$PROMPT" MAX_TOKENS="$MAX_TOKENS" TENSOR_PARALLEL_SIZE="$TENSOR_PARALLEL_SIZE" DFLASH_NUM_SPEC_TOKENS="$DFLASH_NUM_SPEC_TOKENS" SMOKE_EVAL="$SMOKE_EVAL" SMOKE_MAX_TOKENS_PER_TASK="$SMOKE_MAX_TOKENS_PER_TASK" SKIP_GGUF_INSPECT="$SKIP_GGUF_INSPECT" SKIP_LLAMA="$SKIP_LLAMA" SKIP_MTP_SIDECAR="$SKIP_MTP_SIDECAR" PUBLIC_QUALITY_PRIOR="$PUBLIC_QUALITY_PRIOR" PUBLIC_QUALITY_BASIS="$PUBLIC_QUALITY_BASIS" PUBLIC_QUALITY_SOURCE="$PUBLIC_QUALITY_SOURCE" PASSED_TASKS="$PASSED_TASKS" TOTAL_TASKS="$TOTAL_TASKS" LOCAL_QUALITY_SCORE="$LOCAL_QUALITY_SCORE" QUALITY_SCORE="$QUALITY_SCORE" scripts/run_baseline_vllm_matrix.sh "$target" "$matrix_copy" >"$bundle_dir/matrix_stdout.txt" 2>"$bundle_dir/matrix_stderr.txt" || true

if [ ! -r "$repo_root/scripts/model_quality_speed_score.py" ]; then
    echo "missing scorer: $repo_root/scripts/model_quality_speed_score.py" >&2
    exit 3
fi

python3 "$repo_root/scripts/model_quality_speed_score.py" "$csv_path" >"$bundle_dir/model_quality_speed_score.md" 2>"$bundle_dir/model_quality_speed_score_stderr.txt" || true
python3 "$repo_root/scripts/model_quality_speed_score.py" "$csv_path" --json >"$bundle_dir/model_quality_speed_score.json" 2>>"$bundle_dir/model_quality_speed_score_stderr.txt" || true

summary_path="$bundle_dir/model_quality_speed_scored_summary.txt"
if [ -r "$bundle_dir/model_quality_speed_score.json" ]; then
    python3 - "$bundle_dir/model_quality_speed_score.json" >"$summary_path" 2>/dev/null <<'PY' || true
import json
import sys

json_path = sys.argv[1]
try:
    rows = json.load(open(json_path, "r", encoding="utf-8"))
except OSError:
    rows = []
except json.JSONDecodeError:
    rows = []

def fmt(v):
    if v is None:
        return("")
    if isinstance(v, float):
        return(f"{v:.6f}")
    return(str(v))

want = [
    "model",
    "scope",
    "quality_score",
    "quality_source",
    "public_quality_prior",
    "public_quality_basis",
    "public_quality_source",
    "local_quality_score",
    "passed_tasks",
    "total_tasks",
    "decode_tps",
    "prefill_tps",
    "ttft_s",
    "total_wall_s",
    "output_tokens",
    "quality_adjusted_decode_tps",
    "correct_task_rate",
    "correct_tasks_per_s",
    "tokens_per_success",
    "wall_s_per_success",
    "dominated_by",
]

for r in rows:
    run_id = str(r.get("run_id", "") or "")
    if not run_id:
        continue
    sys.stdout.write(f"run_id={run_id}\n")
    for k in want:
        if k == "dominated_by":
            v = r.get(k, "")
        else:
            v = r.get(k)
        if v is None:
            continue
        sys.stdout.write(f"{k}={fmt(v)}\n")
    sys.stdout.write("\n")
PY
fi

{
    echo "## Scored summary (copy/paste)"
    echo
    if [ -r "$summary_path" ]; then
        echo '```text'
        cat "$summary_path"
        echo '```'
    else
        echo "missing: $summary_path"
    fi
    echo
} >>"$report_md"

echo "wrote:"
echo "- $report_md"
echo "- $bundle_dir/matrix_stdout.txt"
echo "- $bundle_dir/matrix_stderr.txt"
echo "- $csv_path"
echo "- $bundle_dir/model_quality_speed_score.md"
echo "- $bundle_dir/model_quality_speed_score.json"
echo "- $summary_path"
