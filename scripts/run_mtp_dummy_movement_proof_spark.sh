#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: run_mtp_dummy_movement_proof_spark.sh [user@host]

Compile and run a Spark-side CUDA microbenchmark that mimics the data
movement of DS4 MTP without doing model math.

Defaults target Spark0 by IPv4 because mDNS has been unreliable:
  spark0@172.16.11.228

Environment:
  SSH_OPTS              ssh options
  OUT_ROOT              local artifact root
  REMOTE_DIR            remote build/run dir
  STEPS                 timed decode steps (default: 512)
  WARMUP                warmup steps (default: 32)
  DRAFT_LEN             dummy MTP draft depth (default: 2)
  VERIFY_ROWS           dummy verifier rows per step (default: DRAFT_LEN)
  N_EMBD                embedding width (default: 4096)
  N_HC                  hyper-connection rows (default: 4)
  N_VOCAB               vocab logits row width (default: 163840)
  RAW_CACHE_ROWS        dummy MTP raw-cache rows (default: 2048)
  RAW_ROW_BYTES         bytes touched per draft raw-cache row (default: 65536)
  RESIDENT_MIB          resident startup cache bytes, in MiB (default: 1024)
  HOST_ROUNDTRIP        copy verifier row ids D2H each step, 0|1 (default: 1)
  COLD_MIB_PER_STEP     if >0, run one cold-copy variant with this MiB/step
  RUN_COLD_VARIANT      run resident+cold64 variants when COLD_MIB_PER_STEP unset (default: 1)

Artifacts:
  $OUT_ROOT/<timestamp>/{report.md,resident.json,cold*.json,remote_*}

Examples:
  ./scripts/run_mtp_dummy_movement_proof_spark.sh
  STEPS=2048 RESIDENT_MIB=4096 ./scripts/run_mtp_dummy_movement_proof_spark.sh spark0@172.16.11.228
  COLD_MIB_PER_STEP=256 RUN_COLD_VARIANT=0 ./scripts/run_mtp_dummy_movement_proof_spark.sh
EOF
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

target="${1:-spark0@172.16.11.228}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
OUT_ROOT="${OUT_ROOT:-/private/tmp/ds4_mtp_dummy_movement_proof}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$OUT_ROOT/$ts"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_mtp_dummy_movement_${ts}_$$}"

STEPS="${STEPS:-512}"
WARMUP="${WARMUP:-32}"
DRAFT_LEN="${DRAFT_LEN:-2}"
VERIFY_ROWS="${VERIFY_ROWS:-$DRAFT_LEN}"
N_EMBD="${N_EMBD:-4096}"
N_HC="${N_HC:-4}"
N_VOCAB="${N_VOCAB:-163840}"
RAW_CACHE_ROWS="${RAW_CACHE_ROWS:-2048}"
RAW_ROW_BYTES="${RAW_ROW_BYTES:-65536}"
RESIDENT_MIB="${RESIDENT_MIB:-1024}"
HOST_ROUNDTRIP="${HOST_ROUNDTRIP:-1}"
RUN_COLD_VARIANT="${RUN_COLD_VARIANT:-1}"
COLD_MIB_PER_STEP="${COLD_MIB_PER_STEP:-}"

mkdir -p "$OUT_DIR"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
repo_rev="unknown"
if [ -e "$repo_root/.git" ]; then
	repo_rev="$(cd "$repo_root" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

REPORT_MD="$OUT_DIR/report.md"

