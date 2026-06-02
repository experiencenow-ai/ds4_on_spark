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
MASTER_PORT="${MASTER_PORT:-29527}"
API_PORT="${API_PORT:-8101}"
MODEL="${QWEN27_BF16_MODEL:-/home/$USER/models/hf/Qwen/Qwen3.6-27B}"
RUNTIME_PYTHON="${DS4_VLLM_PYTHON:-python3}"
SOURCE_ROOT="${DS4_VLLM_SOURCE_ROOT:-/home/$USER/src/vllm}"

if [[ -z "${QWEN27_PP_LAYER_PARTITION:-}" ]]; then
  if [[ "$NNODES" == "8" ]]; then
    QWEN27_PP_LAYER_PARTITION="9,9,9,8,8,8,8,5"
  else
    QWEN27_PP_LAYER_PARTITION="$(python3 - "$NNODES" <<'PY'
import sys
total = 64
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
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
export VLLM_ALLOW_LONG_MAX_MODEL_LEN="${VLLM_ALLOW_LONG_MAX_MODEL_LEN:-1}"
export VLLM_PP_LAYER_PARTITION="$QWEN27_PP_LAYER_PARTITION"
export DS4_NODE_ID="${DS4_NODE_ID:-spark${NODE_RANK}}"
DS4_NVME_ROOT="${DS4_NVME_ROOT:-$HOME/ds4_nvme}"
export LMCACHE_ROOT="${LMCACHE_ROOT:-$DS4_NVME_ROOT/ds4_lmcache/qwen27_bf16_pp8}/${DS4_NODE_ID}"
export LMCACHE_CONFIG_FILE="${LMCACHE_CONFIG_FILE:-/tmp/lmcache_qwen27_bf16_pp8_${DS4_NODE_ID}.yaml}"
mkdir -p "$LMCACHE_ROOT"

cat > "$LMCACHE_CONFIG_FILE" <<YAML
chunk_size: ${LMCACHE_CHUNK_SIZE:-784}
local_cpu: true
max_local_cpu_size: ${LMCACHE_MAX_LOCAL_CPU_SIZE:-16.0}
local_disk: file://$LMCACHE_ROOT
max_local_disk_size: ${LMCACHE_MAX_LOCAL_DISK_SIZE:-2048.0}
YAML

KV_TRANSFER_CONFIG='{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both","kv_connector_extra_config":{"use_native":true,"lmcache_kv_cache_group_id":"auto","discard_partial_chunks":false}}'

COMMON_ARGS=(
  -m vllm.entrypoints.cli.main serve "$MODEL"
  --served-model-name "${QWEN27_SERVED_MODEL_NAME:-qwen27-bf16-pp}"
  --trust-remote-code
  --tensor-parallel-size 1
  --distributed-executor-backend mp
  --pipeline-parallel-size "$NNODES"
  --nnodes "$NNODES"
  --node-rank "$NODE_RANK"
  --master-addr "$HEAD_ADDR"
  --master-port "$MASTER_PORT"
  --max-model-len "${QWEN27_MAX_MODEL_LEN:-262144}"
  --max-num-seqs "${QWEN27_MAX_NUM_SEQS:-12}"
  --max-num-batched-tokens "${QWEN27_MAX_NUM_BATCHED_TOKENS:-65536}"
  --gpu-memory-utilization "${QWEN27_GPU_MEMORY_UTILIZATION:-0.35}"
  --dtype bfloat16
  --language-model-only
  --enable-chunked-prefill
  --enable-prefix-caching
  --async-scheduling
  --reasoning-parser qwen3
  --no-disable-hybrid-kv-cache-manager
  --mamba-cache-mode align
  --kv-transfer-config "$KV_TRANSFER_CONFIG"
)

if [[ "$NODE_RANK" == "0" ]]; then
  exec "$RUNTIME_PYTHON" "${COMMON_ARGS[@]}" --host "${API_HOST:-0.0.0.0}" --port "$API_PORT"
fi

exec "$RUNTIME_PYTHON" "${COMMON_ARGS[@]}" --headless
