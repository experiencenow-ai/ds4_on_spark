#!/usr/bin/env sh
set -eu

# Local bundle wrapper for running a vLLM Ling/Qwen/DFlash matrix on Spark and
# collecting all per-row reports + a single scored summary in one output dir.
#
# This does not install runtimes or download weights. Spark-side gates still apply.

target="${1:-spark0@aitopatom-9ab9.local}"
matrix_tsv="${2:-}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

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

csv_path="$bundle_dir/model_runs.csv"
: >"$csv_path"

echo "bundle_dir=$bundle_dir"
echo "model_runs_csv=$csv_path"
echo "matrix_tsv=$matrix_tsv"
echo

MODEL_RUNS_CSV="$csv_path" OUT_ROOT="$bundle_dir" ALLOW_RUN="$ALLOW_RUN" ALLOW_FETCH="$ALLOW_FETCH" PROMPT="$PROMPT" MAX_TOKENS="$MAX_TOKENS" TENSOR_PARALLEL_SIZE="$TENSOR_PARALLEL_SIZE" DFLASH_NUM_SPEC_TOKENS="$DFLASH_NUM_SPEC_TOKENS" SMOKE_EVAL="$SMOKE_EVAL" SMOKE_MAX_TOKENS_PER_TASK="$SMOKE_MAX_TOKENS_PER_TASK" SKIP_GGUF_INSPECT="$SKIP_GGUF_INSPECT" SKIP_LLAMA="$SKIP_LLAMA" SKIP_MTP_SIDECAR="$SKIP_MTP_SIDECAR" PUBLIC_QUALITY_PRIOR="$PUBLIC_QUALITY_PRIOR" PUBLIC_QUALITY_BASIS="$PUBLIC_QUALITY_BASIS" PUBLIC_QUALITY_SOURCE="$PUBLIC_QUALITY_SOURCE" PASSED_TASKS="$PASSED_TASKS" TOTAL_TASKS="$TOTAL_TASKS" LOCAL_QUALITY_SCORE="$LOCAL_QUALITY_SCORE" QUALITY_SCORE="$QUALITY_SCORE" scripts/run_baseline_vllm_matrix.sh "$target" "$matrix_tsv" >"$bundle_dir/matrix_stdout.txt" 2>"$bundle_dir/matrix_stderr.txt" || true

if [ ! -r "$repo_root/scripts/model_quality_speed_score.py" ]; then
    echo "missing scorer: $repo_root/scripts/model_quality_speed_score.py" >&2
    exit 3
fi

python3 "$repo_root/scripts/model_quality_speed_score.py" "$csv_path" >"$bundle_dir/model_quality_speed_score.md" 2>"$bundle_dir/model_quality_speed_score_stderr.txt" || true
python3 "$repo_root/scripts/model_quality_speed_score.py" "$csv_path" --json >"$bundle_dir/model_quality_speed_score.json" 2>>"$bundle_dir/model_quality_speed_score_stderr.txt" || true

echo "wrote:"
echo "- $bundle_dir/matrix_stdout.txt"
echo "- $bundle_dir/matrix_stderr.txt"
echo "- $csv_path"
echo "- $bundle_dir/model_quality_speed_score.md"
echo "- $bundle_dir/model_quality_speed_score.json"
