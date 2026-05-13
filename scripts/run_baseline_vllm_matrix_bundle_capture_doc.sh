#!/usr/bin/env sh
set -eu

# Run a vLLM matrix bundle on Spark and copy the self-contained bundle report
# into docs/ as a commit-ready baseline note.
#
# This script does not install runtimes or download weights. Spark-side gates
# still apply via the underlying bundle runner (`ALLOW_RUN`, `ALLOW_FETCH`).
#
# Usage (example):
#   ALLOW_RUN=1 ALLOW_FETCH=0 \
#   PROMPT='Explain Redis streams in one paragraph.' \
#   MAX_TOKENS=64 TENSOR_PARALLEL_SIZE=1 \
#   scripts/run_baseline_vllm_matrix_bundle_capture_doc.sh \
#     spark0@aitopatom-9ab9.local fixtures/baseline/vllm_ling_qwen_dflash_ladder_spark0.tsv
#
# Optional overrides:
# - WRAPPER_SCRIPT: bundle runner entrypoint (default: run_baseline_vllm_matrix_bundle.sh)
# - DOC_OUT: docs output path (default: docs/baseline-vllm-matrix-<ts>-<run_label>.md)

target="${1:-spark0@aitopatom-9ab9.local}"
matrix_tsv="${2:-}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
wrapper="${WRAPPER_SCRIPT:-$repo_root/scripts/run_baseline_vllm_matrix_bundle.sh}"
doc_out="${DOC_OUT:-}"

ts="$(date -u +%Y-%m-%dT%H%M%SZ)"
run_label="${RUN_LABEL:-vllm-matrix}"
if [ "$doc_out" = "" ]; then
	doc_out="$repo_root/docs/baseline-vllm-matrix-${ts}-${run_label}.md"
fi

if [ "$matrix_tsv" = "" ]; then
	matrix_tsv="$repo_root/fixtures/baseline/vllm_matrix_template.tsv"
fi

if [ ! -r "$wrapper" ]; then
	echo "error: missing wrapper script: $wrapper" >&2
	exit 2
fi
if [ ! -r "$matrix_tsv" ]; then
	echo "error: missing matrix TSV: $matrix_tsv" >&2
	exit 3
fi

tmp_log="/private/tmp/ds4_vllm_matrix_bundle_capture_doc.$$.$ts.log"
rm -f "$tmp_log"
cleanup()
{
	rm -f "$tmp_log" 2>/dev/null || true
}
trap cleanup EXIT INT HUP TERM

echo "== run bundle wrapper =="
echo "- wrapper: $wrapper"
echo "- target: $target"
echo "- matrix_tsv: $matrix_tsv"
echo "- doc_out: $doc_out"
echo

set +e
sh "$wrapper" "$target" "$matrix_tsv" 2>&1 | tee "$tmp_log"
rc="$?"
set -e

bundle_dir="$(sed -n 's/^bundle_dir=//p' "$tmp_log" | tail -n 1 || true)"
if [ "$bundle_dir" = "" ] || [ ! -d "$bundle_dir" ]; then
	echo "error: failed to locate bundle_dir from wrapper output" >&2
	echo "note: expected a line like: bundle_dir=/path/to/bundle_dir" >&2
	echo "note: log: $tmp_log" >&2
	exit 4
fi

bundle_report="$bundle_dir/baseline_vllm_matrix_bundle.md"
if [ ! -r "$bundle_report" ]; then
	echo "error: missing bundle report: $bundle_report" >&2
	echo "note: bundle_dir: $bundle_dir" >&2
	exit 5
fi

cp "$bundle_report" "$doc_out"
echo "ok: wrote doc: $doc_out"

exit "$rc"

