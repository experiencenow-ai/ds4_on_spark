#!/bin/sh
set -u

RUN_ID=${RUN_ID:-ds4-threeway-stage-$(date -u +%Y%m%dT%H%M%SZ)}
LOCAL_OUT_DIR=${LOCAL_OUT_DIR:-/private/tmp/$RUN_ID}
SPARK0_HOST=${SPARK0_HOST:-spark0@aitopatom-9ab9.local}
SPARK1_HOST=${SPARK1_HOST:-spark1@edgexpert-d623.local}
SPARK2_HOST=${SPARK2_HOST:-spark2@10.10.5.2}
SPARK2_PROXY_HOST=${SPARK2_PROXY_HOST:-spark1@edgexpert-d623.local}
SPARK0_DS4_DIR=${SPARK0_DS4_DIR:-/home/spark0/src/ds4}
SPARK1_DS4_DIR=${SPARK1_DS4_DIR:-/home/spark1/src/ds4}
SPARK2_DS4_DIR=${SPARK2_DS4_DIR:-/home/spark2/src/ds4}
SPARK0_MODEL_GGUF=${SPARK0_MODEL_GGUF:-/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
SPARK1_MODEL_GGUF=${SPARK1_MODEL_GGUF:-/home/spark1/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
SPARK2_MODEL_GGUF=${SPARK2_MODEL_GGUF:-/home/spark2/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf}
STAGE0_BEGIN=${STAGE0_BEGIN:-0}
STAGE0_END=${STAGE0_END:-15}
STAGE1_BEGIN=${STAGE1_BEGIN:-15}
STAGE1_END=${STAGE1_END:-29}
STAGE2_BEGIN=${STAGE2_BEGIN:-29}
STAGE2_END=${STAGE2_END:-43}
BATCH=${BATCH:-64}
ITERS=${ITERS:-1}
CTX=${CTX:-128}
PRELOAD_CHUNK_MB=${PRELOAD_CHUNK_MB:-64}
PRELOAD_SLEEP_US=${PRELOAD_SLEEP_US:-0}
SSH_KNOWN_HOSTS=${SSH_KNOWN_HOSTS:-/private/tmp/ds4_spark_known_hosts}
SSH_OPTS=${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SSH_KNOWN_HOSTS"}

remote_q() {
	printf "%s" "$1" | sed "s/'/'\\\\''/g; s/^/'/; s/$/'/"
}

stage_ssh() {
	stage=$1
	shift
	if [ "$stage" = "2" ] && [ -n "$SPARK2_PROXY_HOST" ]; then
		ssh $SSH_OPTS -o "ProxyCommand=ssh $SSH_OPTS $SPARK2_PROXY_HOST -W %h:%p" "$@"
	else
		ssh $SSH_OPTS "$@"
	fi
}

run_stage() {
	stage=$1
	host=$2
	ds4_dir=$3
	model=$4
	begin=$5
	end=$6
	include_head=$7
	no_head_env=
	if [ "$include_head" != "1" ]; then
		no_head_env="DS4_CUDA_STACK_PROBE_NO_HEAD=1"
	fi
	stage_ssh "$stage" "$host" "
		cd $(remote_q "$ds4_dir")
		env DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
			DS4_CUDA_STACK_PROBE_PRELOAD_STAGE=1 \
			DS4_CUDA_STACK_PROBE_PRELOAD_CHUNK_MB=$(remote_q "$PRELOAD_CHUNK_MB") \
			DS4_CUDA_STACK_PROBE_PRELOAD_SLEEP_US=$(remote_q "$PRELOAD_SLEEP_US") \
			DS4_CUDA_STACK_PROBE_LAYER_BEGIN=$(remote_q "$begin") \
			DS4_CUDA_STACK_PROBE_LAYER_END=$(remote_q "$end") \
			DS4_CUDA_STACK_PROBE_SPLIT_LAYERS=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
			DS4_CUDA_MOE_EXPERT_SLICE_STRICT=1 \
			$no_head_env \
			./ds4 -m $(remote_q "$model") \
			--cuda-batch-stack-probe \
			--cuda-moe-tokens $(remote_q "$BATCH") \
			--cuda-moe-iters $(remote_q "$ITERS") \
			--ctx $(remote_q "$CTX")
	" > "$LOCAL_OUT_DIR/stage${stage}.out" 2> "$LOCAL_OUT_DIR/stage${stage}.err" &
	echo $! > "$LOCAL_OUT_DIR/stage${stage}.pid"
}

wait_stage() {
	stage=$1
	pid=$(cat "$LOCAL_OUT_DIR/stage${stage}.pid")
	if wait "$pid"; then
		echo 0 > "$LOCAL_OUT_DIR/stage${stage}.rc"
	else
		echo $? > "$LOCAL_OUT_DIR/stage${stage}.rc"
	fi
}

mkdir -p "$LOCAL_OUT_DIR"
run_stage 0 "$SPARK0_HOST" "$SPARK0_DS4_DIR" "$SPARK0_MODEL_GGUF" "$STAGE0_BEGIN" "$STAGE0_END" 0
run_stage 1 "$SPARK1_HOST" "$SPARK1_DS4_DIR" "$SPARK1_MODEL_GGUF" "$STAGE1_BEGIN" "$STAGE1_END" 0
run_stage 2 "$SPARK2_HOST" "$SPARK2_DS4_DIR" "$SPARK2_MODEL_GGUF" "$STAGE2_BEGIN" "$STAGE2_END" 1
wait_stage 0
wait_stage 1
wait_stage 2

python3 - "$LOCAL_OUT_DIR" "$BATCH" "$STAGE0_BEGIN" "$STAGE0_END" "$STAGE1_BEGIN" "$STAGE1_END" "$STAGE2_BEGIN" "$STAGE2_END" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
batch = int(sys.argv[2])
stage_ranges = [
	[int(sys.argv[3]), int(sys.argv[4])],
	[int(sys.argv[5]), int(sys.argv[6])],
	[int(sys.argv[7]), int(sys.argv[8])],
]
rows = []
ok = True
for stage in range(3):
	rc = int((root / f"stage{stage}.rc").read_text(encoding="utf-8").strip())
	out_path = root / f"stage{stage}.out"
	err_path = root / f"stage{stage}.err"
	row = {"stage": stage, "rc": rc, "stdout": str(out_path), "stderr": str(err_path)}
	if rc == 0 and out_path.read_text(encoding="utf-8").strip():
		obj = json.loads(out_path.read_text(encoding="utf-8").splitlines()[-1])
		row.update(obj)
	else:
		ok = False
		row["error_tail"] = "\n".join(err_path.read_text(encoding="utf-8").splitlines()[-8:])
	rows.append(row)
success_rows = [r for r in rows if r.get("rc") == 0 and "best_ms" in r]
summary = {
	"format": "ds4-threeway-stage-split-v1",
	"batch": batch,
	"preload_policy": "explicit_stage_preload",
	"stage_count": 3,
	"stage_layer_ranges": stage_ranges,
	"all_stages_success": ok and len(success_rows) == 3,
	"stages": rows,
}
if len(success_rows) == 3:
	slowest = max(success_rows, key=lambda r: float(r["best_ms"]))
	summary["slowest_stage"] = slowest["stage"]
	summary["slowest_stage_ms"] = float(slowest["best_ms"])
	summary["pipeline_rows_per_s_bound"] = batch * 1000.0 / float(slowest["best_ms"])
(root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
raise SystemExit(0 if summary["all_stages_success"] else 1)
PY
