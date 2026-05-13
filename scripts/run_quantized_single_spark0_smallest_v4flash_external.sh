#!/usr/bin/env sh
set -eu

# Convenience wrapper for the "quantized single-Spark Spark0" milestone:
# - Selects the smallest staged V4 Flash-family GGUF on Spark0 (by size).
# - Targets the pinned external llama.cpp runtime path if present.
# - Does not download weights or build runtimes; Spark-side gates still apply.
#
# Token generation remains opt-in: set ALLOW_RUN=1 to actually produce tokens.
#
# Usage:
#   ALLOW_RUN=1 scripts/run_quantized_single_spark0_smallest_v4flash_external.sh spark0@aitopatom-9ab9.local

target="${1:-spark0@aitopatom-9ab9.local}"

MODEL_GGUF_GLOB="${MODEL_GGUF_GLOB:-/home/spark0/models/ds4/*.gguf}"
MODEL_GGUF_EXCLUDE_EGREP="${MODEL_GGUF_EXCLUDE_EGREP:-MTP|DFlash|draft|sidecar}"
MODEL_GGUF_INCLUDE_EGREP="${MODEL_GGUF_INCLUDE_EGREP:-}"

MODEL_SOURCE="${MODEL_SOURCE:-staged:/home/spark0/models/ds4 (auto-select smallest trunk)}"
MODEL_QUANT="${MODEL_QUANT:-auto: smallest_by_size_bytes (exclude: $MODEL_GGUF_EXCLUDE_EGREP)}"

LLAMA_CLI="${LLAMA_CLI:-/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli}"
LLAMA_DIR="${LLAMA_DIR:-/home/spark0/src/llama.cpp-kamnxt}"
RUNTIME_LABEL="${RUNTIME_LABEL:-v4flash-external}"

CTX="${CTX:-512}"
N_TOKENS="${N_TOKENS:-32}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"

RUN_LABEL="${RUN_LABEL:-quantized-single-spark0-smallest}"
REQUIRE_GGUF_TRUNK_COMPLETE="${REQUIRE_GGUF_TRUNK_COMPLETE:-1}"

export MODEL_SOURCE MODEL_QUANT
export MODEL_GGUF_GLOB MODEL_GGUF_EXCLUDE_EGREP MODEL_GGUF_INCLUDE_EGREP
export LLAMA_CLI LLAMA_DIR RUNTIME_LABEL
export CTX N_TOKENS N_GPU_LAYERS
export RUN_LABEL REQUIRE_GGUF_TRUNK_COMPLETE

scripts/run_quantized_single_spark.sh "$target"

