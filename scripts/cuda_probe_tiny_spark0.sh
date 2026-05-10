#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_tiny}"

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

echo
echo \"== build (tiny) ==\"
cd \"$REMOTE_DIR\"
make clean
make bin/cuda_device_props_tiny bin/cuda_sm121_compile_probe.o bin/cuda_sm121_probe bin/cuda_sm121_arch_report

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
run_retry cuda_sm121_probe \"$REMOTE_DIR\"/bin/cuda_sm121_probe
run_retry cuda_sm121_arch_report \"$REMOTE_DIR\"/bin/cuda_sm121_arch_report
"
