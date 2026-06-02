#!/usr/bin/env bash
set -euo pipefail

: "${NODE_RANK:?set NODE_RANK to the local pipeline rank, starting at 0}"
: "${HEAD_ADDR:?set HEAD_ADDR to spark0 private IP or hostname}"

DS4_PIPELINE_NODES="${DS4_PIPELINE_NODES:-spark0,spark1,spark2,spark3,spark4,spark5,spark6,spark7}"
NODE_COUNT="$(python3 - "$DS4_PIPELINE_NODES" <<'PY'
import sys
print(len([x for x in sys.argv[1].split(',') if x.strip()]))
PY
)"
NNODES="${NNODES:-$NODE_COUNT}"
MASTER_PORT="${MASTER_PORT:-29544}"
API_PORT="${API_PORT:-8102}"
MODEL="${DSV4_FLASH_MODEL:-deepseek-ai/DeepSeek-V4-Flash}"
RUNTIME_PYTHON="${DS4_VLLM_PYTHON:-python3}"
SOURCE_ROOT="${DS4_VLLM_SOURCE_ROOT:-/home/$USER/src/vllm}"

if [[ -z "${DSV4_FLASH_PP_LAYER_PARTITION:-}" ]]; then
  if [[ "$NNODES" == "8" ]]; then
    DSV4_FLASH_PP_LAYER_PARTITION="6,6,6,5,5,5,5,5"
  else
    DSV4_FLASH_PP_LAYER_PARTITION="$(python3 - "$NNODES" <<'PY'
import sys
total = 43
stages = int(sys.argv[1])
if stages < 1 or stages > total:
    raise SystemExit(f"invalid pipeline stage count {stages} for {total} layers")
base, extra = divmod(total, stages)
print(','.join(str(base + (1 if i < extra else 0)) for i in range(stages)))
PY
)"
  fi
fi

export PYTHONPATH="$SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$(dirname "$RUNTIME_PYTHON"):$PATH"
VENV_SITE="$("$RUNTIME_PYTHON" -c 'import site; print(site.getsitepackages()[0])')"
PY_INCLUDE="$("$RUNTIME_PYTHON" -c 'import sysconfig; print(sysconfig.get_paths().get("include",""))')"
FALLBACK_PY_INCLUDE="${DS4_PYTHON_INCLUDE_DIR:-$HOME/ds4_deps/python3.12-dev/usr/include/python3.12}"
if [[ ! -r "$PY_INCLUDE/Python.h" && -r "$FALLBACK_PY_INCLUDE/Python.h" ]]; then
  FALLBACK_PY_INCLUDE_ROOT="$(dirname "$FALLBACK_PY_INCLUDE")"
  export CPATH="$FALLBACK_PY_INCLUDE:$FALLBACK_PY_INCLUDE_ROOT${CPATH:+:$CPATH}"
elif [[ ! -r "$PY_INCLUDE/Python.h" ]]; then
  echo "missing Python.h at $PY_INCLUDE/Python.h; install python3.12-dev or set DS4_PYTHON_INCLUDE_DIR" >&2
  exit 2
fi
if ! "$RUNTIME_PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  echo "missing pytest in $RUNTIME_PYTHON; install pytest for CuPy/Torch runtime inspection" >&2
  exit 2
fi
export LD_LIBRARY_PATH="${CUDA_LIB_DIR:-/usr/local/cuda/targets/sbsa-linux/lib}:${CUDA13_LIB_DIR:-/usr/local/cuda-13.0/targets/sbsa-linux/lib}:$VENV_SITE/nvidia/cu13/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
SPARK_ETH_IF="${DS4_SPARK_ETH_IF:-enP7s7}"
if command -v ip >/dev/null 2>&1; then
  LOCAL_HOST_IP="$(ip -o -4 addr show "$SPARK_ETH_IF" | awk '{print $4}' | cut -d/ -f1 | head -n 1)"
else
  LOCAL_HOST_IP=""
fi
if [[ -n "$LOCAL_HOST_IP" ]]; then
  export VLLM_HOST_IP="${VLLM_HOST_IP:-$LOCAL_HOST_IP}"