{
	echo "# MTP Dummy Movement Proof (Spark)"
	echo
	echo "Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo
	echo "- repo commit: $repo_rev"
	echo "- target: $target"
	echo "- remote dir: $REMOTE_DIR"
	echo
	echo "## Purpose"
	echo
	echo "This benchmark isolates the MTP data plumbing from MTP math. It allocates"
	echo "dummy resident buffers for token embeddings, HC streams, MTP raw-cache rows,"
	echo "vocab logits, and verifier rows, then runs the same per-token movement cadence"
	echo "that a draft/verify loop needs."
	echo
	echo "The pass/fail question is not answer quality. It is whether the data path can"
	echo "move resident MTP buffers fast enough when model math is replaced with simple"
	echo "copy/touch kernels."
	echo
	echo "## Config"
	echo
	echo "- steps: $STEPS"
	echo "- warmup: $WARMUP"
	echo "- draft_len: $DRAFT_LEN"
	echo "- verify_rows: $VERIFY_ROWS"
	echo "- n_embd: $N_EMBD"
	echo "- n_hc: $N_HC"
	echo "- n_vocab: $N_VOCAB"
	echo "- raw_cache_rows: $RAW_CACHE_ROWS"
	echo "- raw_row_bytes: $RAW_ROW_BYTES"
	echo "- resident_mib: $RESIDENT_MIB"
	echo "- host_roundtrip: $HOST_ROUNDTRIP"
	echo "- run_cold_variant: $RUN_COLD_VARIANT"
	echo "- cold_mib_per_step: ${COLD_MIB_PER_STEP:-auto}"
	echo
	echo "## Spark Host"
	echo
	echo '```'
	ssh $SSH_OPTS "$target" 'set -eu; hostname; uname -a; nvidia-smi || true' || true
	echo '```'
	echo
} >"$REPORT_MD"

echo "writing report to: $OUT_DIR"
echo "== building remote dummy movement benchmark =="

ssh $SSH_OPTS "$target" "set -eu
rm -rf '$REMOTE_DIR'
mkdir -p '$REMOTE_DIR'
cat > '$REMOTE_DIR/mtp_dummy_movement.cu' <<'EOF_CU'
#include <cuda_runtime.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK_CUDA(expr) do { cudaError_t err__ = (expr); if ( err__ != cudaSuccess ) { fprintf(stderr,\"cuda error: %s:%d %s: %s\\n\",__FILE__,__LINE__,#expr,cudaGetErrorString(err__)); return(10); } } while (0)

typedef struct
{
	uint64_t steps;
	uint64_t warmup;
	uint64_t draft_len;
	uint64_t verify_rows;
	uint64_t n_embd;
	uint64_t n_hc;
	uint64_t n_vocab;
	uint64_t raw_cache_rows;
	uint64_t raw_row_bytes;
	uint64_t resident_bytes;
	uint64_t cold_bytes_per_step;
	int32_t host_roundtrip;
	int32_t json;
} cfg_t;

static uint64_t parse_u64(const char *s,uint64_t fallback)
{
	char *end;
	uint64_t v;
	if ( s == 0 || s[0] == 0 )
		return(fallback);
	end = 0;
	v = (uint64_t)strtoull(s,&end,10);
	if ( end == s )
		return(fallback);
	return(v);
}

