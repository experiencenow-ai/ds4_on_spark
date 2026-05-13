#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
remote_tag="${REMOTE_TAG:-"$(date -u +%Y%m%d-%H%M%S)-$$"}"
default_remote_dir="/tmp/ds4_cuda_probe_sm121_gate_${remote_tag}"
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
echo \"== nvcc: --list-gpu-arch / --list-gpu-code (best-effort) ==\"
list_gpu_arch=\$(\$NVCC --list-gpu-arch 2>/dev/null || true)
if [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported)\"
else
	printf \"%s\n\" \"\${list_gpu_arch}\"
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		:
	else
		echo \"(nvcc --list-gpu-arch missing compute_121)\" >&2
		exit 4
	fi
fi
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
echo \"== build (sm121_gate) ==\"
cd \"$REMOTE_DIR\"
make clean
make sm121_gate

echo
echo \"== nvcc: gencode sm_121+compute_121 compile (if compute_121 advertised) ==\"
if [ \"\${list_gpu_arch}\" = \"\" ]; then
	echo \"(nvcc --list-gpu-arch not supported; skipping)\"
else
	if echo \"\${list_gpu_arch}\" | grep -q \"compute_121\"; then
		mkdir -p bin
		set +e
		\$NVCC -O2 -std=c++17 -gencode \"arch=compute_121,code=[sm_121,compute_121]\" -c -o bin/cuda_sm121_gencode_sm_plus_ptx_compile_probe.o src/cuda_sm121_compile_probe.cu 2>bin/cuda_sm121_gencode_sm_plus_ptx_compile_probe.err
		rc=\$?
		set -e
		if [ \$rc -eq 0 ]; then
			echo \"gencode_sm_121_plus_compute_121_compile: OK\"
		else
			echo \"gencode_sm_121_plus_compute_121_compile: FAILED rc=\$rc\" >&2
			head -n 80 bin/cuda_sm121_gencode_sm_plus_ptx_compile_probe.err || true
			exit 6
		fi
	else
		echo \"(nvcc --list-gpu-arch missing compute_121; skipping)\" >&2
	fi
fi

echo
echo \"== nvidia-smi: memory (best-effort) ==\"
if command -v nvidia-smi >/dev/null 2>&1; then
	smi_out=\$(nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader,nounits 2>/dev/null || true)
	if [ \"\${smi_out}\" = \"\" ]; then
		echo \"(nvidia-smi query unavailable)\"
	else
		printf \"%s\\n\" \"\${smi_out}\"
		if printf \"%s\\n\" \"\${smi_out}\" | grep -qi \"N/A\"; then
			echo \"(nvidia-smi memory fields N/A on this host/driver)\"
		fi
	fi
else
	echo \"(nvidia-smi not found)\"
fi

	run_best_effort() {
		name=\"\$1\"
		shift
		echo \"== run: \${name} ==\"
	set +e
	out=\$(\"\$@\" 2>&1)
	rc=\$?
	set -e
	printf \"%s\\n\" \"\${out}\"
	if [ \"\${rc}\" -eq 0 ]; then
		echo
		return 0
	fi
		if printf \"%s\\n\" \"\${out}\" | grep -Eqi \"out of memory|busy or unavailable|device is busy\"; then
			echo \"(\${name} skipped: GPU OOM/busy rc=\${rc})\" >&2
			echo
			return 0
		fi
	echo \"(\${name} failed rc=\${rc})\" >&2
	echo
	return \"\${rc}\"
	}
	
	run_best_effort cuda_device_props_tiny \"$REMOTE_DIR\"/bin/cuda_device_props_tiny
	run_best_effort cuda_sm121_kernel_launch_tiny \"$REMOTE_DIR\"/bin/cuda_sm121_kernel_launch_tiny
	run_best_effort cuda_sm121_arch_report \"$REMOTE_DIR\"/bin/cuda_sm121_arch_report
	run_best_effort cuda_sm121_arch_list_report \"$REMOTE_DIR\"/bin/cuda_sm121_arch_list_report
	run_best_effort cuda_sm121_compile_report_tiny \"$REMOTE_DIR\"/bin/cuda_sm121_compile_report_tiny
	run_best_effort cuda_sm121a_arch_list_report \"$REMOTE_DIR\"/bin/cuda_sm121a_arch_list_report
	run_best_effort cuda_sm121f_arch_list_report \"$REMOTE_DIR\"/bin/cuda_sm121f_arch_list_report
"
}

if [ "$log_path" = "" ]; then
	main
	exit 0
fi

mkdir -p "$(dirname "$log_path")"
printf "== cuda_probe_sm121_gate_spark0 log: %s ==\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$log_path"
tmp_out="$(mktemp "/private/tmp/ds4_cuda_probe_sm121_gate_out.XXXXXX")"
set +e
main >"$tmp_out" 2>&1
rc=$?
set -e
cat "$tmp_out"
cat "$tmp_out" >> "$log_path"
rm -f "$tmp_out"
exit $rc
