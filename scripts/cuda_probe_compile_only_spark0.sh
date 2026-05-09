#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_compile_only}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
probe_dir="$repo_root/tools/cuda_probe"

if [ ! -d "$probe_dir" ]; then
	echo "missing $probe_dir" >&2
	exit 2
fi

ssh $SSH_OPTS "$target" "set -eu
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
"

env COPYFILE_DISABLE=1 tar -C "$probe_dir" -cf - . | ssh $SSH_OPTS "$target" "set -eu
tar -C \"$REMOTE_DIR\" -xf -
"

ssh $SSH_OPTS "$target" "set -eu
echo \"== nvcc ==\"
if [ -x /usr/local/cuda/bin/nvcc ]; then
	/usr/local/cuda/bin/nvcc --version
	echo
	echo \"== nvcc: --list-gpu-arch (if supported) ==\"
	/usr/local/cuda/bin/nvcc --list-gpu-arch 2>/dev/null || echo \"(nvcc --list-gpu-arch not supported)\"
	echo
	echo \"== nvcc: --list-gpu-code (if supported) ==\"
	/usr/local/cuda/bin/nvcc --list-gpu-code 2>/dev/null || echo \"(nvcc --list-gpu-code not supported)\"
elif command -v nvcc >/dev/null 2>&1; then
	nvcc --version
	echo
	echo \"== nvcc: --list-gpu-arch (if supported) ==\"
	nvcc --list-gpu-arch 2>/dev/null || echo \"(nvcc --list-gpu-arch not supported)\"
	echo
	echo \"== nvcc: --list-gpu-code (if supported) ==\"
	nvcc --list-gpu-code 2>/dev/null || echo \"(nvcc --list-gpu-code not supported)\"
else
	echo \"nvcc not found\" >&2
	exit 3
fi
	echo
	echo \"== compile-only sm_121 probes ==\"
	cd \"$REMOTE_DIR\"
	make clean
	make bin/cuda_sm121_compile_probe.o bin/cuda_sm121_probe bin/cuda_sm121_arch_report bin/cuda_cublaslt_smoke bin/cuda_cublaslt_fp8_smoke bin/cuda_sm121_smem_optin bin/cuda_sm121_devattrs bin/cuda_sm121_fp8_conv bin/cuda_sm121_pipeline_memcpy_async bin/cuda_sm120_compat_probe bin/cuda_sm121_barrier_memcpy_async bin/cuda_sm121_cccl_atomic_ref bin/cuda_sm121_wmma_smoke bin/cuda_sm121_cluster_launch bin/cuda_sm121_cxx20_probe
"
