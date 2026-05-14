#!/bin/sh
set -eu

if [ $# -lt 1 ]; then
	echo "usage: $0 spark-host" >&2
	exit 1
fi

HOST=$1
DS4_DIR=${DS4_DIR:-/home/spark0/src/ds4}
MODEL_GGUF=${MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
OUT_DIR=${OUT_DIR:-/tmp/ds4_cuda_ffn_envelope}
BATCHES=${BATCHES:-"512 1024"}
ITERS=${ITERS:-5}
LAYER=${LAYER:-1}
WITH_STAGE_PROFILE=${WITH_STAGE_PROFILE:-1}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}

remote_q() {
	printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

run_probe() {
	name=$1
	batch=$2
	stage_env=$3
	mode=$4
	echo "$name batch=$batch"
	ssh $SSH_OPTS "$HOST" "
		set -eu
		mkdir -p $(remote_q "$OUT_DIR")
		cd $(remote_q "$DS4_DIR")
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			$stage_env \
			./ds4 -m $(remote_q "$MODEL_GGUF") \
			$mode \
			--cuda-moe-layer $(remote_q "$LAYER") \
			--cuda-moe-tokens $(remote_q "$batch") \
			--cuda-moe-iters $(remote_q "$ITERS") \
			> $(remote_q "$OUT_DIR")/${name}_${batch}.out \
			2> $(remote_q "$OUT_DIR")/${name}_${batch}.err
	"
}

for b in $BATCHES; do
	run_probe moe "$b" "" "--cuda-moe-probe"
	run_probe ffn "$b" "" "--cuda-ffn-probe"
	if [ "$WITH_STAGE_PROFILE" = "1" ]; then
		run_probe ffn_stage "$b" "DS4_METAL_LAYER_STAGE_PROFILE=1" "--cuda-ffn-probe"
	fi
done

echo "wrote CUDA FFN envelope logs to $HOST:$OUT_DIR"
