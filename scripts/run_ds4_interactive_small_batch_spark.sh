#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_id="${RUN_ID:-ds4-interactive-small-batch-$(date -u +%Y%m%dT%H%M%SZ)}"
out_root="${OUT_ROOT:-/private/tmp/$run_id}"
row_tokens="9,10,11,12,13,14,15,16,17,18,19,20,198,220,271,220"
baseline_tps="${BASELINE_AGGREGATE_TOK_S:-14.65}"
base_port_start="${BASE_PORT_START:-33100}"

cd "$repo_root"
mkdir -p "$out_root"

run_stage()
{
	local name="$1"
	local batch="$2"
	local base_port="$3"
	local local_out="$out_root/$name"
	python3 scripts/run_ds4_streaming_stage_handoff_spark.py \
		--run-id "$run_id-$name" \
		--local-out-dir "$local_out" \
		--remote-run-root "/tmp/$run_id/$name" \
		--batch "$batch" \
		--microbatches 1 \
		--pipeline-depth 1 \
		--base-port "$base_port" \
		--cleanup-stale-stage-locks \
		--stale-lock-min-age-s 5 \
		--compact-suffix-token-ids "$row_tokens" \
		--stage-env DS4_CUDA_MOE_SLICE_TILE8=1 \
		--stage-env DS4_CUDA_STACK_PROBE_BATCH_HEAD=1
}

build_artifact()
{
	local name="$1"
	local prompt_shape="$2"
	local row_count="$3"
	local logical_count="$4"
	local prompt_tokens="$5"
	python3 scripts/validate_ds4_interactive_small_batch.py build \
		--run-id "$run_id-$name" \
		--stage-handoff "$out_root/$name/summary.json" \
		--prompt-shape "$prompt_shape" \
		--row-count "$row_count" \
		--logical-question-count "$logical_count" \
		--prompt-tokens-per-row "$prompt_tokens" \
		--output-token-target 1 \
		--max-output-tokens 1 \
		--baseline-aggregate-tok-s "$baseline_tps" \
		--out "$out_root/${name}.json" >/dev/null
}

for batch in 1 2 4 8 16; do
	name="b${batch}_independent"
	if ! run_stage "$name" "$batch" "$((base_port_start + batch))"; then
		printf 'warning: %s failed; building blocked benchmark artifact\n' "$name" >&2
	fi
	if [[ "$batch" == "1" ]]; then
		build_artifact "$name" independent_rows "$batch" "$batch" 1
		live_baseline_tps="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["aggregate_output_tokens_per_s"])' "$out_root/${name}.json")"
		if python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > 0.0 else 1)' "$live_baseline_tps"; then
			baseline_tps="$live_baseline_tps"
		fi
	else
		build_artifact "$name" independent_rows "$batch" "$batch" 1
	fi
done

if ! run_stage "b4_combined_prompt_control" 1 "$((base_port_start + 104))"; then
	printf 'warning: b4_combined_prompt_control failed; building blocked benchmark artifact\n' >&2
fi
build_artifact "b4_combined_prompt_control" single_combined_prompt_control 1 4 4

printf '%s\n' "$out_root"
