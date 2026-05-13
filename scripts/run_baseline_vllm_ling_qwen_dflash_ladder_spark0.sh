#!/usr/bin/env sh
set -eu

# Convenience wrapper for the Spark0 Ling/Qwen target-only + paired Qwen DFlash
# ladder.
#
# Default behavior is metadata-only (ALLOW_RUN=0, ALLOW_FETCH=0). No weights are
# downloaded and no inference runs unless you opt in.

target="${1:-spark0@aitopatom-9ab9.local}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

MATRIX_TSV="${MATRIX_TSV:-$repo_root/fixtures/baseline/vllm_ling_qwen_dflash_ladder_spark0.tsv}"
RUN_ENV_PROBE="${RUN_ENV_PROBE:-1}"

ALLOW_RUN="${ALLOW_RUN:-0}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph.}"
MAX_TOKENS="${MAX_TOKENS:-64}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
DFLASH_NUM_SPEC_TOKENS="${DFLASH_NUM_SPEC_TOKENS:-15}"
SMOKE_EVAL="${SMOKE_EVAL:-1}"
SMOKE_MAX_TOKENS_PER_TASK="${SMOKE_MAX_TOKENS_PER_TASK:-64}"

OUT_ROOT_BASE="${OUT_ROOT_BASE:-/private/tmp/ds4_on_spark_baseline}"
OUT_ROOT_PROBE="${OUT_ROOT_PROBE:-$OUT_ROOT_BASE}"
OUT_ROOT_MATRIX="${OUT_ROOT_MATRIX:-$OUT_ROOT_BASE/vllm_matrix_bundle}"
BUNDLE_LABEL="${BUNDLE_LABEL:-vllm-ling-qwen-dflash-ladder-spark0}"

if [ ! -r "$MATRIX_TSV" ]; then
	echo "matrix TSV not found/readable: $MATRIX_TSV" >&2
	echo "hint: set MATRIX_TSV=/abs/path/to/matrix.tsv to override" >&2
	exit 2
fi

if [ "$RUN_ENV_PROBE" = "1" ]; then
	OUT_ROOT="$OUT_ROOT_PROBE" RUN_LABEL="${RUN_LABEL_ENV_PROBE:-vllm-env-probe}" \
	ALLOW_RUN="$ALLOW_RUN" scripts/run_baseline_vllm_env_probe.sh "$target" || true
fi

BUNDLE_LABEL="$BUNDLE_LABEL" OUT_ROOT="$OUT_ROOT_MATRIX" \
ALLOW_RUN="$ALLOW_RUN" ALLOW_FETCH="$ALLOW_FETCH" \
PROMPT="$PROMPT" MAX_TOKENS="$MAX_TOKENS" TENSOR_PARALLEL_SIZE="$TENSOR_PARALLEL_SIZE" \
DFLASH_NUM_SPEC_TOKENS="$DFLASH_NUM_SPEC_TOKENS" \
SMOKE_EVAL="$SMOKE_EVAL" SMOKE_MAX_TOKENS_PER_TASK="$SMOKE_MAX_TOKENS_PER_TASK" \
scripts/run_baseline_vllm_matrix_bundle.sh "$target" "$MATRIX_TSV"

