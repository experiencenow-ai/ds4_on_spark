#!/usr/bin/env sh
set -eu

target="${1:-spark0@172.16.11.228}"
SAMPLE_COUNT="${SAMPLE_COUNT:-10}"
OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_antirez_ds4_mtp_timing_samples}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-mtp-k2-timing-samples}"
MTP_DRAFT="${MTP_DRAFT:-2}"
N_PREDICT="${N_PREDICT:-126}"
CTX="${CTX:-2048}"
SEED="${SEED:-1234}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph. Keep it concise, covering key features: append-only log, consumer groups, blocking reads, message persistence, and}"
REMOTE_PREP_ENV="${REMOTE_PREP_ENV:-ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1}"
REMOTE_RUN_ENV="${REMOTE_RUN_ENV:-ALLOW_RUN=1}"
REMOTE_COMMON_ENV="${REMOTE_COMMON_ENV:-DS4_MTP_MEASURED_MODE=1 DS4_SUPPRESS_OUTPUT=1}"
REMOTE_BASELINE_EXTRA_ENV="${REMOTE_BASELINE_EXTRA_ENV:-DS4_MTP_SPEC_DISABLE=1 RUN_LABEL=baseline}"
REMOTE_MTP_EXTRA_ENV="${REMOTE_MTP_EXTRA_ENV:-RUN_LABEL=mtp}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
single_runner="$repo_root/scripts/run_antirez_ds4_mtp_multitoken_acceptance_probe_spark.sh"
samples_builder="$repo_root/scripts/build_ds4_mtp_timing_samples.py"
samples_summary_builder="$repo_root/scripts/build_ds4_mtp_timing_samples_summary.py"
samples_validator="$repo_root/scripts/validate_ds4_mtp_timing_samples.py"

if [ "$SAMPLE_COUNT" -lt 10 ]; then
	echo "SAMPLE_COUNT must be >= 10 for direction-setting timing evidence" 1>&2
	exit 2
fi
if [ ! -x "$single_runner" ] || [ ! -r "$samples_builder" ] || [ ! -r "$samples_summary_builder" ] || [ ! -r "$samples_validator" ]; then
	echo "missing runner or timing-sample scripts under $repo_root" 1>&2
	exit 3
fi

run_root="$OUT_ROOT/$RUN_ID"
baseline_root="$run_root/baseline"
mtp_root="$run_root/mtp"
mkdir -p "$baseline_root" "$mtp_root"

run_phase_sample()
{
	phase="$1"
	idx="$2"
	phase_root="$3"
	phase_extra="$4"
	gate_env="$5"
	remote_env="$gate_env $REMOTE_COMMON_ENV $phase_extra N_PREDICT=$N_PREDICT MTP_DRAFT=$MTP_DRAFT CTX=$CTX SEED=$SEED PROMPT=$(printf "%s" "$PROMPT" | python3 -c 'import shlex,sys; print(shlex.quote(sys.stdin.read()))')"
	echo "== $phase sample $idx/$SAMPLE_COUNT =="
	OUT_ROOT="$phase_root" \
	RUN_ID="$RUN_ID-$phase-$idx" \
	MTP_DRAFT="$MTP_DRAFT" \
	PROMPT="$PROMPT" \
	REMOTE_ANTIREZ_DS4_MTP_ACCEPT_ENV="$remote_env" \
	"$single_runner" "$target"
}

i=1
while [ "$i" -le "$SAMPLE_COUNT" ]; do
	if [ "$i" -eq 1 ]; then
		gate_env="$REMOTE_PREP_ENV"
	else
		gate_env="$REMOTE_RUN_ENV"
	fi
	run_phase_sample "baseline" "$i" "$baseline_root" "$REMOTE_BASELINE_EXTRA_ENV" "$gate_env"
	i=$((i + 1))
done

i=1
while [ "$i" -le "$SAMPLE_COUNT" ]; do
	run_phase_sample "mtp" "$i" "$mtp_root" "$REMOTE_MTP_EXTRA_ENV" "$REMOTE_RUN_ENV"
	i=$((i + 1))
done

baseline_report="$run_root/baseline_timing_samples.json"
mtp_report="$run_root/mtp_timing_samples.json"
summary_report="$run_root/timing_samples_summary.json"

python3 "$samples_builder" \
	--sample-dir "$baseline_root" \
	--run-id "$RUN_ID-baseline" \
	--label "baseline-spec-disabled" \
	--min-sample-count "$SAMPLE_COUNT" \
	--out-json "$baseline_report"
python3 "$samples_validator" "$baseline_report" >"$run_root/baseline_timing_samples_validate.json"

baseline_median="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["generation_tps_median"])' "$baseline_report")"
python3 "$samples_builder" \
	--sample-dir "$mtp_root" \
	--run-id "$RUN_ID-mtp" \
	--label "mtp-draft-$MTP_DRAFT" \
	--min-sample-count "$SAMPLE_COUNT" \
	--baseline-tps "$baseline_median" \
	--out-json "$mtp_report"
python3 "$samples_validator" "$mtp_report" >"$run_root/mtp_timing_samples_validate.json"

python3 "$samples_summary_builder" \
	--baseline-report "$baseline_report" \
	--mtp-report "$mtp_report" \
	--out-json "$summary_report"

echo "done: $run_root"
