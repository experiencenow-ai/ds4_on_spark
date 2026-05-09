#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: spark_probe.sh [user@host]

Environment:
  SSH_OPTS             Extra ssh options (default includes BatchMode + temp known_hosts)
  SPARK_KNOWN_HOSTS    SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR          Optional git dir override for printing `git: <hash>`
  REDACT=1             Redact IPv4/IPv6/MAC addresses from output
  NVIDIA_SMI_FULL=1    Include full `nvidia-smi` output (process list, timestamps)
  PYTORCH_PROBE=1      Attempt a python3 torch CUDA probe (optional)
  CUDA_RUNTIME_PROBE=0 Skip the tiny `nvcc` runtime probe compile/run
  NVCC_ARCH            Optional `nvcc -arch` override (e.g., sm_121); default derives from nvidia-smi compute_cap when available

Examples:
  ./scripts/spark_probe.sh
  REDACT=1 ./scripts/spark_probe.sh | tee /private/tmp/spark0-probe.txt
  REDACT=1 NVIDIA_SMI_FULL=1 ./scripts/spark_probe.sh
  SPARK_KNOWN_HOSTS_PER_HOST=1 REDACT=1 ./scripts/spark_probe.sh spark0@spark1.local
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

target="${1:-spark0@aitopatom-9ab9.local}"
SPARK_KNOWN_HOSTS_PER_HOST="${SPARK_KNOWN_HOSTS_PER_HOST:-0}"
if [ "${SPARK_KNOWN_HOSTS:-}" = "" ]; then
	if [ "$SPARK_KNOWN_HOSTS_PER_HOST" = "1" ]; then
		host="${target#*@}"
		safe_host="$(printf "%s" "$host" | sed -E 's/[^A-Za-z0-9_.-]/_/g')"
		SPARK_KNOWN_HOSTS="/private/tmp/ds4_spark_known_hosts.$safe_host"
	else
		SPARK_KNOWN_HOSTS="/private/tmp/ds4_spark_known_hosts"
	fi
fi
NVIDIA_SMI_FULL="${NVIDIA_SMI_FULL:-0}"
PYTORCH_PROBE="${PYTORCH_PROBE:-0}"
CUDA_RUNTIME_PROBE="${CUDA_RUNTIME_PROBE:-1}"
NVCC_ARCH="${NVCC_ARCH:-}"
if [ "$NVCC_ARCH" != "" ]; then
	case "$NVCC_ARCH" in
		sm_[0-9][0-9]*)
			;;
		*)
			echo "warning: ignoring invalid NVCC_ARCH (expected sm_<digits>): $NVCC_ARCH" >&2
			NVCC_ARCH=""
			;;
	esac
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$SPARK_KNOWN_HOSTS -o ServerAliveInterval=5 -o ServerAliveCountMax=2"
fi

tmp="$(mktemp /private/tmp/ds4_spark_probe.XXXXXX)"
trap 'rm -f "$tmp"' EXIT INT HUP TERM

