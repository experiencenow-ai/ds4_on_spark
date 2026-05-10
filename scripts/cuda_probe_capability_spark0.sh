#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

echo "== cuda probe capability: nvcc minimal (no repo transfer) =="
"$repo_root/scripts/cuda_probe_nvcc_minimal_spark0.sh" "$target"

echo "== cuda probe capability: tiny build+run =="
"$repo_root/scripts/cuda_probe_tiny_spark0.sh" "$target"

echo "== cuda probe capability: tiny compile-only (variants + PTX embed probes) =="
"$repo_root/scripts/cuda_probe_compile_only_tiny_spark0.sh" "$target"

