#!/usr/bin/env sh
set -eu

target="${1:-spark0@172.16.11.228}"
SAMPLE_COUNT="${SAMPLE_COUNT:-10}"
WARMUP_COUNT="${WARMUP_COUNT:-1}"
OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_on_spark_antirez_ds4_mtp_timing_samples}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-mtp-k2-timing-samples}"
MTP_DRAFT="${MTP_DRAFT:-2}"
N_PREDICT="${N_PREDICT:-126}"
CTX="${CTX:-2048}"
SEED="${SEED:-1234}"
PROMPT="${PROMPT:-Explain Redis streams in one paragraph. Keep it concise, covering key features: append-only log, consumer groups, blocking reads, message persistence, and}"
REMOTE_PREP_ENV="${REMOTE_PREP_ENV:-ALLOW_FETCH=1 ALLOW_PATCH=1 ALLOW_BUILD=1 ALLOW_RUN=1}"
REMOTE_RUN_ENV="${REMOTE_RUN_ENV:-ALLOW_RUN=1}"
REMOTE_COMMON_ENV="${REMOTE_COMMON_ENV:-DS4_MTP_MEASURED_MODE=1 DS4_SUPPRESS_OUTPUT=1 DS4_MTP_SAMPLE_DIAG=1}"
REMOTE_BASELINE_EXTRA_ENV="${REMOTE_BASELINE_EXTRA_ENV:-DS4_MTP_SPEC_DISABLE=1 RUN_LABEL=baseline}"
REMOTE_MTP_EXTRA_ENV="${REMOTE_MTP_EXTRA_ENV:-RUN_LABEL=mtp}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
single_runner="$repo_root/scripts/run_antirez_ds4_mtp_multitoken_acceptance_probe_spark.sh"
samples_builder="$repo_root/scripts/build_ds4_mtp_timing_samples.py"
samples_summary_builder="$repo_root/scripts/build_ds4_mtp_timing_samples_summary.py"
samples_validator="$repo_root/scripts/validate_ds4_mtp_timing_samples.py"
repeat_splitter="$repo_root/scripts/split_ds4_mtp_repeat_samples.py"

if [ "$SAMPLE_COUNT" -lt 10 ]; then
	echo "SAMPLE_COUNT must be >= 10 for direction-setting timing evidence" 1>&2
	exit 2
fi
if [ ! -x "$single_runner" ] || [ ! -r "$samples_builder" ] || [ ! -r "$samples_summary_builder" ] || [ ! -r "$samples_validator" ] || [ ! -r "$repeat_splitter" ]; then
	echo "missing runner or timing-sample scripts under $repo_root" 1>&2
	exit 3
fi

run_root="$OUT_ROOT/$RUN_ID"
baseline_root="$run_root/baseline"
mtp_root="$run_root/mtp"
mkdir -p "$baseline_root" "$mtp_root"

run_phase_repeated()
{
	phase="$1"
	phase_root="$2"
	phase_extra="$3"
	gate_env="$4"
	combined_root="$phase_root/_combined"
	rm -rf "$combined_root"
	mkdir -p "$combined_root"
	remote_env="$gate_env $REMOTE_COMMON_ENV $phase_extra DS4_MTP_BENCH_WARMUP_REPEATS=$WARMUP_COUNT DS4_MTP_BENCH_REPEATS=$SAMPLE_COUNT N_PREDICT=$N_PREDICT MTP_DRAFT=$MTP_DRAFT CTX=$CTX SEED=$SEED PROMPT=$(printf "%s" "$PROMPT" | python3 -c 'import shlex,sys; print(shlex.quote(sys.stdin.read()))')"
	echo "== $phase repeated sample run 1x setup + $WARMUP_COUNT warmup + $SAMPLE_COUNT measured generations =="
	OUT_ROOT="$combined_root" \
	RUN_ID="$RUN_ID-$phase-combined" \
	MTP_DRAFT="$MTP_DRAFT" \
	PROMPT="$PROMPT" \
	REMOTE_ANTIREZ_DS4_MTP_ACCEPT_ENV="$remote_env" \
	"$single_runner" "$target"
	combined_dir="$(find "$combined_root" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
	if [ "$combined_dir" = "" ]; then
		echo "missing combined run dir for $phase under $combined_root" 1>&2
		exit 4
	fi
	python3 "$repeat_splitter" \
		--log "$combined_dir/remote_probe_stdout.txt" \
		--log "$combined_dir/remote_probe_stderr.txt" \
		--out-dir "$phase_root" \
		--expected-count "$SAMPLE_COUNT" \
		>"$phase_root/repeat_split_stdout.json"
}

run_phase_repeated "baseline" "$baseline_root" "$REMOTE_BASELINE_EXTRA_ENV" "$REMOTE_PREP_ENV"
run_phase_repeated "mtp" "$mtp_root" "$REMOTE_MTP_EXTRA_ENV" "$REMOTE_RUN_ENV"

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
