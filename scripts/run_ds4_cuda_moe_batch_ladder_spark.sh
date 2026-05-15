#!/bin/sh
set -eu

if [ $# -lt 1 ]; then
	echo "usage: $0 spark-host" >&2
	exit 1
fi

HOST=$1
DS4_DIR=${DS4_DIR:-/home/spark0/src/ds4_perf_stack_20260515T080833}
MODEL_GGUF=${MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
OUT_ROOT=${OUT_ROOT:-/private/tmp/ds4_cuda_moe_batch_ladder}
REMOTE_OUT_DIR=${REMOTE_OUT_DIR:-}
BATCHES=${BATCHES:-"16 64 128 256 512 1024"}
ITERS=${ITERS:-5}
LAYER=${LAYER:-1}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}

ts=$(date -u +%Y%m%dT%H%M%SZ)
LOCAL_OUT_DIR="$OUT_ROOT/$ts"
if [ "$REMOTE_OUT_DIR" = "" ]; then
	REMOTE_OUT_DIR="/tmp/ds4_cuda_moe_batch_ladder_$ts"
fi

mkdir -p "$LOCAL_OUT_DIR"

remote_q() {
	printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

echo "writing local artifacts to: $LOCAL_OUT_DIR"
echo "writing remote artifacts to: $HOST:$REMOTE_OUT_DIR"

ssh $SSH_OPTS "$HOST" "
	set -u
	mkdir -p $(remote_q "$REMOTE_OUT_DIR")
	cd $(remote_q "$DS4_DIR") || exit 2
	for b in $BATCHES; do
		echo \"moe batch=\$b\"
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			./ds4 -m $(remote_q "$MODEL_GGUF") \
			--cuda-moe-probe \
			--cuda-moe-layer $(remote_q "$LAYER") \
			--cuda-moe-tokens \"\$b\" \
			--cuda-moe-iters $(remote_q "$ITERS") \
			> $(remote_q "$REMOTE_OUT_DIR")/moe_\"\$b\".out \
			2> $(remote_q "$REMOTE_OUT_DIR")/moe_\"\$b\".err
		rc=\$?
		if [ \$rc -ne 0 ]; then
			echo \"moe batch=\$b rc=\$rc\" > $(remote_q "$REMOTE_OUT_DIR")/moe_\"\$b\".failed
		fi
	done
" >"$LOCAL_OUT_DIR/remote_stdout.txt" 2>"$LOCAL_OUT_DIR/remote_stderr.txt" || true

ssh $SSH_OPTS "$HOST" "tar -C /tmp -czf - $(remote_q "${REMOTE_OUT_DIR##*/}")" >"$LOCAL_OUT_DIR/remote_artifacts.tgz" 2>"$LOCAL_OUT_DIR/remote_artifacts.tgz.stderr" || true
if [ -s "$LOCAL_OUT_DIR/remote_artifacts.tgz" ]; then
	tar -xzf "$LOCAL_OUT_DIR/remote_artifacts.tgz" -C "$LOCAL_OUT_DIR" >/dev/null 2>&1 || true
fi

REMOTE_BASE=${REMOTE_OUT_DIR##*/}
REMOTE_LOCAL_DIR="$LOCAL_OUT_DIR/$REMOTE_BASE"
python3 "$(dirname "$0")/summarize_ds4_moe_batch_ladder.py" \
	--dir "$REMOTE_LOCAL_DIR" \
	--json-out "$LOCAL_OUT_DIR/summary.json" \
	--md-out "$LOCAL_OUT_DIR/summary.md" \
	>"$LOCAL_OUT_DIR/summary.stdout.json"

echo "summary: $LOCAL_OUT_DIR/summary.md"
cat "$LOCAL_OUT_DIR/summary.md"