static int32_t parse_args(cfg_t *cfg,int32_t argc,char **argv)
{
	int32_t i;
	for (i=1; i<argc; i++)
	{
		if ( strcmp(argv[i],"--steps") == 0 && i+1 < argc )
			cfg->steps = parse_u64(argv[++i],cfg->steps);
		else if ( strcmp(argv[i],"--warmup") == 0 && i+1 < argc )
			cfg->warmup = parse_u64(argv[++i],cfg->warmup);
		else if ( strcmp(argv[i],"--draft-len") == 0 && i+1 < argc )
			cfg->draft_len = parse_u64(argv[++i],cfg->draft_len);
		else if ( strcmp(argv[i],"--verify-rows") == 0 && i+1 < argc )
			cfg->verify_rows = parse_u64(argv[++i],cfg->verify_rows);
		else if ( strcmp(argv[i],"--n-embd") == 0 && i+1 < argc )
			cfg->n_embd = parse_u64(argv[++i],cfg->n_embd);
		else if ( strcmp(argv[i],"--n-hc") == 0 && i+1 < argc )
			cfg->n_hc = parse_u64(argv[++i],cfg->n_hc);
		else if ( strcmp(argv[i],"--n-vocab") == 0 && i+1 < argc )
			cfg->n_vocab = parse_u64(argv[++i],cfg->n_vocab);
		else if ( strcmp(argv[i],"--raw-cache-rows") == 0 && i+1 < argc )
			cfg->raw_cache_rows = parse_u64(argv[++i],cfg->raw_cache_rows);
		else if ( strcmp(argv[i],"--raw-row-bytes") == 0 && i+1 < argc )
			cfg->raw_row_bytes = parse_u64(argv[++i],cfg->raw_row_bytes);
		else if ( strcmp(argv[i],"--resident-bytes") == 0 && i+1 < argc )
			cfg->resident_bytes = parse_u64(argv[++i],cfg->resident_bytes);
		else if ( strcmp(argv[i],"--cold-bytes-per-step") == 0 && i+1 < argc )
			cfg->cold_bytes_per_step = parse_u64(argv[++i],cfg->cold_bytes_per_step);
		else if ( strcmp(argv[i],"--host-roundtrip") == 0 && i+1 < argc )
			cfg->host_roundtrip = (int32_t)parse_u64(argv[++i],(uint64_t)cfg->host_roundtrip);
		else if ( strcmp(argv[i],"--json") == 0 )
			cfg->json = 1;
		else
		{
			fprintf(stderr,\"unknown arg: %s\\n\",argv[i]);
			return(-1);
		}
	}
	return(0);
}

static __global__ void touch_bytes(uint8_t *buf,uint64_t bytes,uint32_t salt)
{
	uint64_t tid;
	uint64_t stride;
	uint64_t i;
	tid = ((uint64_t)blockIdx.x * (uint64_t)blockDim.x) + (uint64_t)threadIdx.x;
	stride = (uint64_t)blockDim.x * (uint64_t)gridDim.x;
	for (i=tid; i<bytes; i+=stride)
		buf[i] = (uint8_t)(buf[i] + (uint8_t)(salt + i));
}

static __global__ void mtp_dummy_step(float *tok,float *prev,float *state,float *next,float *inp,float *head,float *logits,uint8_t *raw,uint64_t raw_bytes,uint64_t raw_row_bytes,uint64_t n_embd,uint64_t n_hc,uint64_t n_vocab,uint64_t step,uint64_t draft_idx)
{
	uint64_t tid;
	uint64_t stride;
	uint64_t hc_elems;
	uint64_t maxn;
	uint64_t i;
	uint64_t raw_base;
	float v;
	tid = ((uint64_t)blockIdx.x * (uint64_t)blockDim.x) + (uint64_t)threadIdx.x;
	stride = (uint64_t)blockDim.x * (uint64_t)gridDim.x;
	hc_elems = (n_embd * n_hc);
	maxn = hc_elems;
	if ( n_vocab > maxn )
		maxn = n_vocab;
	if ( raw_row_bytes > maxn )
		maxn = raw_row_bytes;
	raw_base = ((step * 17ULL) + draft_idx) * raw_row_bytes;
	if ( raw_bytes > raw_row_bytes )
		raw_base %= (raw_bytes - raw_row_bytes);
	else
		raw_base = 0;
	for (i=tid; i<maxn; i+=stride)
	{
		if ( i < hc_elems )
		{
			v = prev[i] + tok[i % n_embd] + state[i];
			inp[i] = v;
			next[i] = v + 0.001f;
			state[i] = next[i];
		}
		if ( i < n_embd )
			head[i] = state[i] + tok[i];
		if ( i < n_vocab )
			logits[i] = logits[i] + (float)((i + step + draft_idx) & 255U) * 0.000001f;
		if ( i < raw_row_bytes )
			raw[raw_base + i] = (uint8_t)(raw[raw_base + i] ^ (uint8_t)(i + draft_idx + step));
	}
}

static __global__ void verify_dummy_step(float *verify_logits,int32_t *row_tops,uint64_t rows,uint64_t n_vocab,uint64_t step)
{
	uint64_t tid;
	uint64_t stride;
	uint64_t n;
	uint64_t i;
	tid = ((uint64_t)blockIdx.x * (uint64_t)blockDim.x) + (uint64_t)threadIdx.x;
	stride = (uint64_t)blockDim.x * (uint64_t)gridDim.x;
	n = rows * n_vocab;
	for (i=tid; i<n; i+=stride)
		verify_logits[i] = verify_logits[i] + (float)((i + step) & 127U) * 0.000002f;
	if ( tid < rows )
		row_tops[tid] = (int32_t)((step + tid) & 65535U);
}

static uint64_t mtp_bytes_per_draft(const cfg_t *cfg)
{
	uint64_t hc_elems;
	uint64_t bytes;
	hc_elems = cfg->n_embd * cfg->n_hc;
	bytes = 0;
	bytes += hc_elems * 24ULL;
	bytes += cfg->n_embd * 12ULL;
	bytes += cfg->n_vocab * 8ULL;
	bytes += cfg->raw_row_bytes * 2ULL;
	return(bytes);
}

static uint64_t verify_bytes_per_step(const cfg_t *cfg)
{
	return((cfg->verify_rows * cfg->n_vocab * 8ULL) + (cfg->verify_rows * 4ULL));
}

int main(int argc,char **argv)
{
	cfg_t cfg;
	cudaDeviceProp prop;
	uint64_t hc_elems;
	uint64_t raw_bytes;
	uint64_t verify_elems;
	uint64_t total_iters;
	uint64_t iter;
	uint64_t d;
	uint64_t resident_blocks;
	uint64_t resident_grid;
	uint64_t movement_bytes;
	uint64_t cold_total;
	uint8_t *resident;
	uint8_t *raw;
	uint8_t *cold_dev;
	uint8_t *cold_host;
	float *tok,*prev,*state,*next,*inp,*head,*logits,*verify_logits;
	int32_t *row_tops_dev,*row_tops_host;
	cudaStream_t stream;
	cudaEvent_t start,stop;
	float ms;
	float startup_ms;
	int32_t device;
	cfg.steps = 512;
	cfg.warmup = 32;
	cfg.draft_len = 2;
	cfg.verify_rows = 2;
	cfg.n_embd = 4096;
	cfg.n_hc = 4;
	cfg.n_vocab = 163840;
	cfg.raw_cache_rows = 2048;
	cfg.raw_row_bytes = 65536;
	cfg.resident_bytes = 1024ULL * 1024ULL * 1024ULL;
	cfg.cold_bytes_per_step = 0;
	cfg.host_roundtrip = 1;
	cfg.json = 0;
	if ( parse_args(&cfg,argc,argv) < 0 )
		return(2);
	if ( cfg.steps == 0 || cfg.n_embd == 0 || cfg.n_hc == 0 || cfg.n_vocab == 0 )
		return(3);
	CHECK_CUDA(cudaGetDevice(&device));
	CHECK_CUDA(cudaGetDeviceProperties(&prop,device));
	hc_elems = cfg.n_embd * cfg.n_hc;
	raw_bytes = cfg.raw_cache_rows * cfg.raw_row_bytes;
	verify_elems = cfg.verify_rows * cfg.n_vocab;
	resident = 0;
	raw = 0;
	cold_dev = 0;
	cold_host = 0;
	tok = prev = state = next = inp = head = logits = verify_logits = 0;
	row_tops_dev = 0;
	row_tops_host = 0;
	CHECK_CUDA(cudaStreamCreate(&stream));
	CHECK_CUDA(cudaEventCreate(&start));
	CHECK_CUDA(cudaEventCreate(&stop));
	CHECK_CUDA(cudaMalloc((void **)&tok,cfg.n_embd * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&prev,hc_elems * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&state,hc_elems * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&next,hc_elems * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&inp,hc_elems * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&head,cfg.n_embd * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&logits,cfg.n_vocab * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&verify_logits,verify_elems * sizeof(float)));
	CHECK_CUDA(cudaMalloc((void **)&raw,raw_bytes));
	CHECK_CUDA(cudaMalloc((void **)&row_tops_dev,cfg.verify_rows * sizeof(int32_t)));
	CHECK_CUDA(cudaMallocHost((void **)&row_tops_host,cfg.verify_rows * sizeof(int32_t)));
	CHECK_CUDA(cudaMemsetAsync(tok,1,cfg.n_embd * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(prev,2,hc_elems * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(state,3,hc_elems * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(next,4,hc_elems * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(inp,5,hc_elems * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(head,6,cfg.n_embd * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(logits,7,cfg.n_vocab * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(verify_logits,8,verify_elems * sizeof(float),stream));
	CHECK_CUDA(cudaMemsetAsync(raw,9,raw_bytes,stream));
	if ( cfg.resident_bytes != 0 )
	{
		CHECK_CUDA(cudaMalloc((void **)&resident,cfg.resident_bytes));
		CHECK_CUDA(cudaEventRecord(start,stream));
		resident_blocks = 256;
		resident_grid = (cfg.resident_bytes + 255ULL) / 256ULL;
		if ( resident_grid > 65535ULL )
			resident_grid = 65535ULL;
		touch_bytes<<<(uint32_t)resident_grid,256,0,stream>>>(resident,cfg.resident_bytes,17U);
		CHECK_CUDA(cudaEventRecord(stop,stream));
		CHECK_CUDA(cudaEventSynchronize(stop));
		CHECK_CUDA(cudaEventElapsedTime(&startup_ms,start,stop));
	}
	else
		startup_ms = 0.0f;
	if ( cfg.cold_bytes_per_step != 0 )
	{
		CHECK_CUDA(cudaMalloc((void **)&cold_dev,cfg.cold_bytes_per_step));
		CHECK_CUDA(cudaMallocHost((void **)&cold_host,cfg.cold_bytes_per_step));
		memset(cold_host,11,(size_t)cfg.cold_bytes_per_step);
	}
	CHECK_CUDA(cudaStreamSynchronize(stream));
	total_iters = cfg.warmup + cfg.steps;
	CHECK_CUDA(cudaEventRecord(start,stream));
	for (iter=0; iter<total_iters; iter++)
	{
		if ( iter == cfg.warmup )
		{
			CHECK_CUDA(cudaEventRecord(start,stream));
		}
		if ( cfg.cold_bytes_per_step != 0 )
			CHECK_CUDA(cudaMemcpyAsync(cold_dev,cold_host,(size_t)cfg.cold_bytes_per_step,cudaMemcpyHostToDevice,stream));
		for (d=0; d<cfg.draft_len; d++)
			mtp_dummy_step<<<256,256,0,stream>>>(tok,prev,state,next,inp,head,logits,raw,raw_bytes,cfg.raw_row_bytes,cfg.n_embd,cfg.n_hc,cfg.n_vocab,iter,d);
		if ( cfg.verify_rows != 0 )
			verify_dummy_step<<<256,256,0,stream>>>(verify_logits,row_tops_dev,cfg.verify_rows,cfg.n_vocab,iter);
		if ( cfg.host_roundtrip != 0 && cfg.verify_rows != 0 )
			CHECK_CUDA(cudaMemcpyAsync(row_tops_host,row_tops_dev,(size_t)(cfg.verify_rows * sizeof(int32_t)),cudaMemcpyDeviceToHost,stream));
	}
	CHECK_CUDA(cudaEventRecord(stop,stream));
	CHECK_CUDA(cudaEventSynchronize(stop));
	CHECK_CUDA(cudaEventElapsedTime(&ms,start,stop));
	CHECK_CUDA(cudaGetLastError());
	movement_bytes = cfg.steps * ((cfg.draft_len * mtp_bytes_per_draft(&cfg)) + verify_bytes_per_step(&cfg));
	cold_total = cfg.steps * cfg.cold_bytes_per_step;
	if ( cfg.json )
	{
		printf(\"{\\n\");
		printf(\"  \\\"ok\\\": true,\\n\");
		printf(\"  \\\"device\\\": \\\"%s\\\",\\n\",prop.name);
		printf(\"  \\\"steps\\\": %llu,\\n\",(unsigned long long)cfg.steps);
		printf(\"  \\\"warmup\\\": %llu,\\n\",(unsigned long long)cfg.warmup);
		printf(\"  \\\"draft_len\\\": %llu,\\n\",(unsigned long long)cfg.draft_len);
		printf(\"  \\\"verify_rows\\\": %llu,\\n\",(unsigned long long)cfg.verify_rows);
		printf(\"  \\\"n_embd\\\": %llu,\\n\",(unsigned long long)cfg.n_embd);
		printf(\"  \\\"n_hc\\\": %llu,\\n\",(unsigned long long)cfg.n_hc);
		printf(\"  \\\"n_vocab\\\": %llu,\\n\",(unsigned long long)cfg.n_vocab);
		printf(\"  \\\"raw_cache_rows\\\": %llu,\\n\",(unsigned long long)cfg.raw_cache_rows);
		printf(\"  \\\"raw_row_bytes\\\": %llu,\\n\",(unsigned long long)cfg.raw_row_bytes);
		printf(\"  \\\"resident_bytes\\\": %llu,\\n\",(unsigned long long)cfg.resident_bytes);
		printf(\"  \\\"cold_bytes_per_step\\\": %llu,\\n\",(unsigned long long)cfg.cold_bytes_per_step);
		printf(\"  \\\"host_roundtrip\\\": %d,\\n\",cfg.host_roundtrip);
		printf(\"  \\\"startup_ms\\\": %.6f,\\n\",(double)startup_ms);
		printf(\"  \\\"timed_ms\\\": %.6f,\\n\",(double)ms);
		printf(\"  \\\"steps_per_s\\\": %.6f,\\n\",((double)cfg.steps * 1000.0) / (double)ms);
		printf(\"  \\\"dummy_output_tokens_per_s_draft_len_plus_one\\\": %.6f,\\n\",((double)cfg.steps * (double)(cfg.draft_len + 1ULL) * 1000.0) / (double)ms);
		printf(\"  \\\"estimated_movement_bytes\\\": %llu,\\n\",(unsigned long long)movement_bytes);
		printf(\"  \\\"estimated_cold_copy_bytes\\\": %llu,\\n\",(unsigned long long)cold_total);
		printf(\"  \\\"estimated_total_bytes\\\": %llu,\\n\",(unsigned long long)(movement_bytes + cold_total));
		printf(\"  \\\"estimated_movement_gib_s\\\": %.6f\\n\",((double)(movement_bytes + cold_total) / 1073741824.0) / ((double)ms / 1000.0));
		printf(\"}\\n\");
	}
	else
	{
		printf(\"ok device=%s steps=%llu timed_ms=%.3f steps_per_s=%.3f movement_gib_s=%.3f\\n\",prop.name,(unsigned long long)cfg.steps,(double)ms,((double)cfg.steps * 1000.0) / (double)ms,((double)(movement_bytes + cold_total) / 1073741824.0) / ((double)ms / 1000.0));
	}
	CHECK_CUDA(cudaFreeHost(row_tops_host));
	if ( cold_host != 0 )
		CHECK_CUDA(cudaFreeHost(cold_host));
	if ( cold_dev != 0 )
		CHECK_CUDA(cudaFree(cold_dev));
	if ( resident != 0 )
		CHECK_CUDA(cudaFree(resident));
	CHECK_CUDA(cudaFree(row_tops_dev));
	CHECK_CUDA(cudaFree(raw));
	CHECK_CUDA(cudaFree(verify_logits));
	CHECK_CUDA(cudaFree(logits));
	CHECK_CUDA(cudaFree(head));
	CHECK_CUDA(cudaFree(inp));
	CHECK_CUDA(cudaFree(next));
	CHECK_CUDA(cudaFree(state));
	CHECK_CUDA(cudaFree(prev));
	CHECK_CUDA(cudaFree(tok));
	CHECK_CUDA(cudaEventDestroy(stop));
	CHECK_CUDA(cudaEventDestroy(start));
	CHECK_CUDA(cudaStreamDestroy(stream));
	return(0);
}
EOF_CU
NVCC=
if [ -x /usr/local/cuda/bin/nvcc ]; then
	NVCC=/usr/local/cuda/bin/nvcc
elif command -v nvcc >/dev/null 2>&1; then
	NVCC=nvcc
else
	echo 'nvcc not found' >&2
	exit 3
fi
\$NVCC -O3 --use_fast_math -std=c++17 -arch=sm_121 -o '$REMOTE_DIR/mtp_dummy_movement' '$REMOTE_DIR/mtp_dummy_movement.cu'
" >"$OUT_DIR/remote_build_stdout.txt" 2>"$OUT_DIR/remote_build_stderr.txt"

run_remote_variant()
{
	name="$1"
	cold_mib="$2"
	json_path="$OUT_DIR/$name.json"
	stdout_path="$OUT_DIR/remote_${name}_stdout.txt"
	stderr_path="$OUT_DIR/remote_${name}_stderr.txt"
	cold_bytes="$(awk -v m="$cold_mib" 'BEGIN{ printf "%.0f", m * 1048576.0 }')"
	ssh $SSH_OPTS "$target" "set -eu
'$REMOTE_DIR/mtp_dummy_movement' --json \
	--steps '$STEPS' \
	--warmup '$WARMUP' \
	--draft-len '$DRAFT_LEN' \
	--verify-rows '$VERIFY_ROWS' \
	--n-embd '$N_EMBD' \
	--n-hc '$N_HC' \
	--n-vocab '$N_VOCAB' \
	--raw-cache-rows '$RAW_CACHE_ROWS' \
	--raw-row-bytes '$RAW_ROW_BYTES' \
	--resident-bytes '$((RESIDENT_MIB * 1024 * 1024))' \
	--host-roundtrip '$HOST_ROUNDTRIP' \
	--cold-bytes-per-step '$cold_bytes'
" >"$stdout_path" 2>"$stderr_path" || true
	python3 - "$stdout_path" "$json_path" <<'PY' || true
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding="utf-8", errors="replace")
decoder = json.JSONDecoder()
best = None
for i, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        obj, end = decoder.raw_decode(text[i:])
    except json.JSONDecodeError:
        continue
    if isinstance(obj, dict) and "ok" in obj and "timed_ms" in obj:
        best = obj
if best is None:
    dst.write_text(json.dumps({"ok": False, "error": "missing json", "stdout": text[-4000:]}, indent=2) + "\n", encoding="utf-8")
else:
    dst.write_text(json.dumps(best, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

echo "== running resident movement variant =="
run_remote_variant resident 0

if [ "$COLD_MIB_PER_STEP" != "" ]; then
	echo "== running configured cold movement variant: ${COLD_MIB_PER_STEP} MiB/step =="
	run_remote_variant "cold${COLD_MIB_PER_STEP}mib" "$COLD_MIB_PER_STEP"
elif [ "$RUN_COLD_VARIANT" = "1" ]; then
	echo "== running cold movement variant: 64 MiB/step =="
	run_remote_variant cold64mib 64
fi

python3 - "$OUT_DIR" >>"$REPORT_MD" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
print("## Results")
print()
for p in sorted(out.glob("*.json")):
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"- {p.name}: parse failed: {exc}")
        continue
    if not obj.get("ok"):
        print(f"- {p.name}: failed: {obj.get('error', 'unknown')}")
        continue
    print(f"- {p.name}: steps/s={obj.get('steps_per_s'):.2f}, dummy output tok/s={obj.get('dummy_output_tokens_per_s_draft_len_plus_one'):.2f}, movement GiB/s={obj.get('estimated_movement_gib_s'):.2f}, startup_ms={obj.get('startup_ms'):.2f}, cold_bytes/step={obj.get('cold_bytes_per_step')}")
print()
print("Interpretation:")
print()
print("- `resident.json` is the proof target: it keeps MTP-like buffers resident and times only per-token movement.")
print("- `cold*.json` injects host-to-device copies per step. If it collapses, that mirrors the current MTP-ready lazy-cache symptom and tells us the slowdown is plumbing, not draft quality.")
PY

echo "== report =="
cat "$REPORT_MD"