fi
export NCCL_IGNORE_CPU_AFFINITY="${NCCL_IGNORE_CPU_AFFINITY:-1}"
export NCCL_IB_DISABLE="${NCCL_IB_DISABLE:-1}"
export NCCL_SOCKET_IFNAME="${NCCL_SOCKET_IFNAME:-$SPARK_ETH_IF}"
export GLOO_SOCKET_IFNAME="${GLOO_SOCKET_IFNAME:-$SPARK_ETH_IF}"
export TP_SOCKET_IFNAME="${TP_SOCKET_IFNAME:-$SPARK_ETH_IF}"
export NCCL_DEBUG="${NCCL_DEBUG:-WARN}"
export VLLM_PP_LAYER_PARTITION="$DSV4_FLASH_PP_LAYER_PARTITION"
export VLLM_USE_SIMPLE_KV_OFFLOAD="${VLLM_USE_SIMPLE_KV_OFFLOAD:-1}"
export VLLM_ALLOW_LONG_MAX_MODEL_LEN="${VLLM_ALLOW_LONG_MAX_MODEL_LEN:-1}"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-12.1a}"
export VLLM_TRITON_MLA_SPARSE="${VLLM_TRITON_MLA_SPARSE:-1}"
export VLLM_MXFP4_USE_MARLIN="${VLLM_MXFP4_USE_MARLIN:-0}"
export VLLM_TEST_FORCE_FP8_MARLIN="${VLLM_TEST_FORCE_FP8_MARLIN:-0}"
export VLLM_DISABLED_KERNELS="${VLLM_DISABLED_KERNELS:-MarlinNvFp4LinearKernel,EmulationNvFp4LinearKernel,MarlinMxFp4LinearKernel,MarlinMxfp8LinearKernel,EmulationMxfp8LinearKernel,MarlinFP8ScaledMMLinearKernel}"
export VLLM_DS4_STRICT_NATIVE_FP4="${VLLM_DS4_STRICT_NATIVE_FP4:-1}"
export DS4_NODE_ID="${DS4_NODE_ID:-spark${NODE_RANK}}"
DS4_NVME_ROOT="${DS4_NVME_ROOT:-$HOME/ds4_nvme}"
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT="${VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT:-$DS4_NVME_ROOT/ds4_hma_store/dsv4_flash_pp8/simple_cpu_offload}/${DS4_NODE_ID}"
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_STRICT="${VLLM_SIMPLE_KV_OFFLOAD_PERSIST_STRICT:-1}"
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_RANK="${VLLM_SIMPLE_KV_OFFLOAD_PERSIST_RANK:-${DS4_NODE_ID}-dsv4-r${NODE_RANK}}"
mkdir -p "$VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT"

if [[ "${DSV4_SAFE_MODE:-0}" == "1" ]]; then
  DSV4_DEFAULT_MAX_NUM_SEQS=1
  DSV4_DEFAULT_MAX_NUM_BATCHED_TOKENS=2048
  DSV4_DEFAULT_GPU_MEMORY_UTILIZATION=0.68
else
  DSV4_DEFAULT_MAX_NUM_SEQS=8
  DSV4_DEFAULT_MAX_NUM_BATCHED_TOKENS=8192
  DSV4_DEFAULT_GPU_MEMORY_UTILIZATION=0.30
fi

COMMON_ARGS=(
  -m vllm.entrypoints.cli.main serve "$MODEL"
  --served-model-name "${DSV4_SERVED_MODEL_NAME:-deepseek-v4-flash-pp}"
  --trust-remote-code
  --tensor-parallel-size 1
  --distributed-executor-backend mp
  --pipeline-parallel-size "$NNODES"
  --nnodes "$NNODES"
  --node-rank "$NODE_RANK"
  --master-addr "$HEAD_ADDR"
  --master-port "$MASTER_PORT"
  --max-model-len "${DSV4_MAX_MODEL_LEN:-262144}"
  --max-num-seqs "${DSV4_MAX_NUM_SEQS:-$DSV4_DEFAULT_MAX_NUM_SEQS}"
  --max-num-batched-tokens "${DSV4_MAX_NUM_BATCHED_TOKENS:-$DSV4_DEFAULT_MAX_NUM_BATCHED_TOKENS}"
  --gpu-memory-utilization "${DSV4_GPU_MEMORY_UTILIZATION:-$DSV4_DEFAULT_GPU_MEMORY_UTILIZATION}"
  --block-size 256
  --kv-cache-dtype fp8
  --enable-prefix-caching
  --kv-offloading-size "${DSV4_KV_OFFLOADING_SIZE:-2}"
  --kv-offloading-backend native
  --linear-backend "${DSV4_LINEAR_BACKEND:-deep_gemm}"
  --moe-backend "${DSV4_MOE_BACKEND:-deep_gemm}"
  --kv-cache-metrics
  --enable-logging-iteration-details
  --speculative-config "${DSV4_SPECULATIVE_CONFIG:-{\"method\":\"deepseek_mtp\",\"num_speculative_tokens\":2}}"
  --no-disable-hybrid-kv-cache-manager
  --compilation-config "${DSV4_COMPILATION_CONFIG:-{\"cudagraph_mode\":\"FULL_AND_PIECEWISE\",\"custom_ops\":[\"all\"]}}"
  --tokenizer-mode deepseek_v4
  --tool-call-parser deepseek_v4
  --enable-auto-tool-choice
  --reasoning-parser deepseek_v4
  --reasoning-config "${DSV4_REASONING_CONFIG:-{\"reasoning_parser\":\"deepseek_v4\",\"reasoning_start_str\":\"<think>\",\"reasoning_end_str\":\"</think>\"}}"
  --default-chat-template-kwargs "${DSV4_DEFAULT_CHAT_TEMPLATE_KWARGS:-{\"thinking\":true}}"
  --load-format safetensors
)

if [[ "$NODE_RANK" == "0" ]]; then
  exec "$RUNTIME_PYTHON" "${COMMON_ARGS[@]}" --host "${API_HOST:-0.0.0.0}" --port "$API_PORT"
fi

exec "$RUNTIME_PYTHON" "${COMMON_ARGS[@]}" --headless
