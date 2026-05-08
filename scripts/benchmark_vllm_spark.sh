#!/usr/bin/env sh
set -eu

OUT_DIR="${OUT_DIR:-$PWD/baseline_vllm}"
mkdir -p "$OUT_DIR"

echo "== vLLM probe (Spark) =="
date -u +"utc=%Y-%m-%dT%H:%M:%SZ"
echo

echo "== python =="
command -v python3 || true
python3 -V || true
echo

echo "== vllm package =="
python3 -m pip show vllm >"$OUT_DIR/pip_show_vllm.txt" 2>&1 || true
cat "$OUT_DIR/pip_show_vllm.txt"
echo

echo "== torch package =="
python3 -m pip show torch >"$OUT_DIR/pip_show_torch.txt" 2>&1 || true
cat "$OUT_DIR/pip_show_torch.txt"
echo

echo "== cuda via torch =="
python3 - <<'PY' >"$OUT_DIR/torch_cuda_probe.txt" 2>&1 || true
try:
    import torch
    print("torch", torch.__version__)
    print("cuda available", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device", torch.cuda.get_device_name(0))
        print("capability", torch.cuda.get_device_capability(0))
except Exception as e:
    print("torch probe failed:", e)
PY
cat "$OUT_DIR/torch_cuda_probe.txt"

