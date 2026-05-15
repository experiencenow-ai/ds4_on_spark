#!/bin/sh
set -u

if [ $# -lt 1 ]; then
	echo "usage: $0 spark-host" >&2
	exit 1
fi

HOST=$1
DS4_DIR=${DS4_DIR:-/home/spark0/src/ds4}
MODEL_GGUF=${MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
RUN_ID=${RUN_ID:-ds4-perf-iceberg-$(date -u +%Y%m%dT%H%M%SZ)}
REMOTE_OUT_DIR=${REMOTE_OUT_DIR:-/tmp/$RUN_ID}
LOCAL_OUT_DIR=${LOCAL_OUT_DIR:-/private/tmp/$RUN_ID}
ITERS=${ITERS:-1}
HEAD_ITERS=${HEAD_ITERS:-3}
POS=${POS:-4096}
HEAD_BATCHES=${HEAD_BATCHES:-"1 16 64 128 512 1024"}
STACK_BATCHES=${STACK_BATCHES:-"1 16 64 128 512 1024"}
PREFILL_TOKENS=${PREFILL_TOKENS:-"512 2048 8192"}
RUN_PREFILL=${RUN_PREFILL:-0}
RUN_KV=${RUN_KV:-0}
RUN_TRANSFER=${RUN_TRANSFER:-0}
PRELOAD_STAGE=${PRELOAD_STAGE:-1}
PRELOAD_CHUNK_MB=${PRELOAD_CHUNK_MB:-64}
PRELOAD_SLEEP_US=${PRELOAD_SLEEP_US:-0}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}
RUNTIME_ID=${RUNTIME_ID:-antirez-ds4-cuda-stack-probe}
MODEL_ID=${MODEL_ID:-deepseek-ai/DeepSeek-V4-Flash}
QUANTIZATION_ID=${QUANTIZATION_ID:-$(basename "$MODEL_GGUF")}
WARMUP_POLICY=${WARMUP_POLICY:-single-run}
RESIDENCY_POLICY=${RESIDENCY_POLICY:-exact-stage-preload-all-layers-strict-expert-slices}

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

identity_args() {
	printf "%s" "--run-id $RUN_ID --model-id $MODEL_ID --runtime-id $RUNTIME_ID --quantization-id $QUANTIZATION_ID --spark-node $HOST"
}

record_case() {
	name=$1
	rc=$2
	component_kind=$3
	batch=$4
	input_tokens=$5
	context_tokens=$6
	active_sessions=$7
	layers=$8
	inc_head=$9
	shift 9
	inc_attn=$1
	inc_kv=$2
	inc_sampling=$3
	component_only=$4
	shift 4
	extra_args=$*
	head_arg=
	attn_arg=
	kv_arg=
	sampling_arg=
	component_arg=
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
	if [ "$component_only" = "1" ]; then
		component_arg=--component-only
	fi
	python3 scripts/validate_ds4_perf_icebergs.py record \
		--out "$LOCAL_OUT_DIR/${name}.record.json" \
		--run-id "$RUN_ID-$name" \
		--case-id "$name" \
		--model-id "$MODEL_ID" \
		--runtime-id "$RUNTIME_ID" \
		--quantization-id "$QUANTIZATION_ID" \
		--spark-node "$HOST" \
		--component-kind "$component_kind" \
		--batch-size "$batch" \
		--input-tokens "$input_tokens" \
		--context-tokens "$context_tokens" \
		--active-sessions "$active_sessions" \
		--layers-executed "$layers" \
		$head_arg $attn_arg $kv_arg $sampling_arg $component_arg \
		--warmup-policy "$WARMUP_POLICY" \
		--residency-policy "$RESIDENCY_POLICY" \
		--stdout "$LOCAL_OUT_DIR/${name}.out" \
		--stderr "$LOCAL_OUT_DIR/${name}.err" \
		--rc "$rc" \
		$extra_args
}

record_not_run() {
	name=$1
	component_kind=$2
	blocker=$3
	detail=$4
	touch "$LOCAL_OUT_DIR/${name}.out" "$LOCAL_OUT_DIR/${name}.err"
	python3 scripts/validate_ds4_perf_icebergs.py record \
		--out "$LOCAL_OUT_DIR/${name}.record.json" \
		--run-id "$RUN_ID-$name" \
		--case-id "$name" \
		--model-id "$MODEL_ID" \
		--runtime-id "$RUNTIME_ID" \
		--quantization-id "$QUANTIZATION_ID" \
		--spark-node "$HOST" \
		--component-kind "$component_kind" \
		--component-only \
		--warmup-policy "$WARMUP_POLICY" \
		--residency-policy "$RESIDENCY_POLICY" \
		--stdout "$LOCAL_OUT_DIR/${name}.out" \
		--stderr "$LOCAL_OUT_DIR/${name}.err" \
		--rc 0 \
		--failure-status not_run \
		--blocker-kind "$blocker" \
		--blocker-detail "$detail"
}

run_remote_case() {
	name=$1
	mode=$2
	batch=$3
	component_kind=$4
	layers=$5
	inc_head=$6
	inc_attn=$7
	inc_kv=$8
	inc_sampling=$9
	shift 9
	component_only=$1
	shift 1
	preload_enabled=$1
	shift 1
	env_extra=$1
	preload_env=
	cmd_iters=$ITERS
	if [ "$component_kind" = "output_head" ]; then
		cmd_iters=$HEAD_ITERS
	fi
	if [ "$preload_enabled" = "1" ]; then
		preload_env="DS4_CUDA_STACK_PROBE_PRELOAD_STAGE=1 DS4_CUDA_STACK_PROBE_PRELOAD_CHUNK_MB=$(remote_q "$PRELOAD_CHUNK_MB") DS4_CUDA_STACK_PROBE_PRELOAD_SLEEP_US=$(remote_q "$PRELOAD_SLEEP_US") DS4_CUDA_STACK_PROBE_LAYER_BEGIN=0 DS4_CUDA_STACK_PROBE_LAYER_END=43"
	fi
	echo "== $name =="
	ssh $SSH_OPTS "$HOST" "
		set -u
		mkdir -p $(remote_q "$REMOTE_OUT_DIR")
		cd $(remote_q "$DS4_DIR")
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_STACK_PROBE_SPLIT_LAYERS=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_STRICT=1 \
			$preload_env \
			$env_extra \
			./ds4 -m $(remote_q "$MODEL_GGUF") \
			$mode \
			--cuda-decode-pos $(remote_q "$POS") \
			--cuda-moe-tokens $(remote_q "$batch") \
			--cuda-moe-iters $(remote_q "$cmd_iters") \
			> $(remote_q "$REMOTE_OUT_DIR")/${name}.out \
			2> $(remote_q "$REMOTE_OUT_DIR")/${name}.err
	"
	rc=$?
	fetch_log "$name" out
	fetch_log "$name" err
	record_case "$name" "$rc" "$component_kind" "$batch" 0 "$POS" "$batch" "$layers" "$inc_head" "$inc_attn" "$inc_kv" "$inc_sampling" "$component_only"
	echo "$name rc=$rc"
	return "$rc"
}

run_prefill_case() {
	tokens=$1
	name=prefix_miss_prefill_t${tokens}
	echo "== $name =="
	ssh $SSH_OPTS "$HOST" "
		set -u
		mkdir -p $(remote_q "$REMOTE_OUT_DIR")
		cd $(remote_q "$DS4_DIR")
		python3 -c 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text((\"centaur skeleton dry file routing \" * int(sys.argv[2])), encoding=\"utf-8\")' $(remote_q "$REMOTE_OUT_DIR")/${name}.prompt $(remote_q "$tokens")
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			./ds4 -m $(remote_q "$MODEL_GGUF") \
			--metal-graph-prompt-test \
			--ctx $(remote_q "$tokens") \
			$(remote_q "perf prefill probe") \
			> $(remote_q "$REMOTE_OUT_DIR")/${name}.out \
			2> $(remote_q "$REMOTE_OUT_DIR")/${name}.err
	"
	rc=$?
	fetch_log "$name" out
	fetch_log "$name" err
	record_case "$name" "$rc" prefix_miss_prefill 1 "$tokens" "$tokens" 1 43 1 1 1 0 1
	echo "$name rc=$rc"
	return "$rc"
}

mkdir -p "$LOCAL_OUT_DIR"

for batch in $HEAD_BATCHES; do
	run_remote_case "output_head_b${batch}" "--cuda-output-head-probe" "$batch" output_head 0 1 0 0 0 1 0 ""
done

run_remote_case decode_stack_b1 "--cuda-decode-stack-probe" 1 full_stack_decode 43 1 1 1 0 0 "$PRELOAD_STAGE" ""

for batch in $STACK_BATCHES; do
	run_remote_case "batch_no_head_b${batch}" "--cuda-batch-stack-probe" "$batch" full_stack_batch_no_head 43 0 1 1 0 1 "$PRELOAD_STAGE" "DS4_CUDA_STACK_PROBE_NO_HEAD=1"
	run_remote_case "batch_with_head_b${batch}" "--cuda-batch-stack-probe" "$batch" full_stack_batch_with_head 43 1 1 1 0 0 "$PRELOAD_STAGE" ""
done

if [ "$RUN_PREFILL" = "1" ]; then
	for tokens in $PREFILL_TOKENS; do
		run_prefill_case "$tokens"
	done
else
	record_not_run prefix_miss_prefill prefix_miss_prefill not_instrumented "set RUN_PREFILL=1 after confirming the DS4 prompt-prefill CLI path on this build"
fi

record_not_run prefix_hit_load_or_fork prefix_hit_load_or_fork not_instrumented "prefix cache hit/load/fork probe is not wired into the antirez DS4 build yet"
record_not_run suffix_prefill suffix_prefill not_instrumented "suffix prefill needs a prefix-cache-aware probe; full-stack residency is the current blocker"

if [ "$RUN_KV" = "1" ]; then
	record_not_run kv_pressure kv_pressure not_instrumented "KV sweep requested but no repo-owned KV resident-byte probe is wired into this build"
else
	record_not_run kv_pressure kv_pressure not_instrumented "set RUN_KV=1 after a repo-owned KV resident-byte probe exists"
fi

if [ "$RUN_TRANSFER" = "1" ]; then
	record_not_run activation_transfer activation_transfer not_instrumented "run the existing activation-transfer benchmark separately on the current high-speed path"
else
	record_not_run activation_transfer activation_transfer not_instrumented "set RUN_TRANSFER=1 after selecting the current Spark link pair for activation-boundary payloads"
fi

python3 scripts/validate_ds4_perf_icebergs.py summarize \
	--out "$LOCAL_OUT_DIR/spark0_perf_iceberg_summary.latest.json" \
	--run-id "$RUN_ID" \
	--model-id "$MODEL_ID" \
	--runtime-id "$RUNTIME_ID" \
	--quantization-id "$QUANTIZATION_ID" \
	--spark-node "$HOST" \
	"$LOCAL_OUT_DIR"/*.record.json

python3 scripts/validate_ds4_perf_icebergs.py validate "$LOCAL_OUT_DIR"/*.json
echo "wrote DS4 performance iceberg records to $LOCAL_OUT_DIR"
echo "remote logs: $HOST:$REMOTE_OUT_DIR"
