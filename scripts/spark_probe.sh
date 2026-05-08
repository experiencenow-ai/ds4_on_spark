#!/usr/bin/env sh
set -eu

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts}"

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    cat <<'EOF'
Usage:
  scripts/spark_probe.sh [user@host]

Notes:
  - Defaults to spark0@aitopatom-9ab9.local
  - Uses SSH_OPTS env var to override ssh options
  - Output is intended to be safe-to-commit (no MAC addresses, no host keys)
EOF
    exit 0
fi

ssh $SSH_OPTS "$target" 'set -eu
echo "== identity =="
hostname
id
echo "ssh target: '"$target"'"
uname -a
echo
echo "== os =="
if [ -r /etc/os-release ]; then
    cat /etc/os-release
fi
echo
echo "== toolchain =="
command -v gcc >/dev/null 2>&1 && gcc --version | head -n 2 || true
command -v g++ >/dev/null 2>&1 && g++ --version | head -n 2 || true
command -v clang >/dev/null 2>&1 && clang --version | head -n 2 || true
command -v make >/dev/null 2>&1 && make --version | head -n 2 || true
command -v cmake >/dev/null 2>&1 && cmake --version 2>/dev/null | head -n 1 || true
command -v ninja >/dev/null 2>&1 && ninja --version || true
command -v python3 >/dev/null 2>&1 && python3 --version || true
echo
echo "== cpu =="
lscpu || true
echo
echo "== memory =="
free -h || true
echo
echo "== pci nvidia =="
lspci | grep -i nvidia || true
echo
echo "== nvidia-smi =="
nvidia-smi || true
echo
echo "== nvidia-smi query =="
command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total,pstate,pci.bus_id --format=csv,noheader,nounits 2>/dev/null || true
echo
echo "== cuda =="
command -v nvcc >/dev/null 2>&1 && nvcc --version || true
[ -x /usr/local/cuda/bin/nvcc ] && /usr/local/cuda/bin/nvcc --version || true
if [ -r /usr/local/cuda/version.json ]; then
    echo "-- /usr/local/cuda/version.json --"
    cat /usr/local/cuda/version.json
fi
if [ -r /usr/local/cuda/version.txt ]; then
    echo "-- /usr/local/cuda/version.txt --"
    cat /usr/local/cuda/version.txt
fi
echo
echo "== cuda device props (nvcc) =="
NVCC=""
if command -v nvcc >/dev/null 2>&1; then
    NVCC="nvcc"
elif [ -x /usr/local/cuda/bin/nvcc ]; then
    NVCC="/usr/local/cuda/bin/nvcc"
fi
if [ "$NVCC" != "" ]; then
    tmpdir="/tmp/ds4_cuda_probe.$$"
    mkdir -p "$tmpdir"
    cat >"$tmpdir/ds4_cuda_props.cu" <<'"'"'CU'"'"'
#include <stdint.h>
#include <stdio.h>
#include <cuda_runtime.h>

static int32_t ds4_print(int32_t device)
{
	cudaDeviceProp p;
	cudaError_t e;
	e = cudaGetDeviceProperties(&p,device);
	if ( e != cudaSuccess )
	{
		fprintf(stderr,"cudaGetDeviceProperties failed: %s\n",cudaGetErrorString(e));
		return(-1);
	}
	printf("device=%d name=%s\n",device,p.name);
	printf("compute_capability=%d.%d\n",p.major,p.minor);
	printf("totalGlobalMem_bytes=%llu\n",(unsigned long long)p.totalGlobalMem);
	printf("multiProcessorCount=%d\n",p.multiProcessorCount);
	printf("warpSize=%d\n",p.warpSize);
	printf("maxThreadsPerBlock=%d\n",p.maxThreadsPerBlock);
	printf("memoryBusWidth_bits=%d\n",p.memoryBusWidth);
	printf("l2CacheSize_bytes=%d\n",p.l2CacheSize);
	printf("sharedMemPerBlock_bytes=%llu\n",(unsigned long long)p.sharedMemPerBlock);
	printf("regsPerBlock=%d\n",p.regsPerBlock);
	return(0);
}

int main(void)
{
	int32_t n = 0;
	cudaError_t e;
	e = cudaGetDeviceCount((int *)&n);
	if ( e != cudaSuccess )
	{
		fprintf(stderr,"cudaGetDeviceCount failed: %s\n",cudaGetErrorString(e));
		return(1);
	}
	printf("device_count=%d\n",(int)n);
	if ( n <= 0 )
		return(0);
	return((ds4_print(0) == 0) ? 0 : 2);
}
CU
    if "$NVCC" -O2 -std=c++17 -o "$tmpdir/ds4_cuda_props" "$tmpdir/ds4_cuda_props.cu" 2>"$tmpdir/nvcc.stderr"; then
        "$tmpdir/ds4_cuda_props" || true
    else
        echo "nvcc compile failed (showing last 200 lines):"
        tail -n 200 "$tmpdir/nvcc.stderr" || true
    fi
    rm -rf "$tmpdir" || true
else
    echo "nvcc not found"
fi
echo
echo "== network =="
ip -br -4 addr 2>/dev/null || true
ip -4 route 2>/dev/null || true
echo
echo "== storage =="
df -h / /home || true
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS || true
'
