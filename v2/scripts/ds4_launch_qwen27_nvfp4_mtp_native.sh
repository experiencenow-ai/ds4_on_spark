#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${DS4_VLLM_SOURCE_ROOT:-/home/$USER/src/vllm}"
export QWEN27_NVFP4_ENABLE_MTP="${QWEN27_NVFP4_ENABLE_MTP:-1}"
export QWEN27_NVFP4_ENABLE_MTP_EXPERIMENTAL="${QWEN27_NVFP4_ENABLE_MTP_EXPERIMENTAL:-1}"

exec "$SOURCE_ROOT/tools/ds4_launch_qwen27_nvfp4_pp8.sh"
