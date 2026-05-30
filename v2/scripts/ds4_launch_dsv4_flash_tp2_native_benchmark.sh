#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${DS4_VLLM_SOURCE_ROOT:-/home/$USER/src/vllm}"
exec "$SOURCE_ROOT/tools/ds4_launch_dsv4_flash_tp2_native_benchmark.sh"
