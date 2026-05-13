#!/usr/bin/env sh
set -eu

# Convenience wrapper for the "quantized single-Spark Spark0" milestone, but
# with a "smallest credible" GGUF selection policy:
# - Selects the smallest staged V4 Flash-family GGUF on Spark0 (by size),
#   after applying an optional include-regex to avoid ultra-low-bit artifacts.
# - Targets the pinned external llama.cpp runtime path if present.
# - Does not download weights or build runtimes; Spark-side gates still apply.
#
# Token generation remains opt-in: set ALLOW_RUN=1 to actually produce tokens.
#
# Usage:
#   ALLOW_RUN=1 scripts/run_quantized_single_spark0_smallest_credible_v4flash_external.sh spark0@aitopatom-9ab9.local

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

MODEL_GGUF_GLOB="${MODEL_GGUF_GLOB:-/home/spark0/models/ds4/*.gguf}"
MODEL_GGUF_EXCLUDE_EGREP="${MODEL_GGUF_EXCLUDE_EGREP:-MTP|DFlash|draft|sidecar}"
# Default include filter: prefer >=~2-bit quant families (avoid IQ1_* tiers).
MODEL_GGUF_INCLUDE_EGREP="${MODEL_GGUF_INCLUDE_EGREP:-IQ2|Q2_K|IQ3|Q3_K}"

MODEL_SOURCE="${MODEL_SOURCE:-staged:/home/spark0/models/ds4 (auto-select smallest trunk)}"
MODEL_QUANT="${MODEL_QUANT:-auto: smallest_by_size_bytes (exclude: $MODEL_GGUF_EXCLUDE_EGREP; include: $MODEL_GGUF_INCLUDE_EGREP)}"

LLAMA_CLI="${LLAMA_CLI:-/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli}"
LLAMA_DIR="${LLAMA_DIR:-/home/spark0/src/llama.cpp-kamnxt}"
RUNTIME_LABEL="${RUNTIME_LABEL:-v4flash-external}"

CTX="${CTX:-512}"
N_TOKENS="${N_TOKENS:-32}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"

RUN_LABEL="${RUN_LABEL:-quantized-single-spark0-smallest-credible}"
REQUIRE_GGUF_TRUNK_COMPLETE="${REQUIRE_GGUF_TRUNK_COMPLETE:-1}"
FETCH_LLAMA_OUT_DIR="${FETCH_LLAMA_OUT_DIR:-}"

if [ "${FETCH_LLAMA_OUT_DIR}" = "" ] && [ "${ALLOW_RUN:-0}" = "1" ]; then
	FETCH_LLAMA_OUT_DIR="1"
fi

quote_sh()
{
	v="${1:-}"
	printf "'%s'" "$(printf %s "$v" | sed "s/'/'\\\\\\\\''/g")"
}

if [ "${ALLOW_RUN:-0}" = "1" ]; then
	echo "== preflight (Spark0) =="
	ssh $SSH_OPTS "$target" "sh -lc 'set -eu; cli=\"\$1\"; dir=\"\$2\"; if [ ! -x \"\$cli\" ]; then echo \"error: LLAMA_CLI not executable: \$cli\" >&2; exit 2; fi; if [ ! -d \"\$dir\" ]; then echo \"error: LLAMA_DIR not a directory: \$dir\" >&2; exit 3; fi; echo \"ok: llama-cli=\$cli\"; echo \"ok: llama-dir=\$dir\"' sh $(quote_sh "$LLAMA_CLI") $(quote_sh "$LLAMA_DIR")"
	echo
fi

export MODEL_SOURCE MODEL_QUANT
export MODEL_GGUF_GLOB MODEL_GGUF_EXCLUDE_EGREP MODEL_GGUF_INCLUDE_EGREP
export LLAMA_CLI LLAMA_DIR RUNTIME_LABEL
export CTX N_TOKENS N_GPU_LAYERS
export RUN_LABEL REQUIRE_GGUF_TRUNK_COMPLETE
export FETCH_LLAMA_OUT_DIR

scripts/run_quantized_single_spark.sh "$target"

