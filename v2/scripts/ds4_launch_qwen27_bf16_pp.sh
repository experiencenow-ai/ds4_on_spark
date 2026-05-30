#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${DS4_VLLM_SOURCE_ROOT:-/home/$USER/src/vllm}"
if [[ -z "${NNODES:-}" && -n "${DS4_PIPELINE_NODES:-}" ]]; then
  NNODES="$(python3 - "$DS4_PIPELINE_NODES" <<'PY'
import sys
print(len([item for item in sys.argv[1].split(",") if item.strip()]))
PY
)"
  export NNODES
fi

exec "$SOURCE_ROOT/tools/ds4_launch_qwen27_pp8.sh"
