#!/bin/sh
set -u

if [ $# -lt 1 ]; then
	echo "usage: $0 spark-host" >&2
	exit 1
fi

HOST=$1
DS4_DIR=${DS4_DIR:-/home/spark0/src/ds4}
MODEL_GGUF=${MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
RUN_ID=${RUN_ID:-ds4-full-stack-truth-$(date -u +%Y%m%dT%H%M%SZ)}
REMOTE_OUT_DIR=${REMOTE_OUT_DIR:-/tmp/$RUN_ID}
LOCAL_OUT_DIR=${LOCAL_OUT_DIR:-/private/tmp/$RUN_ID}
ITERS=${ITERS:-1}
POS=${POS:-4096}
BATCHES=${BATCHES:-"16 64 128"}
EXTRA_BATCHES=${EXTRA_BATCHES:-"256"}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}
RUNTIME_ID=${RUNTIME_ID:-antirez-ds4-cuda-stack-probe}
MODEL_ID=${MODEL_ID:-deepseek-ai/DeepSeek-V4-Flash}
QUANTIZATION_ID=${QUANTIZATION_ID:-$(basename "$MODEL_GGUF")}
WARMUP_POLICY=${WARMUP_POLICY:-single-run}
RESIDENCY_POLICY=${RESIDENCY_POLICY:-skip-startup-cache-with-expert-slice-cache}

remote_q() {
	printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

fetch_log() {
	name=$1
	suffix=$2
	ssh $SSH_OPTS "$HOST" "cat $(remote_q "$REMOTE_OUT_DIR")/${name}.${suffix}" > "$LOCAL_OUT_DIR/${name}.${suffix}" 2> "$LOCAL_OUT_DIR/${name}.${suffix}.fetch.err"
	if [ ! -s "$LOCAL_OUT_DIR/${name}.${suffix}" ]; then
		touch "$LOCAL_OUT_DIR/${name}.${suffix}"
	fi
}

build_record() {
	name=$1
	rc=$2
	batch=$3
	path_kind=$4
	layers=$5
	inc_head=$6
	inc_attn=$7
	inc_kv=$8
	inc_sampling=$9
	shift 9
	head_arg=
	attn_arg=
	kv_arg=
	sampling_arg=
	if [ "$inc_head" = "1" ]; then
		head_arg=--includes-output-head
	fi
	if [ "$inc_attn" = "1" ]; then
		attn_arg=--includes-attention
	fi
	if [ "$inc_kv" = "1" ]; then
		kv_arg=--includes-kv
	fi
	if [ "$inc_sampling" = "1" ]; then
		sampling_arg=--includes-sampling
	fi
	python3 scripts/validate_ds4_full_stack_truth.py record \
		--out "$LOCAL_OUT_DIR/${name}.json" \
		--run-id "$RUN_ID-$name" \
		--model-id "$MODEL_ID" \
		--runtime-id "$RUNTIME_ID" \
		--quantization-id "$QUANTIZATION_ID" \
		--spark-node "$HOST" \
		--batch-size "$batch" \
		--path-kind "$path_kind" \
		--layers-executed "$layers" \
		$head_arg $attn_arg $kv_arg $sampling_arg \
		--warmup-policy "$WARMUP_POLICY" \
		--residency-policy "$RESIDENCY_POLICY" \
		--stdout "$LOCAL_OUT_DIR/${name}.out" \
		--stderr "$LOCAL_OUT_DIR/${name}.err" \
		--rc "$rc"
}

run_case() {
	name=$1
	mode=$2
	batch=$3
	path_kind=$4
	layers=$5
	inc_head=$6
	inc_attn=$7
	inc_kv=$8
	inc_sampling=$9
	shift 9
	env_extra=$1
	echo "== $name =="
	ssh $SSH_OPTS "$HOST" "
		set -u
		mkdir -p $(remote_q "$REMOTE_OUT_DIR")
		cd $(remote_q "$DS4_DIR")
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_STACK_PROBE_SPLIT_LAYERS=1 \
			$env_extra \
			./ds4 -m $(remote_q "$MODEL_GGUF") \
			$mode \
			--cuda-decode-pos $(remote_q "$POS") \
			--cuda-moe-tokens $(remote_q "$batch") \
			--cuda-moe-iters $(remote_q "$ITERS") \
			> $(remote_q "$REMOTE_OUT_DIR")/${name}.out \
			2> $(remote_q "$REMOTE_OUT_DIR")/${name}.err
	"
	rc=$?
	fetch_log "$name" out
	fetch_log "$name" err
	build_record "$name" "$rc" "$batch" "$path_kind" "$layers" "$inc_head" "$inc_attn" "$inc_kv" "$inc_sampling"
	echo "$name rc=$rc"
	return "$rc"
}

record_success() {
	name=$1
	python3 - "$LOCAL_OUT_DIR/${name}.json" <<'PY'
import json
import sys
obj = json.load(open(sys.argv[1], "r", encoding="utf-8"))
raise SystemExit(0 if obj.get("failure_status") == "success" else 1)
PY
}

mkdir -p "$LOCAL_OUT_DIR"

run_case output_head "--cuda-output-head-probe" 1 output_head 0 1 0 0 0 ""
run_case decode_stack_b1 "--cuda-decode-stack-probe" 1 decode_stack 43 1 1 1 0 ""

last_batch_success=0
for batch in $BATCHES; do
	name=batch_stack_b${batch}
	if run_case "$name" "--cuda-batch-stack-probe" "$batch" batch_stack_with_head 43 1 1 1 0 ""; then
		if record_success "$name"; then
			last_batch_success=1
		else
			last_batch_success=0
		fi
	else
		last_batch_success=0
	fi
done

for batch in $EXTRA_BATCHES; do
	if [ "$last_batch_success" != "1" ]; then
		break
	fi
	name=batch_stack_b${batch}
	if run_case "$name" "--cuda-batch-stack-probe" "$batch" batch_stack_with_head 43 1 1 1 0 ""; then
		if record_success "$name"; then
			last_batch_success=1
		else
			last_batch_success=0
		fi
	else
		last_batch_success=0
	fi
done

python3 scripts/validate_ds4_full_stack_truth.py validate "$LOCAL_OUT_DIR"/*.json
echo "wrote DS4 full-stack truth records to $LOCAL_OUT_DIR"
echo "remote logs: $HOST:$REMOTE_OUT_DIR"
