#!/bin/sh
set -u

if [ $# -lt 1 ]; then
	echo "usage: $0 spark-host" >&2
	exit 1
fi

HOST=$1
DS4_DIR=${DS4_DIR:-/home/spark0/src/ds4}
MODEL_GGUF=${MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
OUT_DIR=${OUT_DIR:-/tmp/ds4_cuda_stack_reality}
ITERS=${ITERS:-1}
BATCH=${BATCH:-128}
POS=${POS:-4096}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}

remote_q() {
	printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

run_case() {
	name=$1
	mode=$2
	env_extra=$3
	echo "$name"
	ssh $SSH_OPTS "$HOST" "
		set -u
		mkdir -p $(remote_q "$OUT_DIR")
		cd $(remote_q "$DS4_DIR")
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			$env_extra \
			./ds4 -m $(remote_q "$MODEL_GGUF") \
			$mode \
			--cuda-decode-pos $(remote_q "$POS") \
			--cuda-moe-tokens $(remote_q "$BATCH") \
			--cuda-moe-iters $(remote_q "$ITERS") \
			> $(remote_q "$OUT_DIR")/${name}.out \
			2> $(remote_q "$OUT_DIR")/${name}.err
	" > "$OUT_DIR.$name.local.out" 2> "$OUT_DIR.$name.local.err"
	rc=$?
	echo "$name rc=$rc"
	return 0
}

run_case output_head "--cuda-output-head-probe" ""
run_case decode_stack_no_head "--cuda-decode-stack-probe" "DS4_CUDA_STACK_PROBE_NO_HEAD=1 DS4_CUDA_STACK_PROBE_SPLIT_LAYERS=1"
run_case batch_stack_no_head "--cuda-batch-stack-probe" "DS4_CUDA_STACK_PROBE_NO_HEAD=1 DS4_CUDA_STACK_PROBE_SPLIT_LAYERS=1"

echo "wrote CUDA stack reality logs to $HOST:$OUT_DIR"
