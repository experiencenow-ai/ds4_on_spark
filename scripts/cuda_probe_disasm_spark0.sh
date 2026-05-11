#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:-"-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=0 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe_disasm}"

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
echo \"== nvcc ==\"
if [ -x /usr/local/cuda/bin/nvcc ]; then
	/usr/local/cuda/bin/nvcc --version
elif command -v nvcc >/dev/null 2>&1; then
	nvcc --version
else
	echo \"nvcc not found\" >&2
	exit 3
fi
echo
echo \"== build (selected targets) ==\"
cd \"$REMOTE_DIR\"
make clean
make bin/cuda_sm121_probe bin/cuda_sm121_cp_async_bulk_tx bin/cuda_sm121_tma_bulk_tensor_2d bin/cuda_sm121_ldmatrix_smoke bin/cuda_sm121_wmma_smoke
echo
dump_sass() {
	name=\"\$1\"
	path=\"\$2\"
	echo \"== cuobjdump --dump-sass: \${name} ==\"
	if [ -x /usr/local/cuda/bin/cuobjdump ]; then
		/usr/local/cuda/bin/cuobjdump --dump-sass \"\$path\" 2>/dev/null | head -n 120 || true
	elif command -v cuobjdump >/dev/null 2>&1; then
		cuobjdump --dump-sass \"\$path\" 2>/dev/null | head -n 120 || true
	else
		echo \"(cuobjdump not found)\"
	fi
	echo
	echo \"== nvdisasm: \${name} ==\"
	if [ -x /usr/local/cuda/bin/nvdisasm ]; then
		/usr/local/cuda/bin/nvdisasm \"\$path\" 2>/dev/null | head -n 120 || true
	elif command -v nvdisasm >/dev/null 2>&1; then
		nvdisasm \"\$path\" 2>/dev/null | head -n 120 || true
	else
		echo \"(nvdisasm not found)\"
	fi
	echo
}

dump_sass cuda_sm121_probe \"$REMOTE_DIR\"/bin/cuda_sm121_probe
dump_sass cuda_sm121_cp_async_bulk_tx \"$REMOTE_DIR\"/bin/cuda_sm121_cp_async_bulk_tx
dump_sass cuda_sm121_tma_bulk_tensor_2d \"$REMOTE_DIR\"/bin/cuda_sm121_tma_bulk_tensor_2d
dump_sass cuda_sm121_ldmatrix_smoke \"$REMOTE_DIR\"/bin/cuda_sm121_ldmatrix_smoke
dump_sass cuda_sm121_wmma_smoke \"$REMOTE_DIR\"/bin/cuda_sm121_wmma_smoke
"
