#!/usr/bin/env bash
set -euo pipefail

# Durable source runtime:
# https://github.com/experiencenow-ai/vllm
# 75358b5ef269050fbbf0d34a1e9772d8c56ac7c7

role="${1:-}"
if [ "$role" != "head" ] && [ "$role" != "worker" ]; then
	echo "usage: $0 head|worker" >&2
	exit 2
fi

if [ "$role" = "head" ]; then
	node_rank="${DS4_DSV4_NODE_RANK:-0}"
	local_ip="${DS4_DSV4_LOCAL_IP:-10.20.0.14}"
	extra_args=()
else
	node_rank="${DS4_DSV4_NODE_RANK:-1}"
	local_ip="${DS4_DSV4_LOCAL_IP:-10.20.0.15}"
	extra_args=(--headless)
fi

runtime="${DS4_DSV4_LOCAL_RUNTIME:-$HOME/ds4-vllm-local}"
model_path="${DS4_DSV4_MODEL_PATH:-/home/spark4/.cache/huggingface/hub/models--deepseek-ai--DeepSeek-V4-Flash/snapshots/6976c7ff1b30a1b2cb7805021b8ba4684041f136}"
port="${DS4_DSV4_PORT:-8000}"
master_addr="${DS4_DSV4_MASTER_ADDR:-10.20.0.14}"
master_port="${DS4_DSV4_MASTER_PORT:-29511}"
persistent_store="${DS4_DSV4_PERSIST_STORE:-/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload}"
kv_offload_size="${DS4_DSV4_KV_OFFLOAD_SIZE:-8}"
python_dev_include="${DS4_DSV4_PYTHON_DEV_INCLUDE:-$HOME/standard-runtimes/python3.12-dev-extract/usr/include}"

export PATH="$runtime/bin:/usr/local/cuda/bin:$PATH"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"
export CPATH="$python_dev_include:$python_dev_include/python3.12:${CPATH:-}"
export VLLM_HOST_IP="$local_ip"
export RAY_NODE_IP_ADDRESS="$local_ip"
export RAY_OVERRIDE_NODE_IP_ADDRESS="$local_ip"
export NCCL_DEBUG="${NCCL_DEBUG:-WARN}"
export NCCL_IGNORE_CPU_AFFINITY=1
export NCCL_IB_DISABLE=1
export NCCL_SOCKET_IFNAME="${DS4_DSV4_ETH_IF:-enP7s7}"
export GLOO_SOCKET_IFNAME="${DS4_DSV4_ETH_IF:-enP7s7}"
export TP_SOCKET_IFNAME="${DS4_DSV4_ETH_IF:-enP7s7}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export VLLM_USE_SIMPLE_KV_OFFLOAD="${VLLM_USE_SIMPLE_KV_OFFLOAD:-1}"
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT="$persistent_store"
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_STRICT="${VLLM_SIMPLE_KV_OFFLOAD_PERSIST_STRICT:-1}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-12.1a}"
export TRITON_PTXAS_PATH="${TRITON_PTXAS_PATH:-/usr/local/cuda/bin/ptxas}"

exec "$runtime/bin/python" "$runtime/bin/vllm" serve "$model_path" \
	--served-model-name deepseek-v4-flash \
	--host 0.0.0.0 \
	--port "$port" \
	--trust-remote-code \
	--tensor-parallel-size 2 \
	--pipeline-parallel-size 1 \
	--enable-expert-parallel \
	--kv-cache-dtype fp8 \
	--block-size 256 \
	--enable-prefix-caching \
	--max-model-len 1048576 \
	--max-num-seqs 2 \
	--max-num-batched-tokens 8192 \
	--gpu-memory-utilization 0.8 \
	--no-disable-hybrid-kv-cache-manager \
	--kv-offloading-size "$kv_offload_size" \
	--kv-offloading-backend native \
	--no-enable-flashinfer-autotune \
	--enforce-eager \
	--speculative-config '{"method":"deepseek_mtp","num_speculative_tokens":2}' \
	--tokenizer-mode deepseek_v4 \
	--tool-call-parser deepseek_v4 \
	--enable-auto-tool-choice \
	--reasoning-parser deepseek_v4 \
	--reasoning-config '{"reasoning_parser":"deepseek_v4","reasoning_start_str":"<think>","reasoning_end_str":"</think>"}' \
	--default-chat-template-kwargs '{"thinking":true}' \
	--load-format safetensors \
	--nnodes 2 \
	--node-rank "$node_rank" \
	--master-addr "$master_addr" \
	--master-port "$master_port" \
	"${extra_args[@]}"
