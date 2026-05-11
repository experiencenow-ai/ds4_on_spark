#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
with_kernel_tiny="${WITH_KERNEL_TINY:-1}"
with_cmake_minimal="${WITH_CMAKE_MINIMAL:-1}"

echo "== cuda probe capability: nvcc minimal (no repo transfer) =="
"$repo_root/scripts/cuda_probe_nvcc_minimal_spark0.sh" "$target"

if [ "${with_cmake_minimal}" = "1" ]; then
	echo "== cuda probe capability: cmake minimal (no repo transfer) =="
	"$repo_root/scripts/cuda_probe_cmake_minimal_spark0.sh" "$target"
fi

echo "== cuda probe capability: tiny build+run =="
"$repo_root/scripts/cuda_probe_tiny_spark0.sh" "$target"

echo "== cuda probe capability: tiny compile-only (variants + PTX embed probes) =="
"$repo_root/scripts/cuda_probe_compile_only_tiny_spark0.sh" "$target"

if [ "${with_kernel_tiny}" = "1" ]; then
	echo "== cuda probe capability: kernel-tiny gates (CUTLASS/DeepGEMM plumbing) =="
	"$repo_root/scripts/cuda_probe_kernel_tiny_spark0.sh" "$target"
fi
