#!/usr/bin/env sh
set -eu

# vLLM multi-run wrapper for Ling/Qwen target-only + paired DFlash probes.
#
# Safety posture:
# - Does not install runtimes or download weights by default.
# - Uses the existing `scripts/run_baseline_vllm_dflash_pair.sh` wrapper, which in turn
#   calls `scripts/run_baseline_existing_runtime.sh` (Spark-side gates still apply).
#
# Matrix TSV columns (tab-separated; comments allowed with leading '#'):
#   run_label  scope_target  scope_dflash  target_id  target_model_dir  draft_model_dir(optional)

target="${1:-spark0@aitopatom-9ab9.local}"
matrix_tsv="${2:-}"

if [ "$matrix_tsv" = "" ] || [ ! -r "$matrix_tsv" ]; then
    echo "usage: scripts/run_baseline_vllm_matrix.sh <target> <matrix.tsv>" >&2
    echo "matrix TSV columns:" >&2
    echo "  run_label<TAB>scope_target<TAB>scope_dflash<TAB>target_id<TAB>target_model_dir<TAB>draft_model_dir(optional)" >&2
    exit 2
fi

ALLOW_RUN="${ALLOW_RUN:-0}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
MAX_TOKENS="${MAX_TOKENS:-64}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
DFLASH_NUM_SPEC_TOKENS="${DFLASH_NUM_SPEC_TOKENS:-15}"
MATRIX_CONTINUE_ON_ERROR="${MATRIX_CONTINUE_ON_ERROR:-1}"

MODEL_RUNS_CSV="${MODEL_RUNS_CSV:-}"
PUBLIC_QUALITY_PRIOR="${PUBLIC_QUALITY_PRIOR:-}"
PUBLIC_QUALITY_BASIS="${PUBLIC_QUALITY_BASIS:-}"
PUBLIC_QUALITY_SOURCE="${PUBLIC_QUALITY_SOURCE:-}"
PASSED_TASKS="${PASSED_TASKS:-}"
TOTAL_TASKS="${TOTAL_TASKS:-}"
LOCAL_QUALITY_SCORE="${LOCAL_QUALITY_SCORE:-}"
QUALITY_SCORE="${QUALITY_SCORE:-}"

# Most vLLM comparisons should skip DeepSeek-specific probes by default.
SKIP_GGUF_INSPECT="${SKIP_GGUF_INSPECT:-1}"
SKIP_LLAMA="${SKIP_LLAMA:-1}"
SKIP_MTP_SIDECAR="${SKIP_MTP_SIDECAR:-1}"

if [ "$MODEL_RUNS_CSV" = "" ]; then
    echo "warning: MODEL_RUNS_CSV is not set; quality/speed scoring artifacts will not be written" >&2
fi

tab="$(printf '\t')"
line_no=0
ok_rows=0
fail_rows=0
fail_list=""
while IFS="$tab" read -r run_label scope_target scope_dflash target_id target_model draft_model _rest; do
    line_no=$((line_no + 1))
    case "$run_label" in
        ""|\#*|run_label)
            continue
            ;;
    esac
    if [ "$target_model" = "" ]; then
        echo "matrix error: line $line_no: target_model_dir is required" >&2
        exit 3
    fi
    if [ "$scope_target" = "" ]; then
        scope_target="vllm_target"
    fi
    if [ "$scope_dflash" = "" ]; then
        scope_dflash="vllm_dflash"
    fi

    echo
    echo "== matrix row $line_no: $run_label =="
    echo "target_id=${target_id:-$target_model}"
    echo "target_model=$target_model"
    if [ "$draft_model" != "" ]; then
        echo "draft_model=$draft_model"
    else
        echo "draft_model=(none)"
    fi

    set +e
    RUN_LABEL="$run_label" MODEL_RUNS_CSV="$MODEL_RUNS_CSV" PROMPT="$PROMPT" MAX_TOKENS="$MAX_TOKENS" TENSOR_PARALLEL_SIZE="$TENSOR_PARALLEL_SIZE" DFLASH_NUM_SPEC_TOKENS="$DFLASH_NUM_SPEC_TOKENS" ALLOW_RUN="$ALLOW_RUN" ALLOW_FETCH="$ALLOW_FETCH" VLLM_SCOPE_TARGET="$scope_target" VLLM_SCOPE_DFLASH="$scope_dflash" VLLM_TARGET_ID="$target_id" VLLM_TARGET_MODEL="$target_model" VLLM_DRAFT_MODEL="$draft_model" SKIP_GGUF_INSPECT="$SKIP_GGUF_INSPECT" SKIP_LLAMA="$SKIP_LLAMA" SKIP_MTP_SIDECAR="$SKIP_MTP_SIDECAR" PUBLIC_QUALITY_PRIOR="$PUBLIC_QUALITY_PRIOR" PUBLIC_QUALITY_BASIS="$PUBLIC_QUALITY_BASIS" PUBLIC_QUALITY_SOURCE="$PUBLIC_QUALITY_SOURCE" PASSED_TASKS="$PASSED_TASKS" TOTAL_TASKS="$TOTAL_TASKS" LOCAL_QUALITY_SCORE="$LOCAL_QUALITY_SCORE" QUALITY_SCORE="$QUALITY_SCORE" scripts/run_baseline_vllm_dflash_pair.sh "$target"
    row_rc="$?"
    set -e
    if [ "$row_rc" -ne 0 ]; then
        fail_rows=$((fail_rows + 1))
        if [ "$fail_list" = "" ]; then
            fail_list="$run_label:$row_rc"
        else
            fail_list="$fail_list $run_label:$row_rc"
        fi
        echo "matrix row failed: line=$line_no label=$run_label rc=$row_rc" >&2
        if [ "$MATRIX_CONTINUE_ON_ERROR" != "1" ]; then
            exit "$row_rc"
        fi
    else
        ok_rows=$((ok_rows + 1))
    fi
done <"$matrix_tsv"

echo
echo "== matrix summary =="
echo "ok_rows=$ok_rows"
echo "fail_rows=$fail_rows"
if [ "$fail_list" != "" ]; then
    echo "failed=$fail_list"
fi
