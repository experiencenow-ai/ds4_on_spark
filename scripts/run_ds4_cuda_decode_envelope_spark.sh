#!/bin/sh
set -eu

if [ $# -lt 1 ]; then
	echo "usage: $0 spark-host" >&2
	exit 1
fi

HOST=$1
DS4_DIR=${DS4_DIR:-/home/spark0/src/ds4}
MODEL_GGUF=${MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
OUT_DIR=${OUT_DIR:-/tmp/ds4_cuda_decode_envelope}
DECODE_CASES=${DECODE_CASES:-"0:128 1:128 2:4096 3:4096"}
FULL_BATCH_LAYERS=${FULL_BATCH_LAYERS:-"0 1 2 3"}
BATCH=${BATCH:-1024}
ITERS=${ITERS:-4}
WITH_STAGE_PROFILE=${WITH_STAGE_PROFILE:-1}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}

remote_q() {
	printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

run_remote() {
	name=$1
	mode=$2
	layer=$3
	pos=$4
	stage_env=$5
	echo "$name layer=$layer pos=$pos"
	ssh $SSH_OPTS "$HOST" "
		set -eu
		mkdir -p $(remote_q "$OUT_DIR")
		cd $(remote_q "$DS4_DIR")
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			$stage_env \
			./ds4 -m $(remote_q "$MODEL_GGUF") \
			$mode \
			--cuda-moe-layer $(remote_q "$layer") \
			--cuda-decode-pos $(remote_q "$pos") \
			--cuda-moe-tokens $(remote_q "$BATCH") \
			--cuda-moe-iters $(remote_q "$ITERS") \
			> $(remote_q "$OUT_DIR")/${name}_layer${layer}_pos${pos}.out \
			2> $(remote_q "$OUT_DIR")/${name}_layer${layer}_pos${pos}.err
	"
}

for item in $DECODE_CASES; do
	layer=${item%%:*}
	pos=${item#*:}
	stage_env=""
	if [ "$WITH_STAGE_PROFILE" = "1" ]; then
		stage_env="DS4_METAL_DECODE_STAGE_PROFILE=1 DS4_METAL_INDEXER_STAGE_PROFILE=1"
	fi
	run_remote decode "--cuda-decode-probe" "$layer" "$pos" "$stage_env"
done

for layer in $FULL_BATCH_LAYERS; do
	stage_env=""
	if [ "$WITH_STAGE_PROFILE" = "1" ]; then
		stage_env="DS4_METAL_LAYER_STAGE_PROFILE=1"
	fi
	run_remote full_batch "--cuda-layer-probe" "$layer" "0" "$stage_env"
done

echo "wrote CUDA decode envelope logs to $HOST:$OUT_DIR"
