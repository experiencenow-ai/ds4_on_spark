#!/usr/bin/env sh
set -eu

target_note="llama.cpp Spark fork: MTP sidecar probe patch"

LLAMA_DIR="${LLAMA_DIR:-$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark}"
LLAMA_REPO="${LLAMA_REPO:-https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git}"
LLAMA_COMMIT="${LLAMA_COMMIT:-9222e55}"
PATCH_FILE="${PATCH_FILE:-$PWD/docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-sidecar-probe.patch}"

MTP_SIDECAR_GGUF="${MTP_SIDECAR_GGUF:-}"
PAYLOAD_SAMPLE_BYTES="${PAYLOAD_SAMPLE_BYTES:-0}"
LOAD_WEIGHTS="${LOAD_WEIGHTS:-0}"

ALLOW_FETCH="${ALLOW_FETCH:-0}"
ALLOW_PATCH="${ALLOW_PATCH:-0}"
ALLOW_BUILD="${ALLOW_BUILD:-0}"
ALLOW_RUN="${ALLOW_RUN:-0}"

echo "== $target_note =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo "cwd=$PWD"
echo "llama_dir=$LLAMA_DIR"
echo "llama_repo=$LLAMA_REPO"
echo "llama_commit=$LLAMA_COMMIT"
echo "patch_file=$PATCH_FILE"
echo "payload_sample_bytes=$PAYLOAD_SAMPLE_BYTES"
echo "load_weights=$LOAD_WEIGHTS"
echo

if [ ! -d "$LLAMA_DIR" ]; then
    echo "missing LLAMA_DIR=$LLAMA_DIR"
    if [ "$ALLOW_FETCH" = "1" ]; then
        mkdir -p "$(dirname "$LLAMA_DIR")"
        git clone "$LLAMA_REPO" "$LLAMA_DIR"
    else
        echo "set ALLOW_FETCH=1 to clone the llama.cpp fork"
        exit 2
    fi
fi

if [ ! -r "$PATCH_FILE" ]; then
    echo "PATCH_FILE not readable: $PATCH_FILE"
    exit 3
fi

echo "== llama.cpp revision (pre) =="
(cd "$LLAMA_DIR" && git rev-parse HEAD) || true

(cd "$LLAMA_DIR" && git fetch --all --tags)
(cd "$LLAMA_DIR" && git checkout "$LLAMA_COMMIT")

echo

echo "== patch =="
if [ "$ALLOW_PATCH" != "1" ]; then
    echo "patch skipped (set ALLOW_PATCH=1 to apply): $PATCH_FILE"
else
    (cd "$LLAMA_DIR" && git apply "$PATCH_FILE")
    echo "patch applied"
fi

echo

echo "== build =="
if [ "$ALLOW_BUILD" != "1" ]; then
    echo "build skipped (set ALLOW_BUILD=1 to compile llama-ds4-mtp-sidecar-probe)"
else
    (cd "$LLAMA_DIR" && cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release)
    (cd "$LLAMA_DIR" && cmake --build build --config Release --target llama-ds4-mtp-sidecar-probe -j)
fi

echo

echo "== run =="
if [ "$ALLOW_RUN" != "1" ]; then
    echo "run skipped (set ALLOW_RUN=1 and MTP_SIDECAR_GGUF=/abs/path/to/sidecar.gguf)"
    exit 0
fi

if [ "$MTP_SIDECAR_GGUF" = "" ]; then
    echo "MTP_SIDECAR_GGUF is required for ALLOW_RUN=1"
    exit 4
fi

if [ ! -r "$MTP_SIDECAR_GGUF" ]; then
    echo "MTP_SIDECAR_GGUF not readable: $MTP_SIDECAR_GGUF"
    exit 5
fi

PROBE_BIN="$LLAMA_DIR/build/bin/llama-ds4-mtp-sidecar-probe"
if [ ! -x "$PROBE_BIN" ]; then
    echo "probe binary not found: $PROBE_BIN"
    echo "set ALLOW_BUILD=1 to build it"
    exit 6
fi

PROBE_ARGS="--path \"$MTP_SIDECAR_GGUF\" --json"
if [ "$PAYLOAD_SAMPLE_BYTES" != "0" ]; then
    PROBE_ARGS="$PROBE_ARGS --payload-sample-bytes $PAYLOAD_SAMPLE_BYTES"
fi
if [ "$LOAD_WEIGHTS" = "1" ]; then
    PROBE_ARGS="$PROBE_ARGS --load-weights"
fi

sh -lc "\"$PROBE_BIN\" $PROBE_ARGS"
