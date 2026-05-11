#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
with_kernel_tiny="${WITH_KERNEL_TINY:-1}"
with_cmake_minimal="${WITH_CMAKE_MINIMAL:-1}"
log_path="${LOG_PATH:-}"

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
	"$@" >"$tmp_out" 2>&1
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
run_logged "$repo_root/scripts/cuda_probe_nvcc_minimal_spark0.sh" "$target"

if [ "${with_cmake_minimal}" = "1" ]; then
	log_line "== cuda probe capability: cmake minimal (no repo transfer) =="
	run_logged "$repo_root/scripts/cuda_probe_cmake_minimal_spark0.sh" "$target"
fi

log_line "== cuda probe capability: tiny build+run =="
run_logged "$repo_root/scripts/cuda_probe_tiny_spark0.sh" "$target"

log_line "== cuda probe capability: tiny compile-only (variants + PTX embed probes) =="
run_logged "$repo_root/scripts/cuda_probe_compile_only_tiny_spark0.sh" "$target"

if [ "${with_kernel_tiny}" = "1" ]; then
	log_line "== cuda probe capability: kernel-tiny gates (CUTLASS/DeepGEMM plumbing) =="
	run_logged "$repo_root/scripts/cuda_probe_kernel_tiny_spark0.sh" "$target"
fi
