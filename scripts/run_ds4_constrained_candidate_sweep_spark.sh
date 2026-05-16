#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_id="${RUN_ID:-ds4-constrained-candidate-sweep-$(date -u +%Y%m%dT%H%M%SZ)}"
out_root="${OUT_ROOT:-/private/tmp/$run_id}"
full_vocab_control="${FULL_VOCAB_CONTROL:-fixtures/constrained_output/ds4_b512_full_vocab_control_hit_1_token_20260516.example.json}"
parity_artifact="${PARITY_ARTIFACT:-fixtures/pipeline_parity/dsv4_slice_tile8_cross_spark_ppn_passed_20260516.example.json}"
compact_suffix="9,10,11,12,13,14,15,16,17,18,19,20,198,220,271"
numeric_ids="15,16,17,18,19,20,220,271,198,13,11,10,9,12,14"
counts=(15 32 64 128 256 512 1024 2048)
build_args=()

cd "$repo_root"
mkdir -p "$out_root"
parity_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact_sha256"])' "$parity_artifact")"

candidate_ids_for_count()
{
	local count="$1"
	if [[ "$count" == "15" ]]; then
		printf '%s\n' "$numeric_ids"
	else
		python3 -c 'import sys; n=int(sys.argv[1]); print(",".join(str(i) for i in range(n)))' "$count"
	fi
}

kind_for_count()
{
	local count="$1"
	if [[ "$count" == "15" ]]; then
		printf '%s\n' "numeric_ids"
	else
		printf '%s\n' "synthetic_candidate_set"
	fi
}

for count in "${counts[@]}"; do
	ids="$(candidate_ids_for_count "$count")"
	kind="$(kind_for_count "$count")"
	local_out="$out_root/candidate_${count}"
	remote_root="/tmp/$run_id/candidate_${count}"
	python3 scripts/run_ds4_streaming_stage_handoff_spark.py \
		--run-id "$run_id-candidate-$count" \
		--local-out-dir "$local_out" \
		--remote-run-root "$remote_root" \
		--batch 512 \
		--microbatches 16 \
		--pipeline-depth 3 \
		--base-port "$((27100 + count % 1000))" \
		--cleanup-stale-stage-locks \
		--stale-lock-min-age-s 5 \
		--compact-suffix-token-ids "$compact_suffix" \
		--stage-env DS4_CUDA_MOE_SLICE_TILE8=1 \
		--stage-env DS4_CUDA_STACK_PROBE_BATCH_HEAD=1 \
		--stage-env "DS4_CUDA_STACK_PROBE_CONSTRAINED_TOKEN_IDS=$ids"
	build_args+=(--stage-artifact "$count:$kind:$local_out/summary.json")
done

python3 scripts/validate_ds4_constrained_candidate_sweep.py build \
	--run-id "$run_id" \
	"${build_args[@]}" \
	--full-vocab-control "$full_vocab_control" \
	--parity-artifact-sha256 "$parity_sha" \
	--out "$out_root/constrained_candidate_sweep.json"

printf '%s\n' "$out_root/constrained_candidate_sweep.json"
