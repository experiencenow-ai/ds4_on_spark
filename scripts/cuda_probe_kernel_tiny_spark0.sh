#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_kernel_tiny}"
log_path="${LOG_PATH:-}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
probe_dir="$repo_root/tools/cuda_probe"
tar_no_mac_metadata=""
if tar --version 2>/dev/null | grep -qi "bsdtar"; then
	tar_no_mac_metadata="--no-mac-metadata"
fi

main() {
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

	echo \"== sm_121 variant build+run (fatbin probe, best-effort) ==\"
	try_variant_fatbin() {
		tag=\"\$1\"
		arch=\"\$2\"
		mode=\"\$3\"
		out_bin=\"$REMOTE_DIR\"/bin/\"\${tag}\"
		advertised=\"unknown\"
		if [ \"\${list_gpu_code}\" != \"\" ]; then
			if echo \"\${list_gpu_code}\" | grep -q \"\${arch}\"; then
				advertised=\"yes\"
			else
				advertised=\"no\"
			fi
		fi
		echo \"-- build: \${tag} (\${mode}=\${arch}; advertised=\${advertised})\"
		set +e
		if [ \"\${mode}\" = \"-arch\" ]; then
			\$NVCC -O2 -std=c++17 -arch=\"\${arch}\" -o \"\${out_bin}\" src/cuda_sm121_fatbin_probe.cu 2>\"$REMOTE_DIR\"/bin/\"\${tag}\".err
		else
			\$NVCC -O2 -std=c++17 --gpu-architecture=\"\${arch}\" -o \"\${out_bin}\" src/cuda_sm121_fatbin_probe.cu 2>\"$REMOTE_DIR\"/bin/\"\${tag}\".err
		fi
		rc=\$?
		set -e
		if [ \$rc -ne 0 ]; then
			echo \"\${tag}: BUILD FAILED rc=\$rc\" >&2
			head -n 60 \"$REMOTE_DIR\"/bin/\"\${tag}\".err || true
			return 0
		fi
		set +e
		run_retry \"\${tag}\" \"\${out_bin}\"
		rc_run=\$?
		set -e
		if [ \$rc_run -ne 0 ]; then
			echo \"(\${tag} run failed rc=\${rc_run}; continuing)\" >&2
		fi
	}

	try_variant_fatbin cuda_sm121a_fatbin_probe sm_121a -arch
	try_variant_fatbin cuda_sm121f_fatbin_probe sm_121f -arch
	try_variant_fatbin cuda_sm121a_gpuarch_fatbin_probe sm_121a --gpu-architecture
	try_variant_fatbin cuda_sm121f_gpuarch_fatbin_probe sm_121f --gpu-architecture
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_kernel_tiny_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_kernel_tiny_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc
