#!/usr/bin/env sh
set -eu

target_note="spark inventory (models + runtimes; read-only)"

b64_dec()
{
    if [ "${1:-}" = "" ]; then
        return 0
    fi
    if command -v base64 >/dev/null 2>&1; then
        if printf %s "$1" | base64 -d >/dev/null 2>&1; then
            printf %s "$1" | base64 -d
            return 0
        fi
        if printf %s "$1" | base64 --decode >/dev/null 2>&1; then
            printf %s "$1" | base64 --decode
            return 0
        fi
    fi
    return 1
}

OUT_DIR="${OUT_DIR:-/tmp/baseline_spark_inventory}"
INVENTORY_DIRS="${INVENTORY_DIRS:-$HOME:/mnt:/data:/models:/opt:/srv}"
MAX_DEPTH="${MAX_DEPTH:-4}"
MAX_FILES="${MAX_FILES:-200}"

if [ "${INVENTORY_DIRS_B64:-}" != "" ]; then
    INVENTORY_DIRS="$(b64_dec "$INVENTORY_DIRS_B64" || echo "$INVENTORY_DIRS")"
fi

mkdir -p "$OUT_DIR"

echo "== $target_note =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo "cwd=$PWD"
echo "out_dir=$OUT_DIR"
echo "inventory_dirs=$INVENTORY_DIRS"
echo "max_depth=$MAX_DEPTH"
echo "max_files=$MAX_FILES"
echo

echo "== host probe =="
echo "hostname=$(hostname)"
echo "uname=$(uname -a)"
echo

echo "== disk =="
df -h / 2>/dev/null || true
echo

echo "== nvidia-smi =="
nvidia-smi -L 2>/dev/null || true
nvidia-smi 2>/dev/null || true
echo

echo "== runtimes: common paths =="
for p in \
    "$HOME/src/llama.cpp/build/bin/llama-cli" \
    "$HOME/src/llama.cpp/build/bin/main" \
    "/usr/local/bin/llama-cli" \
    "/usr/bin/llama-cli" \
    "/usr/local/bin/llama-server" \
    "/usr/bin/llama-server" \
    "/usr/local/bin/ds4" \
    "/usr/bin/ds4"; do
    if [ -x "$p" ]; then
        echo "found_exec=$p"
        ls -lh "$p" 2>/dev/null || true
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum "$p" 2>/dev/null || true
        elif command -v shasum >/dev/null 2>&1; then
            shasum -a 256 "$p" 2>/dev/null || true
        fi
        echo
    fi
done
if command -v llama-cli >/dev/null 2>&1; then
    p="$(command -v llama-cli || true)"
    if [ "$p" != "" ]; then
        echo "which_llama_cli=$p"
        ls -lh "$p" 2>/dev/null || true
        echo
    fi
fi
if command -v ds4 >/dev/null 2>&1; then
    p="$(command -v ds4 || true)"
    if [ "$p" != "" ]; then
        echo "which_ds4=$p"
        ls -lh "$p" 2>/dev/null || true
        echo
    fi
fi

echo "== models: candidate GGUFs (best-effort) =="
IFS=":"
set -- $INVENTORY_DIRS
unset IFS
for d in "$@"; do
    if [ "$d" = "" ]; then
        continue
    fi
    if [ ! -d "$d" ]; then
        continue
    fi
    echo "== scan_dir=$d =="
    find "$d" -maxdepth "$MAX_DEPTH" -type f -name '*.gguf' -print 2>/dev/null | head -n "$MAX_FILES" || true
    echo
done

echo "== models: HF cache hints (no deep scan) =="
if [ -d "$HOME/.cache/huggingface" ]; then
    echo "hf_cache_dir=$HOME/.cache/huggingface"
    (du -sh "$HOME/.cache/huggingface" 2>/dev/null || true) | head -n 5
    (ls -la "$HOME/.cache/huggingface" 2>/dev/null || true) | head -n 50
fi
echo

echo "== python + vLLM presence =="
command -v python3 2>/dev/null || true
python3 -V 2>/dev/null || true
python3 -m pip show vllm >"$OUT_DIR/pip_show_vllm.txt" 2>&1 || true
python3 -m pip show torch >"$OUT_DIR/pip_show_torch.txt" 2>&1 || true
echo "pip_show_vllm=$OUT_DIR/pip_show_vllm.txt"
echo "pip_show_torch=$OUT_DIR/pip_show_torch.txt"
