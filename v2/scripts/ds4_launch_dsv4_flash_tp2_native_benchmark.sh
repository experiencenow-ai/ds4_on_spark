#!/usr/bin/env bash
set -euo pipefail

: "${NODE_RANK:?set NODE_RANK to 0 on head, 1 on worker}"
: "${HEAD_ADDR:?set HEAD_ADDR to the rank-0 Spark private IP or hostname}"

MASTER_PORT="${MASTER_PORT:-29501}"
API_PORT="${API_PORT:-8000}"
MODEL="${DSV4_FLASH_MODEL:-deepseek-ai/DeepSeek-V4-Flash}"
RUNTIME_PYTHON="${DS4_VLLM_PYTHON:-python3}"
SOURCE_ROOT="${DS4_VLLM_SOURCE_ROOT:-/home/$USER/src/vllm}"

export PYTHONPATH="$SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$(dirname "$RUNTIME_PYTHON"):$PATH"
export VLLM_ALLOW_LONG_MAX_MODEL_LEN="${VLLM_ALLOW_LONG_MAX_MODEL_LEN:-1}"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-12.1a}"
export VLLM_TRITON_MLA_SPARSE="${VLLM_TRITON_MLA_SPARSE:-1}"
export VLLM_MXFP4_USE_MARLIN="${VLLM_MXFP4_USE_MARLIN:-0}"
export VLLM_TEST_FORCE_FP8_MARLIN="${VLLM_TEST_FORCE_FP8_MARLIN:-0}"
export VLLM_DISABLED_KERNELS="${VLLM_DISABLED_KERNELS:-MarlinNvFp4LinearKernel,EmulationNvFp4LinearKernel,MarlinMxFp4LinearKernel,MarlinMxfp8LinearKernel,EmulationMxfp8LinearKernel,MarlinFP8ScaledMMLinearKernel}"
export VLLM_DS4_STRICT_NATIVE_FP4="${VLLM_DS4_STRICT_NATIVE_FP4:-1}"

COMMON_ARGS=(
  -m vllm.entrypoints.cli.main serve "$MODEL"
  --served-model-name "${DSV4_SERVED_MODEL_NAME:-deepseek-v4-flash-tp2-native}"
  --trust-remote-code
  --tensor-parallel-size 2
  --enable-expert-parallel
  --distributed-executor-backend mp
  --nnodes 2
  --node-rank "$NODE_RANK"
  --master-addr "$HEAD_ADDR"
  --master-port "$MASTER_PORT"
  --max-model-len "${DSV4_MAX_MODEL_LEN:-200000}"
  --max-num-seqs "${DSV4_MAX_NUM_SEQS:-2}"
  --max-num-batched-tokens "${DSV4_MAX_NUM_BATCHED_TOKENS:-4096}"
  --gpu-memory-utilization "${DSV4_GPU_MEMORY_UTILIZATION:-0.85}"
  --linear-backend "${DSV4_LINEAR_BACKEND:-deep_gemm}"
  --moe-backend "${DSV4_MOE_BACKEND:-deep_gemm}"
  --block-size 256
  --kv-cache-dtype fp8
  --enable-prefix-caching
  --compilation-config "${DSV4_COMPILATION_CONFIG:-{\"cudagraph_mode\":\"FULL_AND_PIECEWISE\",\"custom_ops\":[\"all\"]}}"
  --speculative-config "${DSV4_SPECULATIVE_CONFIG:-{\"model\":\"$MODEL\",\"num_speculative_tokens\":2,\"method\":\"deepseek_mtp\"}}"
  --tokenizer-mode deepseek_v4
  --load-format safetensors
)

if [[ "$NODE_RANK" == "0" ]]; then
  exec "$RUNTIME_PYTHON" "${COMMON_ARGS[@]}" --host "${API_HOST:-0.0.0.0}" --port "$API_PORT"
fi

exec "$RUNTIME_PYTHON" "${COMMON_ARGS[@]}" --headless