{
	echo "== local meta =="
	date -u
	if command -v git >/dev/null 2>&1; then
		if [ "${DS4_GIT_DIR:-}" != "" ]; then
			echo "git: $(git --git-dir="$DS4_GIT_DIR" --work-tree="$PWD" rev-parse --short HEAD 2>/dev/null || true)"
		elif git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
			echo "git: $(git rev-parse --short HEAD 2>/dev/null || true)"
	fi
	fi
	echo "probe target: $target"
	if [ "$NVCC_ARCH" != "" ]; then
		echo "NVCC_ARCH: $NVCC_ARCH"
	fi
	echo
	ssh $SSH_OPTS "$target" 'set -eu
export LANG=C LC_ALL=C
export TERM=dumb
nvidia_smi_full='"$NVIDIA_SMI_FULL"'
pytorch_probe='"$PYTORCH_PROBE"'
cuda_runtime_probe='"$CUDA_RUNTIME_PROBE"'
nvcc_arch_override='"$NVCC_ARCH"'
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
echo "== nvidia-smi inventory (index + pci bus) =="
if command -v nvidia-smi >/dev/null 2>&1; then
	q=""
	q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
	if [ "$q" != "" ]; then
		echo "$q"
	else
		q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,temperature.gpu,pstate,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
		[ "$q" != "" ] && echo "$q"
		echo "note: nvidia-smi compute_cap field not supported; rely on nvcc runtime probe for cc"
	fi
else
	echo "nvidia-smi not found"
fi
compute_cap=""
if [ "$q" != "" ]; then
	compute_cap="$(printf "%s\n" "$q" | awk -F"," "{ c=\$5; gsub(/^[ \\t]+|[ \\t]+$/, \"\", c); if ( c ~ /^[0-9]+[.][0-9]+$/ ) { split(c,a,\".\"); v=(a[1]*100)+a[2]; if ( v > best ) { best=v; bestc=c; } } } END { if ( bestc != \"\" ) print bestc; }")"
fi
nvcc_arch=""
if [ "$nvcc_arch_override" != "" ]; then
	nvcc_arch="$nvcc_arch_override"
elif [ "$compute_cap" != "" ]; then
	nvcc_arch="sm_$(printf "%s" "$compute_cap" | sed -E "s/[^0-9.]//g; s/[.]//g")"
fi
if [ "$compute_cap" != "" ]; then
	echo "selected compute_cap: $compute_cap"
fi
echo
echo "== nvidia-smi pcie link state =="
if command -v nvidia-smi >/dev/null 2>&1; then
	nvidia-smi --query-gpu=index,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current --format=csv,noheader,nounits 2>/dev/null || echo "pcie link query not supported"
else
	echo "nvidia-smi not found"
fi
echo
echo "== nvidia-smi cuda version =="
nvidia-smi -q 2>/dev/null | grep -i "cuda version" | head -n 5 || true
echo
echo "== nvidia-smi gpu list =="
if command -v nvidia-smi >/dev/null 2>&1; then
	nvidia-smi -L 2>/dev/null || true
else
	echo "nvidia-smi not found"
fi
echo
echo "== nvidia-smi topo (capped) =="
if command -v nvidia-smi >/dev/null 2>&1; then
	nvidia-smi topo -m 2>/dev/null | sed -E "s/\\x1B\\[[0-9;]*[[:alpha:]]//g" | head -n 120 || true
else
	echo "nvidia-smi not found"
fi
echo
if [ "$nvidia_smi_full" = "1" ]; then
	echo "== nvidia-smi full (verbose) =="
	nvidia-smi || true
	echo
fi
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
ptxas_bin=""
if [ -x /usr/local/cuda/bin/ptxas ]; then
	ptxas_bin="/usr/local/cuda/bin/ptxas"
elif command -v ptxas >/dev/null 2>&1; then
	ptxas_bin="$(command -v ptxas)"
fi
if [ "$ptxas_bin" != "" ]; then
	echo "ptxas: $ptxas_bin"
	"$ptxas_bin" --version 2>/dev/null | head -n 3 || true
fi
[ -e /usr/local/cuda ] && ls -ld /usr/local/cuda || true
command -v readlink >/dev/null 2>&1 && readlink -f /usr/local/cuda 2>/dev/null || true
[ -e /usr/local/cuda/version.txt ] && cat /usr/local/cuda/version.txt || true
echo
echo "== cuda headers (cuda.h) =="
cuda_h="/usr/local/cuda/include/cuda.h"
cuda_macro=""
if [ -r "$cuda_h" ]; then
	echo "$cuda_h"
	grep -E "^#define (CUDA_VERSION|CUDART_VERSION) " "$cuda_h" 2>/dev/null || true
	cuda_macro="$(grep -E "^#define CUDA_VERSION " "$cuda_h" 2>/dev/null | awk "{ print \$3 }" | head -n 1 || true)"
	case "$cuda_macro" in
		""|*[!0-9]*)
			cuda_macro=""
			;;
		*)
			;;
	esac
else
	echo "cuda.h not found"
fi
echo
echo "== cuda toolkit cross-check =="
nvcc_release=""
if [ "$nvcc_bin" != "" ]; then
	nvcc_release="$("$nvcc_bin" --version 2>/dev/null | sed -n "s/.*release \\([0-9][0-9]*\\)\\.\\([0-9][0-9]*\\).*/\\1 \\2/p" | head -n 1 || true)"
fi
if [ "$nvcc_release" != "" ] && [ "$cuda_macro" != "" ]; then
	set -- $nvcc_release
	nvcc_rel_maj="$1"
	nvcc_rel_min="$2"
	cuda_maj="$((cuda_macro / 1000))"
	cuda_min="$(((cuda_macro % 1000) / 10))"
	echo "nvcc release: $nvcc_rel_maj.$nvcc_rel_min"
	echo "cuda.h CUDA_VERSION: $cuda_maj.$cuda_min ($cuda_macro)"
	if [ "$nvcc_rel_maj" != "$cuda_maj" ] || [ "$nvcc_rel_min" != "$cuda_min" ]; then
		echo "warning: nvcc release and cuda.h CUDA_VERSION differ; check /usr/local/cuda symlink"
	fi
elif [ "$nvcc_release" != "" ]; then
	set -- $nvcc_release
	echo "nvcc release: $1.$2"
	echo "cuda.h CUDA_VERSION: unavailable"
elif [ "$cuda_macro" != "" ]; then
	cuda_maj="$((cuda_macro / 1000))"
	cuda_min="$(((cuda_macro % 1000) / 10))"
	echo "nvcc release: unavailable"
	echo "cuda.h CUDA_VERSION: $cuda_maj.$cuda_min ($cuda_macro)"
