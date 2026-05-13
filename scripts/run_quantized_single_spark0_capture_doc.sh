#!/usr/bin/env sh
set -eu

# Run the quantized single-Spark Spark0 milestone wrapper and immediately render
# a commit-ready baseline report into docs/.
#
# This script never downloads weights or builds runtimes. Token generation is
# still gated by ALLOW_RUN=1 (see the underlying wrapper).
#
# Usage:
#   ALLOW_RUN=1 OUT_ROOT=/private/tmp/ds4_on_spark_baseline \
#     scripts/run_quantized_single_spark0_capture_doc.sh spark0@aitopatom-9ab9.local
#
# Optional overrides:
# - WRAPPER_SCRIPT: wrapper entrypoint (default: smallest-credible external)
# - DOC_OUT: docs output path (default: docs/baseline-quantized-single-spark0-<ts>-<run_label>.md)

target="${1:-spark0@aitopatom-9ab9.local}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
wrapper="${WRAPPER_SCRIPT:-$repo_root/scripts/run_quantized_single_spark0_smallest_credible_v4flash_external.sh}"
doc_out="${DOC_OUT:-}"

ts="$(date -u +%Y-%m-%dT%H%M%SZ)"
run_label="${RUN_LABEL:-quantized-single-spark0-smallest-credible}"

if [ "$doc_out" = "" ]; then
	doc_out="$repo_root/docs/baseline-quantized-single-spark0-${ts}-${run_label}.md"
fi

if [ ! -r "$wrapper" ]; then
	echo "error: missing wrapper script: $wrapper" >&2
	exit 2
fi

tmp_log="/private/tmp/ds4_quantized_single_spark0_capture_doc.$$.$ts.log"
rm -f "$tmp_log"
cleanup()
{
	rm -f "$tmp_log" 2>/dev/null || true
}
trap cleanup EXIT INT HUP TERM

echo "== run wrapper =="
echo "- wrapper: $wrapper"
echo "- target: $target"
echo "- doc_out: $doc_out"
echo

set +e
sh "$wrapper" "$target" 2>&1 | tee "$tmp_log"
rc="$?"
set -e

out_dir="$(sed -n 's/^writing report to: //p' "$tmp_log" | tail -n 1 || true)"
if [ "$out_dir" = "" ] || [ ! -d "$out_dir" ]; then
	echo "error: failed to locate OUT_DIR from wrapper output" >&2
	echo "note: expected a line like: writing report to: /path/to/out_dir" >&2
	echo "note: log: $tmp_log" >&2
	exit 3
fi

echo
echo "== render report =="
python3 "$repo_root/scripts/render_quantized_single_spark_report.py" "$out_dir" --write "$doc_out"
echo "ok: wrote doc: $doc_out"

exit "$rc"

