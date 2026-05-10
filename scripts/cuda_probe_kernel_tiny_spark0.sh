#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_kernel_tiny}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
probe_dir="$repo_root/tools/cuda_probe"
tar_no_mac_metadata=""
if tar --version 2>/dev/null | grep -qi "bsdtar"; then
	tar_no_mac_metadata="--no-mac-metadata"
fi

if [ ! -d "$probe_dir" ]; then
	echo "missing $probe_dir" >&2
	exit 2
fi

ssh $SSH_OPTS "$target" "set -eu
rm -rf \"$REMOTE_DIR\"
mkdir -p \"$REMOTE_DIR\"
"

LC_ALL=C env COPYFILE_DISABLE=1 tar --no-xattrs $tar_no_mac_metadata -C "$probe_dir" -cf - . | ssh $SSH_OPTS "$target" "set -eu
LC_ALL=C LANG=C tar -C \"$REMOTE_DIR\" -xf -
"

ssh $SSH_OPTS "$target" "set -eu
NVCC=\"\"
echo \"== nvcc ==\"
if [ -x /usr/local/cuda/bin/nvcc ]; then
	NVCC=\"/usr/local/cuda/bin/nvcc\"
elif command -v nvcc >/dev/null 2>&1; then
	NVCC=\"nvcc\"
else
	echo \"nvcc not found\" >&2
	exit 3
fi
	\$NVCC --version
	echo
	echo \"== nvcc: --list-gpu-arch (if supported) ==\"
	\$NVCC --list-gpu-arch 2>/dev/null || echo \"(nvcc --list-gpu-arch not supported)\"
	list_gpu_arch=\$(\$NVCC --list-gpu-arch 2>/dev/null || true)
	if [ \"\${list_gpu_arch}\" = \"\" ]; then
		:
	else
		if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
			:
		else
			echo \"(nvcc --list-gpu-arch missing compute_121)\" >&2
			exit 4
		fi
	fi
	echo
	echo \"== nvcc: --list-gpu-code (if supported) ==\"
	list_gpu_code=\$(\$NVCC --list-gpu-code 2>/dev/null || true)
	if [ \"\${list_gpu_code}\" = \"\" ]; then
		echo \"(nvcc --list-gpu-code not supported)\"
	else
		printf \"%s\n\" \"\${list_gpu_code}\"
		if echo \"\${list_gpu_code}\" | grep -q \"sm_121\"; then
			:
		else
			echo \"(nvcc --list-gpu-code missing sm_121)\" >&2
			exit 5
		fi
	fi

echo
	echo \"== build (kernel-tiny) ==\"
	cd \"$REMOTE_DIR\"
	make clean
	make kernel_tiny

echo
run_retry() {
	name=\"\$1\"
	shift
	echo \"== run: \${name} ==\"
	if \"\$@\"; then
		echo
		return 0
	else
		rc=\$?
		echo \"(\${name} failed rc=\${rc}; retrying once)\" >&2
		sleep 1
		\"\$@\"
		echo
	fi
}

	run_retry cuda_device_props_tiny \"$REMOTE_DIR\"/bin/cuda_device_props_tiny
	run_retry cuda_sm121_arch_report \"$REMOTE_DIR\"/bin/cuda_sm121_arch_report
	run_retry cuda_sm121_smem_optin \"$REMOTE_DIR\"/bin/cuda_sm121_smem_optin
	run_retry cuda_sm121_devattrs \"$REMOTE_DIR\"/bin/cuda_sm121_devattrs
	run_retry cuda_sm121_fp8_conv \"$REMOTE_DIR\"/bin/cuda_sm121_fp8_conv
	run_retry cuda_sm121_bf16_conv \"$REMOTE_DIR\"/bin/cuda_sm121_bf16_conv
	run_retry cuda_sm121_fp4_conv \"$REMOTE_DIR\"/bin/cuda_sm121_fp4_conv
	run_retry cuda_sm121_pipeline_memcpy_async \"$REMOTE_DIR\"/bin/cuda_sm121_pipeline_memcpy_async
	run_retry cuda_sm121_barrier_memcpy_async \"$REMOTE_DIR\"/bin/cuda_sm121_barrier_memcpy_async
	run_retry cuda_sm121_cp_async_bulk_tx \"$REMOTE_DIR\"/bin/cuda_sm121_cp_async_bulk_tx
	run_retry cuda_sm121_tma_bulk_tensor_1d \"$REMOTE_DIR\"/bin/cuda_sm121_tma_bulk_tensor_1d
	run_retry cuda_sm121_tma_bulk_tensor_2d \"$REMOTE_DIR\"/bin/cuda_sm121_tma_bulk_tensor_2d
	run_retry cuda_sm121_cccl_atomic_ref \"$REMOTE_DIR\"/bin/cuda_sm121_cccl_atomic_ref
	run_retry cuda_sm121_cuda_graph_smoke \"$REMOTE_DIR\"/bin/cuda_sm121_cuda_graph_smoke
	run_retry cuda_sm121_ldmatrix_smoke \"$REMOTE_DIR\"/bin/cuda_sm121_ldmatrix_smoke
	run_retry cuda_sm121_wmma_smoke \"$REMOTE_DIR\"/bin/cuda_sm121_wmma_smoke
	run_retry cuda_sm121_cxx20_probe \"$REMOTE_DIR\"/bin/cuda_sm121_cxx20_probe
	run_retry cuda_sm121_nvcc_flags_probe \"$REMOTE_DIR\"/bin/cuda_sm121_nvcc_flags_probe
	run_retry cuda_sm121_nvrtc_jit \"$REMOTE_DIR\"/bin/cuda_sm121_nvrtc_jit
	run_retry cuda_sm121_nvrtc_cxx20_jit \"$REMOTE_DIR\"/bin/cuda_sm121_nvrtc_cxx20_jit
	run_retry cuda_sm121_nvjitlink_jit \"$REMOTE_DIR\"/bin/cuda_sm121_nvjitlink_jit
	run_retry cuda_sm121_cluster_launch \"$REMOTE_DIR\"/bin/cuda_sm121_cluster_launch
"
