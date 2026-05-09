#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/ds4_cuda_probe}"

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
elif command -v nvcc >/dev/null 2>&1; then
	nvcc --version
else
	echo \"nvcc not found\" >&2
	exit 3
fi
echo
echo \"== build ==\"
cd \"$REMOTE_DIR\"
make clean
make
echo
echo \"== run: cuda_device_props ==\"
\"$REMOTE_DIR\"/bin/cuda_device_props
echo
echo \"== run: cuda_sm121_probe ==\"
\"$REMOTE_DIR\"/bin/cuda_sm121_probe
echo
echo \"== run: cuda_sm121_arch_report ==\"
\"$REMOTE_DIR\"/bin/cuda_sm121_arch_report
echo
echo \"== run: cuda_cublaslt_smoke ==\"
\"$REMOTE_DIR\"/bin/cuda_cublaslt_smoke
echo
echo \"== run: cuda_sm121_smem_optin ==\"
\"$REMOTE_DIR\"/bin/cuda_sm121_smem_optin
echo
echo \"== run: cuda_sm121_devattrs ==\"
\"$REMOTE_DIR\"/bin/cuda_sm121_devattrs
"
