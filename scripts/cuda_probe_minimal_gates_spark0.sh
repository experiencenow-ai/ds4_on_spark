#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
with_device_props_sm121_run="${WITH_DEVICE_PROPS_SM121_RUN:-1}"
with_device_props_compute121_run="${WITH_DEVICE_PROPS_COMPUTE121_RUN:-1}"
with_device_props_gencode_run="${WITH_DEVICE_PROPS_GENCODE_RUN:-1}"
with_kernel_tiny="${WITH_KERNEL_TINY:-0}"
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
	tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_minimal_gates_out.XXXXXX")"
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
	printf "== cuda_probe_minimal_gates_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
fi

log_line "== cuda probe minimal gates: nvcc minimal (no repo transfer) =="
run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_nvcc_minimal_${remote_tag}" "$repo_root/scripts/cuda_probe_nvcc_minimal_spark0.sh" "$target"

log_line "== cuda probe minimal gates: device props minimal (no repo transfer) =="
run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_device_props_minimal_${remote_tag}" WITH_SM121_RUN="${with_device_props_sm121_run}" WITH_COMPUTE121_RUN="${with_device_props_compute121_run}" WITH_GENCODE_RUN="${with_device_props_gencode_run}" "$repo_root/scripts/cuda_probe_device_props_minimal_spark0.sh" "$target"

log_line "== cuda probe minimal gates: sm121_gate (ships tools/cuda_probe) =="
run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_sm121_gate_${remote_tag}" "$repo_root/scripts/cuda_probe_sm121_gate_spark0.sh" "$target"

if [ "${with_kernel_tiny}" = "1" ]; then
	log_line "== cuda probe minimal gates: kernel-tiny (plumbing gates) =="
	run_logged env REMOTE_DIR="/tmp/ds4_cuda_probe_kernel_tiny_${remote_tag}" "$repo_root/scripts/cuda_probe_kernel_tiny_spark0.sh" "$target"
fi

