#!/bin/sh
set -eu

if [ $# -lt 1 ]; then
    echo "usage: $0 spark-host" >&2
    exit 1
fi

HOST=$1
DS4_DIR=${DS4_DIR:-/home/spark0/src/ds4}
MODEL_GGUF=${MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
PROMPT_FILE=${PROMPT_FILE:-bench/promessi_sposi.txt}
OUT_DIR=${OUT_DIR:-/tmp/ds4_moe_batch_sweep}
BATCHES=${BATCHES:-"16 32 64 100 128 256 512 1024 2048"}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}

remote_q() {
    printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

run_variant() {
    name=$1
    env_prefix=$2
    for b in $BATCHES; do
        echo "$name batch=$b"
        ssh $SSH_OPTS "$HOST" "
            set -eu
            mkdir -p $(remote_q "$OUT_DIR")
            cd $(remote_q "$DS4_DIR")
            $env_prefix DS4_CUDA_MOE_PROFILE=1 ./ds4-bench \
                -m $(remote_q "$MODEL_GGUF") \
                --chat-prompt-file $(remote_q "$PROMPT_FILE") \
                --cuda \
                --ctx-start $b \
                --ctx-max $b \
                --step-incr $b \
                --gen-tokens 1 \
                --csv $(remote_q "$OUT_DIR")/${name}_${b}.csv \
                > $(remote_q "$OUT_DIR")/${name}_${b}.out \
                2> $(remote_q "$OUT_DIR")/${name}_${b}.err
        "
    done
}

run_variant default ""
run_variant no_tiles "DS4_CUDA_MOE_NO_EXPERT_TILES=1"

echo "wrote sweep logs to $HOST:$OUT_DIR"
