#!/usr/bin/env bash
set -euo pipefail

MODEL="${QWEN27_NVFP4_MTP_MODEL:-/home/$USER/models/hf/sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP}"
API_PORT="${API_PORT:-8103}"
RUNTIME_PYTHON="${DS4_VLLM_PYTHON:-python3}"
SOURCE_ROOT="${DS4_VLLM_SOURCE_ROOT:-/home/$USER/src/vllm}"

export PYTHONPATH="$SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$(dirname "$RUNTIME_PYTHON"):$PATH"
export VLLM_NVFP4_GEMM_BACKEND="${VLLM_NVFP4_GEMM_BACKEND:-flashinfer-cutlass}"
export VLLM_USE_FLASHINFER_MOE_FP4="${VLLM_USE_FLASHINFER_MOE_FP4:-1}"
export VLLM_TEST_FORCE_FP8_MARLIN="${VLLM_TEST_FORCE_FP8_MARLIN:-0}"
export VLLM_MXFP4_USE_MARLIN="${VLLM_MXFP4_USE_MARLIN:-0}"
export VLLM_DISABLED_KERNELS="${VLLM_DISABLED_KERNELS:-MarlinNvFp4LinearKernel,EmulationNvFp4LinearKernel,MarlinMxFp4LinearKernel,MarlinMxfp8LinearKernel,EmulationMxfp8LinearKernel,MarlinFP8ScaledMMLinearKernel}"
export VLLM_DS4_STRICT_NATIVE_FP4="${VLLM_DS4_STRICT_NATIVE_FP4:-1}"

exec "$RUNTIME_PYTHON" -m vllm.entrypoints.cli.main serve "$MODEL" \
  --host "${API_HOST:-127.0.0.1}" \
  --port "$API_PORT" \
  --served-model-name "${QWEN27_NVFP4_SERVED_MODEL_NAME:-qwen27-nvfp4-native-mtp}" \
  --trust-remote-code \
  --quantization modelopt \
  --linear-backend "${QWEN27_LINEAR_BACKEND:-flashinfer-cutlass}" \
  --language-model-only \
  --max-model-len "${QWEN27_MAX_MODEL_LEN:-8192}" \
  --max-num-seqs "${QWEN27_MAX_NUM_SEQS:-4}" \
  --max-num-batched-tokens "${QWEN27_MAX_NUM_BATCHED_TOKENS:-8192}" \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization "${QWEN27_GPU_MEMORY_UTILIZATION:-0.72}" \
  --reasoning-parser qwen3 \
  --speculative-config "${QWEN27_SPECULATIVE_CONFIG:-{\"method\":\"qwen3_5_mtp\",\"num_speculative_tokens\":3}}"