else
	echo "nvcc release: unavailable"
	echo "cuda.h CUDA_VERSION: unavailable"
fi
echo
echo "== cuda libraries (ldconfig, first hits) =="
ldconfig -p 2>/dev/null | grep -E "libcuda\\.so\\.1|libcudart\\.so" | head -n 20 || true
echo
echo "== cudnn (headers + libs) =="
cudnn_hdr_found="0"
for hdr in \
	/usr/local/cuda/include/cudnn_version.h \
	/usr/local/cuda/include/cudnn.h \
	/usr/include/cudnn_version.h \
	/usr/include/cudnn.h \
	/usr/include/x86_64-linux-gnu/cudnn_version.h \
	/usr/include/x86_64-linux-gnu/cudnn.h
do
	if [ -r "$hdr" ]; then
		echo "-- $hdr --"
		grep -E "^#define CUDNN_(MAJOR|MINOR|PATCHLEVEL)" "$hdr" 2>/dev/null | head -n 20 || true
		cudnn_hdr_found="1"
	fi
done
if [ "$cudnn_hdr_found" = "0" ]; then
	echo "cudnn headers not found"
fi
echo
ldconfig -p 2>/dev/null | grep -E "libcudnn" | head -n 20 || true
echo
echo "== cuda runtime probe (nvcc, no deps) =="
if [ "$cuda_runtime_probe" = "1" ] && [ "$nvcc_bin" != "" ]; then
	echo "nvcc arch: ${nvcc_arch:-default}"
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
	cudaRuntimeGetVersion(&runtime_v);
	cudaDriverGetVersion(&driver_v);
	std::printf("cuda driver api version: %d\n",driver_v);
	std::printf("cuda runtime api version: %d\n",runtime_v);
	for (dev=0; dev<device_count; dev++)
	{
		if ( cudaGetDeviceProperties(&prop,dev) != cudaSuccess )
		{
			std::printf("cudaGetDeviceProperties failed for dev %d\n",dev);
			return(2);
		}
		std::printf("device%d name: %s\n",dev,prop.name);
		std::printf("device%d cc: %d.%d\n",dev,prop.major,prop.minor);
		std::printf("device%d global mem (bytes): %llu\n",dev,(unsigned long long)prop.totalGlobalMem);
		std::printf("device%d sms: %d\n",dev,prop.multiProcessorCount);
	}
	return(0);
}
CU
	nvcc_extra=""
	if [ "$nvcc_arch" != "" ]; then
		nvcc_extra="-arch=$nvcc_arch"
	fi
	if "$nvcc_bin" $nvcc_extra -O2 -lineinfo "$cu_src" -o "$cu_bin" >"$nvcc_log" 2>&1; then
		"$cu_bin" || true
	else
		echo "nvcc compile failed:"
		sed -n "1,80p" "$nvcc_log" 2>/dev/null || true
	fi
	rm -f "$cu_src" "$cu_bin" "$nvcc_log" >/dev/null 2>&1 || true
elif [ "$cuda_runtime_probe" = "1" ]; then
	echo "nvcc not found"
else
	echo "skipped"
fi
echo
if [ "$pytorch_probe" = "1" ]; then
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
fi
echo "== network =="
ip -br -4 addr 2>/dev/null || ip -brief addr 2>/dev/null || ip addr || true
ip -4 route 2>/dev/null || ip route || true
ip -6 route 2>/dev/null || true
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
echo
echo "== kernel modules (nvidia) =="
lsmod 2>/dev/null | grep -E "^nvidia" || true
echo
echo "== modinfo nvidia (summary) =="
if command -v modinfo >/dev/null 2>&1; then
	modinfo nvidia 2>/dev/null | grep -E "^(filename:|description:|version:|srcversion:|vermagic:)" | head -n 40 || true
else
	echo "modinfo not found"
fi
echo
echo "== /dev nvidia nodes =="
ls -l /dev/nvidia* 2>/dev/null | head -n 80 || true
'
} >"$tmp"

if [ "${REDACT:-0}" = "1" ]; then
	sed -E \
		-e 's/([0-9]{1,3}[.]){3}[0-9]{1,3}/<redacted-ipv4>/g' \
		-e 's/([0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}/<redacted-mac>/g' \
		-e 's/([0-9A-Fa-f]{0,4}:){3,7}[0-9A-Fa-f]{0,4}/<redacted-ipv6>/g' \
		-e 's/UUID: [^)]*/UUID: <redacted-gpu-uuid>/g' \
		-e 's/GPU-[0-9A-Fa-f-]{36}/<redacted-gpu-uuid>/g' \
		"$tmp"
else
	cat "$tmp"
fi
