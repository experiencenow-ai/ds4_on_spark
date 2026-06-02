#!/usr/bin/env bash
set -euo pipefail

# Host-local source runtime path for the DSV4 two-node lane.

role="${1:-}"
if [ "$role" != "head" ] && [ "$role" != "worker" ]; then
	echo "usage: $0 head|worker" >&2
	exit 2
fi

if [ "$role" = "head" ]; then
	node_rank="${DS4_DSV4_NODE_RANK:-0}"
	local_ip="${DS4_DSV4_LOCAL_IP:-${DS4_DSV4_HEAD_IP:-10.20.0.14}}"
	extra_args=()
else
	node_rank="${DS4_DSV4_NODE_RANK:-1}"
	local_ip="${DS4_DSV4_LOCAL_IP:-${DS4_DSV4_WORKER_IP:-10.20.0.15}}"
	extra_args=(--headless)
fi

runtime="${DS4_DSV4_LOCAL_RUNTIME:-$HOME/ds4-vllm-local}"
vllm_source="${DS4_DSV4_VLLM_SOURCE:-$HOME/src/vllm-c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34}"
model_path="${DS4_DSV4_MODEL_PATH:-$HOME/.cache/huggingface/hub/models--deepseek-ai--DeepSeek-V4-Flash/snapshots/6976c7ff1b30a1b2cb7805021b8ba4684041f136}"
port="${DS4_DSV4_PORT:-8000}"
master_addr="${DS4_DSV4_MASTER_ADDR:-${DS4_DSV4_HEAD_IP:-10.20.0.14}}"
master_port="${DS4_DSV4_MASTER_PORT:-29511}"
persistent_store="${DS4_DSV4_PERSIST_STORE:-/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload}"
repo_root="${DS4_DSV4_REPO_ROOT:-$HOME/ds4_on_spark}"
persistent_mod_source="${DS4_DSV4_PERSIST_MOD_SOURCE:-$repo_root/v2/runtime_mods/dsv4_persistent_simple_offload}"
apply_runtime_mods="${DS4_DSV4_APPLY_RUNTIME_MODS:-0}"
max_model_len="${DS4_DSV4_MAX_MODEL_LEN:-262144}"
kv_offload_size="${DS4_DSV4_KV_OFFLOAD_SIZE:-2}"
gpu_memory_utilization="${DS4_DSV4_GPU_MEMORY_UTILIZATION:-0.68}"
max_num_batched_tokens="${DS4_DSV4_MAX_NUM_BATCHED_TOKENS:-2048}"
max_num_seqs="${DS4_DSV4_MAX_NUM_SEQS:-1}"
enable_mtp="${DS4_DSV4_ENABLE_MTP:-1}"
mtp_tokens="${DS4_DSV4_MTP_TOKENS:-2}"
python_dev_include="${DS4_DSV4_PYTHON_DEV_INCLUDE:-$HOME/standard-runtimes/python3.12-dev-extract/usr/include}"
speculative_args=()
if [ "$enable_mtp" = "1" ]; then
	speculative_args=(--speculative-config "{\"method\":\"deepseek_mtp\",\"num_speculative_tokens\":$mtp_tokens}")
fi

export PATH="$runtime/bin:/usr/local/cuda/bin:$PATH"
if [ -f "$vllm_source/vllm/__init__.py" ]; then
	export PYTHONPATH="$vllm_source:${PYTHONPATH:-}"
fi
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
export PYTHONHASHSEED="${PYTHONHASHSEED:-${DS4_DSV4_PYTHONHASHSEED:-0}}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export VLLM_USE_SIMPLE_KV_OFFLOAD="${VLLM_USE_SIMPLE_KV_OFFLOAD:-1}"
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT="$persistent_store"
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_STRICT="${VLLM_SIMPLE_KV_OFFLOAD_PERSIST_STRICT:-${DS4_DSV4_PERSIST_STRICT:-1}}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-12.1a}"
export TRITON_PTXAS_PATH="${TRITON_PTXAS_PATH:-/usr/local/cuda/bin/ptxas}"

install_runtime_mod() {
	local label="$1"
	local source_dir="$2"
	if [ ! -f "$source_dir/patch_vllm.py" ]; then
		echo "[ds4-dsv4] missing $label runtime mod at $source_dir" >&2
		exit 1
	fi
	"$runtime/bin/python" "$source_dir/patch_vllm.py"
}

persistent_simple_offload_installed() {
	"$runtime/bin/python" - <<'PY'
from pathlib import Path
import sys
import vllm
base = Path(vllm.__file__).resolve().parent / "v1" / "simple_kv_offload"
checks = [
    (base / "persistent_disk.py").exists(),
    "load_block_hashes" in (base / "metadata.py").read_text(),
    "PersistentSimpleOffloadStore" in (base / "manager.py").read_text(),
    "persist_worker_blocks" in (base / "worker.py").read_text(),
]
raise SystemExit(0 if all(checks) else 1)
PY
}

if [ "$apply_runtime_mods" = "1" ]; then
	if persistent_simple_offload_installed; then
		echo "[ds4-dsv4] persistent SimpleCPUOffload already installed in local vLLM runtime"
	else
		install_runtime_mod "persistent SimpleCPUOffload" "$persistent_mod_source"
	fi
fi

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
	--max-model-len "$max_model_len" \
	--max-num-seqs "$max_num_seqs" \
	--max-num-batched-tokens "$max_num_batched_tokens" \
	--gpu-memory-utilization "$gpu_memory_utilization" \
	--no-disable-hybrid-kv-cache-manager \
	--kv-offloading-size "$kv_offload_size" \
	--kv-offloading-backend native \
	--kv-cache-metrics \
	--enable-logging-iteration-details \
	--distributed-executor-backend mp \
	--no-enable-flashinfer-autotune \
	--enforce-eager \
	"${speculative_args[@]}" \
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
