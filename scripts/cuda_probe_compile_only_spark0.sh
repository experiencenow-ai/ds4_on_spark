#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"
default_remote_dir="/tmp/ds4_cuda_probe_compile_only_${remote_tag}"
REMOTE_DIR="${REMOTE_DIR:-${default_remote_dir}}"
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
echo \"== nvcc ==\"
	if [ -x /usr/local/cuda/bin/nvcc ]; then
		/usr/local/cuda/bin/nvcc --version
		echo
		echo \"== nvcc: --list-gpu-arch (if supported) ==\"
		/usr/local/cuda/bin/nvcc --list-gpu-arch 2>/dev/null || echo \"(nvcc --list-gpu-arch not supported)\"
		list_gpu_arch=\$(/usr/local/cuda/bin/nvcc --list-gpu-arch 2>/dev/null || true)
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
		list_gpu_code=\$(/usr/local/cuda/bin/nvcc --list-gpu-code 2>/dev/null || true)
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
	elif command -v nvcc >/dev/null 2>&1; then
		nvcc --version
		echo
		echo \"== nvcc: --list-gpu-arch (if supported) ==\"
		nvcc --list-gpu-arch 2>/dev/null || echo \"(nvcc --list-gpu-arch not supported)\"
		list_gpu_arch=\$(nvcc --list-gpu-arch 2>/dev/null || true)
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
		list_gpu_code=\$(nvcc --list-gpu-code 2>/dev/null || true)
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
	else
		echo \"nvcc not found\" >&2
		exit 3
	fi
	echo
	echo \"== compile-only sm_121 probes ==\"
	cd \"$REMOTE_DIR\"
	make clean
	make bin/cuda_sm121_compile_probe.o bin/cuda_sm121_probe bin/cuda_sm121_rdc_probe bin/cuda_sm121_fatbin_probe bin/cuda_sm121_dlto_probe bin/cuda_sm121_arch_report bin/cuda_cublaslt_smoke bin/cuda_cublaslt_fp8_smoke bin/cuda_cublaslt_fp8_e5m2_smoke bin/cuda_cublaslt_fp8_e5m2_sweep bin/cuda_cublaslt_fp4_smoke bin/cuda_cublaslt_fp4_sweep bin/cuda_sm121_smem_optin bin/cuda_sm121_devattrs bin/cuda_sm121_fp8_conv bin/cuda_sm121_bf16_conv bin/cuda_sm121_fp4_conv bin/cuda_sm121_pipeline_memcpy_async bin/cuda_sm120_compat_probe bin/cuda_sm121_barrier_memcpy_async bin/cuda_sm121_cp_async_bulk_tx bin/cuda_sm121_tma_bulk_tensor_1d bin/cuda_sm121_tma_bulk_tensor_2d bin/cuda_sm121_cccl_atomic_ref bin/cuda_sm121_cuda_graph_smoke bin/cuda_sm121_cxx20_probe bin/cuda_sm121_nvcc_flags_probe bin/cuda_sm121_ldmatrix_smoke bin/cuda_sm121_wmma_smoke bin/cuda_sm121_cluster_launch bin/cuda_sm121_nvrtc_jit bin/cuda_sm121_nvrtc_cxx20_jit bin/cuda_sm121_nvjitlink_jit
	echo
	echo \"== nvcc: cluster_dims attribute compile (expected may fail on sm_121) ==\"
	set +e
	if [ -x /usr/local/cuda/bin/nvcc ]; then
		/usr/local/cuda/bin/nvcc -O2 -std=c++17 -arch=sm_121 -c -o bin/cuda_sm121_cluster_dims_attr_compile.o src/cuda_sm121_cluster_dims_attr_compile.cu 2>bin/cuda_sm121_cluster_dims_attr_compile.err
	else
		nvcc -O2 -std=c++17 -arch=sm_121 -c -o bin/cuda_sm121_cluster_dims_attr_compile.o src/cuda_sm121_cluster_dims_attr_compile.cu 2>bin/cuda_sm121_cluster_dims_attr_compile.err
	fi
	rc=\$?
	set -e
	if [ \$rc -eq 0 ]; then
		echo \"cluster_dims_attr_compile: OK\"
	else
		echo \"cluster_dims_attr_compile: FAILED rc=\$rc\"
		head -n 40 bin/cuda_sm121_cluster_dims_attr_compile.err || true
	fi
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_compile_only_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_compile_only_spark0_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc
