#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
with_device_props_minimal="${WITH_DEVICE_PROPS_MINIMAL:-1}"
with_device_props_sm121_run="${WITH_DEVICE_PROPS_SM121_RUN:-1}"
with_device_props_compute121_run="${WITH_DEVICE_PROPS_COMPUTE121_RUN:-1}"
with_device_props_gencode_run="${WITH_DEVICE_PROPS_GENCODE_RUN:-1}"
with_kernel_launch_minimal="${WITH_KERNEL_LAUNCH_MINIMAL:-1}"
with_kernel_tiny="${WITH_KERNEL_TINY:-1}"
with_cmake_minimal="${WITH_CMAKE_MINIMAL:-1}"
with_cublaslt_tiny="${WITH_CUBLASLT_TINY:-1}"
with_sm121_compile_report_tiny_minimal="${WITH_SM121_COMPILE_REPORT_TINY_MINIMAL:-1}"
log_path="${LOG_PATH:-}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"

log_line() {
	line="$*"
	printf "%s\n" "$line"
	if [ "$log_path" != "" ]; then
		printf "%s\n" "$line" >> "$log_path"
	fi
}

run_logged() {
	if [ "$log_path" = "" ]; then
		"$@"
		return
	fi
	tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_capability_out.XXXXXX")"
	set +e
	env LOG_PATH= "$@" >"$tmp_out" 2>&1
	rc=$?
	set -e
	cat "$tmp_out"
	cat "$tmp_out" >> "$log_path"
	rm -f "$tmp_out"
	return $rc
}

if [ "$log_path" != "" ]; then
	mkdir -p "$(dirname "$log_path")"
	printf "== cuda_probe_capability_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
fi

log_line "== cuda probe capability: nvcc minimal (no repo transfer) =="
run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_nvcc_minimal_${remote_tag}" "$repo_root/scripts/cuda_probe_nvcc_minimal_spark0.sh" "$target"

log_line "== cuda probe capability: sm_121 compile probes minimal (no repo transfer) =="
run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_sm121_compile_probes_minimal_${remote_tag}" "$repo_root/scripts/cuda_probe_sm121_compile_probes_minimal_spark0.sh" "$target"

if [ "${with_sm121_compile_report_tiny_minimal}" = "1" ]; then
	log_line "== cuda probe capability: sm_121 compile report tiny minimal (no repo transfer) =="
	run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_sm121_compile_report_tiny_minimal_${remote_tag}" "$repo_root/scripts/cuda_probe_sm121_compile_report_tiny_minimal_spark0.sh" "$target"
fi

if [ "${with_kernel_launch_minimal}" = "1" ]; then
	log_line "== cuda probe capability: kernel launch tiny minimal (no cudaMalloc; no repo transfer) =="
	run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_kernel_launch_tiny_minimal_${remote_tag}" "$repo_root/scripts/cuda_probe_kernel_launch_tiny_minimal_spark0.sh" "$target"
fi

if [ "${with_device_props_minimal}" = "1" ]; then
	log_line "== cuda probe capability: device props minimal (no repo transfer) =="
	run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_device_props_minimal_${remote_tag}" WITH_SM121_RUN="${with_device_props_sm121_run}" WITH_COMPUTE121_RUN="${with_device_props_compute121_run}" WITH_GENCODE_RUN="${with_device_props_gencode_run}" "$repo_root/scripts/cuda_probe_device_props_minimal_spark0.sh" "$target"
fi


if [ "${with_cmake_minimal}" = "1" ]; then
	log_line "== cuda probe capability: cmake minimal (no repo transfer) =="
	run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_cmake_minimal_${remote_tag}" "$repo_root/scripts/cuda_probe_cmake_minimal_spark0.sh" "$target"
fi

log_line "== cuda probe capability: tiny build+run =="
run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_tiny_${remote_tag}" "$repo_root/scripts/cuda_probe_tiny_spark0.sh" "$target"

log_line "== cuda probe capability: tiny compile-only (variants + PTX embed probes) =="
run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_compile_only_tiny_${remote_tag}" "$repo_root/scripts/cuda_probe_compile_only_tiny_spark0.sh" "$target"

if [ "${with_cublaslt_tiny}" = "1" ]; then
	log_line "== cuda probe capability: cublaslt-tiny gates (cuBLASLt matmul) =="
	run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_cublaslt_tiny_${remote_tag}" "$repo_root/scripts/cuda_probe_cublaslt_tiny_spark0.sh" "$target"
fi

if [ "${with_kernel_tiny}" = "1" ]; then
	log_line "== cuda probe capability: kernel-tiny gates (CUTLASS/DeepGEMM plumbing) =="
	run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_kernel_tiny_${remote_tag}" "$repo_root/scripts/cuda_probe_kernel_tiny_spark0.sh" "$target"
fi
