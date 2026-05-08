#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: spark_probe.sh [user@host]

Environment:
  SSH_OPTS   Extra ssh options (default includes BatchMode + temp known_hosts)
  REDACT=1   Redact IPv4/IPv6/MAC addresses from output

Examples:
  ./scripts/spark_probe.sh
  REDACT=1 ./scripts/spark_probe.sh | tee /private/tmp/spark0-probe.txt
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

target="${1:-spark0@aitopatom-9ab9.local}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts -o ServerAliveInterval=5 -o ServerAliveCountMax=2}"

tmp="$(mktemp /private/tmp/ds4_spark_probe.XXXXXX)"
trap 'rm -f "$tmp"' EXIT INT HUP TERM

{
	echo "== local meta =="
	date -u
	echo "probe target: $target"
	echo
	ssh $SSH_OPTS "$target" 'set -eu
export LANG=C LC_ALL=C
echo "== probe meta =="
date -u
echo "target user: $(id -un 2>/dev/null || true)"
echo
echo "== identity =="
hostname
id
uname -a
echo
echo "== os =="
if [ -r /etc/os-release ]; then
	cat /etc/os-release
fi
echo
echo "== cpu =="
lscpu || true
echo
echo "== memory =="
free -h || true
echo
echo "== toolchain =="
command -v gcc >/dev/null 2>&1 && gcc --version | head -n 1 || true
command -v g++ >/dev/null 2>&1 && g++ --version | head -n 1 || true
command -v clang >/dev/null 2>&1 && clang --version | head -n 1 || true
command -v cmake >/dev/null 2>&1 && cmake --version | head -n 1 || true
command -v ninja >/dev/null 2>&1 && ninja --version || true
command -v make >/dev/null 2>&1 && make --version | head -n 1 || true
command -v python3 >/dev/null 2>&1 && python3 --version || true
echo
echo "== pci nvidia =="
lspci | grep -i nvidia || true
echo
echo "== nvidia-smi summary =="
nvidia-smi || true
echo
echo "== nvidia-smi query (driver + compute capability) =="
nvidia-smi --query-gpu=gpu_name,driver_version,compute_cap,temperature.gpu,pstate,memory.total --format=csv,noheader,nounits 2>/dev/null || true
echo
echo "== nvidia-smi cuda version =="
nvidia-smi -q 2>/dev/null | grep -i "cuda version" | head -n 5 || true
echo
echo "== cuda toolkit =="
nvcc_bin=""
if command -v nvcc >/dev/null 2>&1; then
	nvcc_bin="$(command -v nvcc)"
elif [ -x /usr/local/cuda/bin/nvcc ]; then
	nvcc_bin="/usr/local/cuda/bin/nvcc"
fi
if [ "$nvcc_bin" != "" ]; then
	"$nvcc_bin" --version || true
	ls -l "$nvcc_bin" || true
else
	echo "nvcc not found"
fi
[ -e /usr/local/cuda/version.txt ] && cat /usr/local/cuda/version.txt || true
echo
echo "== cuda libraries (ldconfig, first hits) =="
ldconfig -p 2>/dev/null | grep -E "libcuda\\.so\\.1|libcudart\\.so" | head -n 20 || true
echo
echo "== cuda runtime probe (nvcc, no deps) =="
if [ "$nvcc_bin" != "" ]; then
	cu_src="/tmp/ds4_cuda_probe.$$.cu"
	cu_bin="/tmp/ds4_cuda_probe.$$"
	nvcc_log="/tmp/ds4_cuda_probe_nvcc.$$.log"
	cat >"$cu_src" <<'"'"'CU'"'"'
#include <cstdio>
#include <cuda_runtime.h>
int main()
{
	int device_count = 0,dev = 0;
	cudaDeviceProp prop;
	int runtime_v = 0,driver_v = 0;
	if ( cudaGetDeviceCount(&device_count) != cudaSuccess )
	{
		std::printf("cudaGetDeviceCount failed\n");
		return(1);
	}
	std::printf("cuda devices: %d\n",device_count);
	if ( device_count <= 0 )
		return(0);
	if ( cudaGetDeviceProperties(&prop,dev) != cudaSuccess )
	{
		std::printf("cudaGetDeviceProperties failed\n");
		return(2);
	}
	cudaRuntimeGetVersion(&runtime_v);
	cudaDriverGetVersion(&driver_v);
	std::printf("device0 name: %s\n",prop.name);
	std::printf("device0 cc: %d.%d\n",prop.major,prop.minor);
	std::printf("driver version: %d\n",driver_v);
	std::printf("runtime version: %d\n",runtime_v);
	std::printf("global mem (bytes): %llu\n",(unsigned long long)prop.totalGlobalMem);
	return(0);
}
CU
	if "$nvcc_bin" -O2 -lineinfo "$cu_src" -o "$cu_bin" >"$nvcc_log" 2>&1; then
		"$cu_bin" || true
	else
		echo "nvcc compile failed:"
		sed -n "1,80p" "$nvcc_log" 2>/dev/null || true
	fi
	rm -f "$cu_src" "$cu_bin" "$nvcc_log" >/dev/null 2>&1 || true
else
	echo "nvcc not found"
fi
echo
echo "== python cuda probe (optional) =="
command -v python3 >/dev/null 2>&1 && python3 - <<'"'"'PY'"'"' || true
try:
    import torch
    print("torch", torch.__version__)
    print("cuda available", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device", torch.cuda.get_device_name(0))
        print("capability", torch.cuda.get_device_capability(0))
except Exception as e:
    print("torch probe failed:", e)
PY
echo
echo "== network =="
ip -br -4 addr 2>/dev/null || ip -brief addr 2>/dev/null || ip addr || true
ip -4 route 2>/dev/null || ip route || true
echo
echo "== network links (no IPs) =="
ip -br link 2>/dev/null || true
if command -v ethtool >/dev/null 2>&1; then
	ifaces="$(ip -br link 2>/dev/null | awk '"'"'$1 != "lo" && ($2 == "UP" || $2 == "UNKNOWN") { print $1 }'"'"' | tr '"'"'\n'"'"' '"'"' '"'"' || true)"
	for iface in $ifaces; do
		echo "-- ethtool $iface --"
		ethtool "$iface" 2>/dev/null | grep -E "^(Settings for|\\s*Speed:|\\s*Duplex:|\\s*Auto-negotiation:|\\s*Link detected:)" || true
	done
fi
echo
echo "== storage =="
df -h / /home 2>/dev/null || df -h / || true
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS 2>/dev/null || true
echo
echo "== disks (summary) =="
lsblk -d -o NAME,SIZE,MODEL,ROTA,TYPE 2>/dev/null | head -n 20 || true
echo
echo "== nvidia driver (proc) =="
cat /proc/driver/nvidia/version 2>/dev/null | head -n 40 || true
'
} >"$tmp"

if [ "${REDACT:-0}" = "1" ]; then
	sed -E \
		-e 's/([0-9]{1,3}[.]){3}[0-9]{1,3}/<redacted-ipv4>/g' \
		-e 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/<redacted-mac>/g' \
		-e 's/([0-9A-Fa-f]{0,4}:){3,7}[0-9A-Fa-f]{0,4}/<redacted-ipv6>/g' \
		"$tmp"
else
	cat "$tmp"
fi
