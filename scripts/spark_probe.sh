#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: spark_probe.sh [user@host ...]

Environment:
  SSH_OPTS             Extra ssh options (default includes BatchMode + temp known_hosts)
  SPARK_KNOWN_HOSTS    SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR          Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE    Optional work tree override (defaults to $PWD)
  REDACT=1             Redact IPv4/IPv6/MAC addresses from output
  NVIDIA_SMI_FULL=1    Include full `nvidia-smi` output (process list, timestamps)
  PYTORCH_PROBE=1      Attempt a python3 torch CUDA probe (optional)
  CUDA_RUNTIME_PROBE=0 Skip the tiny `nvcc` runtime probe compile/run
  NVCC_ARCH            Optional `nvcc -arch` override (e.g., sm_121); default derives from nvidia-smi compute_cap when available

Examples:
  ./scripts/spark_probe.sh
  REDACT=1 ./scripts/spark_probe.sh | tee /private/tmp/spark0-probe.txt
  REDACT=1 NVIDIA_SMI_FULL=1 ./scripts/spark_probe.sh
  REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local spark0@spark1.local
  SPARK_KNOWN_HOSTS_PER_HOST=1 REDACT=1 ./scripts/spark_probe.sh spark0@spark1.local
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

SPARK_KNOWN_HOSTS_PER_HOST="${SPARK_KNOWN_HOSTS_PER_HOST:-0}"
NVIDIA_SMI_FULL="${NVIDIA_SMI_FULL:-0}"
PYTORCH_PROBE="${PYTORCH_PROBE:-0}"
CUDA_RUNTIME_PROBE="${CUDA_RUNTIME_PROBE:-1}"
NVCC_ARCH_OVERRIDE="${NVCC_ARCH:-}"

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2"
fi

if [ "$#" -eq 0 ]; then
	set -- "spark0@aitopatom-9ab9.local"
fi

known_hosts_for_target()
{
	t="$1"
	if [ "${SPARK_KNOWN_HOSTS:-}" != "" ]; then
		echo "$SPARK_KNOWN_HOSTS"
		return 0
	fi
	if [ "$SPARK_KNOWN_HOSTS_PER_HOST" = "1" ]; then
		h="${t#*@}"
		safe_h="$(printf "%s" "$h" | sed -E 's/[^A-Za-z0-9_.-]/_/g')"
		echo "/private/tmp/ds4_spark_known_hosts.$safe_h"
	else
		echo "/private/tmp/ds4_spark_known_hosts"
	fi
	return 0
}

tmp="$(mktemp /private/tmp/ds4_spark_probe.XXXXXX)"
trap 'rm -f "$tmp"' EXIT INT HUP TERM

{
	echo "== local meta =="
	date -u
	if command -v git >/dev/null 2>&1; then
		git_worktree="${DS4_GIT_WORK_TREE:-$PWD}"
		git_dir="${DS4_GIT_DIR:-}"
		if [ "$git_dir" = "" ] && [ -d "$git_worktree/.git-codex" ] && [ -r "$git_worktree/.git-codex/HEAD" ]; then
			git_dir="$git_worktree/.git-codex"
		fi
		if [ "$git_dir" != "" ]; then
			echo "git: $(git --git-dir="$git_dir" --work-tree="$git_worktree" rev-parse --short HEAD 2>/dev/null || true)"
		elif git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
			echo "git: $(git rev-parse --short HEAD 2>/dev/null || true)"
		fi
	fi
	echo "probe targets: $*"
	echo "ssh opts: $SSH_OPTS"
	for t in "$@"; do
		echo "known_hosts: $t -> $(known_hosts_for_target "$t")"
	done
	echo
	for target in "$@"; do
		kh="$(known_hosts_for_target "$target")"
		echo "== target: $target =="
		ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$target" 'set -eu
export LANG=C LC_ALL=C
export TERM=dumb
nvidia_smi_full='"$NVIDIA_SMI_FULL"'
pytorch_probe='"$PYTORCH_PROBE"'
cuda_runtime_probe='"$CUDA_RUNTIME_PROBE"'
nvcc_arch_override='"$NVCC_ARCH_OVERRIDE"'
if [ "$nvcc_arch_override" != "" ]; then
	NVCC_ARCH="$nvcc_arch_override"
fi
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
echo "== packages (cuda/nvidia, dpkg, capped) =="
if command -v dpkg-query >/dev/null 2>&1; then
	dpkg-query -W -f='"'"'${Package}\t${Version}\n'"'"' "cuda*" "nvidia*" "libcudnn*" 2>/dev/null | head -n 200 || true
else
	echo "dpkg-query not found"
fi
echo
echo "== pci nvidia =="
lspci | grep -i nvidia || true
if lspci -nn >/dev/null 2>&1; then
	echo
	echo "== pci nvidia (numeric ids) =="
	lspci -nn | grep -i nvidia || true
fi
echo
echo "== lspci gpu link state (capped) =="
if command -v lspci >/dev/null 2>&1; then
	gpu_buses="$(lspci -D -nn 2>/dev/null | grep -i nvidia | grep -E "VGA compatible controller|3D controller" | awk '"'"'{ print $1 }'"'"' | head -n 16 || true)"
	if [ "$gpu_buses" = "" ]; then
		gpu_buses="$(lspci -nn 2>/dev/null | grep -i nvidia | grep -E "VGA compatible controller|3D controller" | awk '"'"'{ print $1 }'"'"' | head -n 16 || true)"
	fi
	if [ "$gpu_buses" != "" ]; then
		for bus in $gpu_buses; do
			echo "-- $bus --"
			vv="$(lspci -vv -s "$bus" 2>/dev/null || true)"
			if [ "$vv" = "" ]; then
				echo "lspci -vv produced no output (restricted?)"
			else
				link_lines="$(printf "%s\n" "$vv" | grep -E "Lnk(Cap|Sta|Ctl2):" | head -n 20 || true)"
				if [ "$link_lines" != "" ]; then
					printf "%s\n" "$link_lines"
				else
					echo "no LnkCap/LnkSta fields found; header:"
					printf "%s\n" "$vv" | head -n 3 || true
				fi
			fi
		done
	else
		echo "no nvidia vga/3d controller buses found"
	fi
else
	echo "lspci not found"
fi
echo
echo "== nvidia-smi inventory (index + pci bus) =="
have_smi="0"
q=""
if command -v nvidia-smi >/dev/null 2>&1; then
	have_smi="1"
	echo "columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total"
	q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,compute_cap,temperature.gpu,pstate,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
	if [ "$q" != "" ]; then
		echo "$q"
	else
		echo "columns: index,gpu_name,pci.bus_id,driver_version,temperature.gpu,pstate,memory.total"
		q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,temperature.gpu,pstate,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
		[ "$q" != "" ] && echo "$q"
		echo "note: nvidia-smi compute_cap field not supported; rely on nvcc runtime probe for cc"
	fi
else
	echo "nvidia-smi not found"
fi
echo
echo "== nvidia-smi pci ids (optional) =="
if command -v nvidia-smi >/dev/null 2>&1; then
	ids_q="$(nvidia-smi --query-gpu=index,pci.bus_id,pci.device_id,pci.sub_device_id --format=csv,noheader,nounits 2>/dev/null || true)"
	if [ "$ids_q" != "" ]; then
		if printf "%s" "$ids_q" | grep -qi "not a valid field"; then
			echo "pci id query not supported"
			printf "%s\n" "$ids_q" | head -n 2
		else
			echo "columns: index,pci.bus_id,pci.device_id,pci.sub_device_id"
			echo "$ids_q"
		fi
	else
		echo "pci id query not supported"
	fi
else
	echo "nvidia-smi not found"
fi
compute_cap=""
if [ "$q" != "" ]; then
	compute_cap="$(printf "%s\n" "$q" | awk -F"," "{ c=\$5; gsub(/^[ \\t]+|[ \\t]+$/, \"\", c); if ( c ~ /^[0-9]+[.][0-9]+$/ ) { split(c,a,\".\"); v=(a[1]*100)+a[2]; if ( v > best ) { best=v; bestc=c; } } } END { if ( bestc != \"\" ) print bestc; }")"
fi
compute_cap_q=""
smi_q=""
smi_cuda_ver=""
if [ "$have_smi" = "1" ]; then
	smi_q="$(nvidia-smi -q 2>/dev/null || true)"
	smi_cuda_ver="$(printf "%s\n" "$smi_q" | sed -nE "s/^[[:space:]]*CUDA Version[[:space:]]*:[[:space:]]*([0-9]+[.][0-9]+).*/\\1/p" | head -n 1 || true)"
	compute_cap_q="$(printf "%s\n" "$smi_q" | sed -nE "s/^[[:space:]]*Compute Capability[[:space:]]*:[[:space:]]*([0-9]+)[.]([0-9]+).*/\\1.\\2/p" | awk -F. "{ v=(\$1*100)+\$2; if ( v > best ) { best=v; bestc=\$0; } } END { if ( bestc != \"\" ) print bestc; }")"
fi
if [ "$compute_cap" = "" ] && [ "$compute_cap_q" != "" ]; then
	compute_cap="$compute_cap_q"
fi
nvcc_arch=""
if [ "${NVCC_ARCH:-}" != "" ]; then
	nvcc_arch="$NVCC_ARCH"
elif [ "$compute_cap" != "" ]; then
	nvcc_arch="sm_$(printf "%s" "$compute_cap" | sed -E "s/[^0-9.]//g; s/[.]//g")"
fi
if [ "$compute_cap" != "" ]; then
	echo "selected compute_cap: $compute_cap"
fi
if [ "$compute_cap_q" != "" ]; then
	echo "compute_cap (-q): $compute_cap_q"
	if [ "$compute_cap" != "" ] && [ "$compute_cap" != "$compute_cap_q" ]; then
		echo "warning: compute_cap selected $compute_cap != nvidia-smi -q compute_cap $compute_cap_q"
	fi
fi
if [ "$nvcc_arch" != "" ]; then
	echo "selected nvcc arch: $nvcc_arch"
else
	echo "selected nvcc arch: default"
fi
echo
echo "== nvidia-smi cuda version =="
[ "$have_smi" = "1" ] && [ "$smi_cuda_ver" = "" ] && smi_cuda_ver="$(printf "%s\n" "$smi_q" | grep -i "cuda version" | sed -nE "s/.*([0-9]+[.][0-9]+).*/\\1/p" | head -n 1 || true)"
if [ "$have_smi" = "1" ]; then
	[ "$smi_cuda_ver" != "" ] && echo "CUDA Version: $smi_cuda_ver" || echo "CUDA Version: unknown"
else
	echo "nvidia-smi not found"
fi
echo
pcie_link_query()
{
	pcie_q="$(nvidia-smi --query-gpu=index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current --format=csv,noheader,nounits 2>/dev/null || true)"
	if [ "$pcie_q" = "" ]; then
		pcie_q="$(nvidia-smi --query-gpu=index,pci.bus_id,pci.link.gen.max,pci.link.gen.current,pci.link.width.max,pci.link.width.current --format=csv,noheader,nounits 2>/dev/null || true)"
	fi
	printf "%s" "$pcie_q"
	return 0
}

emit_pcie_link()
{
	label="$1"
	echo "== nvidia-smi pcie link (max/current${label}) =="
	if command -v nvidia-smi >/dev/null 2>&1; then
		pcie_q="$(pcie_link_query)"
		if [ "$pcie_q" != "" ]; then
			if printf "%s" "$pcie_q" | grep -qi "not a valid field"; then
				echo "pcie link query not supported"
				printf "%s\n" "$pcie_q" | head -n 2
			else
				echo "columns: index,pci.bus_id,pcie.link.gen.max,pcie.link.gen.current,pcie.link.width.max,pcie.link.width.current"
				echo "$pcie_q"
			fi
		else
			echo "pcie link query not supported"
		fi
	else
		echo "nvidia-smi not found"
	fi
	return 0
}

emit_sysfs_pcie_link()
{
	label="$1"
	echo "== pci link (sysfs, current/max${label}) =="
	if [ -d /sys/bus/pci/devices ]; then
		bus_ids=""
		if [ "$q" != "" ]; then
			bus_ids="$(printf "%s\n" "$q" | cut -d"," -f3 | sed -E "s/^[[:space:]]+|[[:space:]]+\\$//g" | sort -u | paste -sd " " - 2>/dev/null || true)"
		fi
		if [ "$bus_ids" != "" ]; then
			for bus in $bus_ids; do
				dom="$(printf "%s" "$bus" | cut -d: -f1 | sed -E "s/.*([0-9A-Fa-f]{4})$/\\1/" | tr ABCDEF abcdef)"
				rest="$(printf "%s" "$bus" | cut -d: -f2-)"
				short_bus="${dom}:${rest}"
				sys="/sys/bus/pci/devices/$short_bus"
				echo "-- $bus -> $short_bus --"
				if [ -d "$sys" ]; then
					if command -v readlink >/dev/null 2>&1; then
						devpath="$(readlink -f "$sys" 2>/dev/null || true)"
						if [ "$devpath" != "" ]; then
							echo "sysfs: $devpath"
							chain="$(printf "%s" "$devpath" | tr "/" "\n" | grep -E "^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}[.][0-7]$" | paste -sd " " - 2>/dev/null || true)"
							if [ "$chain" != "" ]; then
								echo "path: $chain"
									for dev in $chain; do
										p="/sys/bus/pci/devices/$dev"
										[ -r "$p/current_link_speed" ] && echo "path $dev current_link_speed: $(cat "$p/current_link_speed" 2>/dev/null || true)"
										[ -r "$p/current_link_width" ] && echo "path $dev current_link_width: $(cat "$p/current_link_width" 2>/dev/null || true)"
										[ -r "$p/max_link_speed" ] && echo "path $dev max_link_speed: $(cat "$p/max_link_speed" 2>/dev/null || true)"
										[ -r "$p/max_link_width" ] && echo "path $dev max_link_width: $(cat "$p/max_link_width" 2>/dev/null || true)"
										if command -v lspci >/dev/null 2>&1; then
											vv="$(lspci -vv -s "$dev" 2>/dev/null || true)"
											if [ "$vv" != "" ]; then
												link_lines="$(printf "%s\n" "$vv" | grep -E "Lnk(Cap|Sta|Ctl2):" | head -n 20 || true)"
												if [ "$link_lines" != "" ]; then
													printf "%s\n" "$link_lines" | sed -E "s/^/path $dev /"
												fi
											fi
										fi
									done
								fi
						fi
					fi
					[ -r "$sys/vendor" ] && echo "vendor: $(cat "$sys/vendor" 2>/dev/null || true)"
					[ -r "$sys/device" ] && echo "device: $(cat "$sys/device" 2>/dev/null || true)"
					[ -r "$sys/subsystem_vendor" ] && echo "subsystem_vendor: $(cat "$sys/subsystem_vendor" 2>/dev/null || true)"
					[ -r "$sys/subsystem_device" ] && echo "subsystem_device: $(cat "$sys/subsystem_device" 2>/dev/null || true)"
					[ -r "$sys/class" ] && echo "class: $(cat "$sys/class" 2>/dev/null || true)"
					[ -r "$sys/current_link_speed" ] && echo "current_link_speed: $(cat "$sys/current_link_speed" 2>/dev/null || true)"
					[ -r "$sys/current_link_width" ] && echo "current_link_width: $(cat "$sys/current_link_width" 2>/dev/null || true)"
					[ -r "$sys/max_link_speed" ] && echo "max_link_speed: $(cat "$sys/max_link_speed" 2>/dev/null || true)"
					[ -r "$sys/max_link_width" ] && echo "max_link_width: $(cat "$sys/max_link_width" 2>/dev/null || true)"
				else
					echo "sysfs device not found: $sys"
				fi
			done
		else
			echo "no pci.bus_id inventory"
		fi
	else
		echo "/sys/bus/pci/devices not found"
	fi
	return 0
}

emit_pcie_link ""
echo
emit_sysfs_pcie_link ""
echo
echo "== nvidia-smi power/clocks (summary) =="
if command -v nvidia-smi >/dev/null 2>&1; then
	pwr_q="$(nvidia-smi --query-gpu=index,pci.bus_id,power.limit,power.draw,clocks.gr,clocks.sm,clocks.mem,utilization.gpu,utilization.memory --format=csv,noheader,nounits 2>/dev/null || true)"
	if [ "$pwr_q" != "" ]; then
		if printf "%s" "$pwr_q" | grep -qi "not a valid field"; then
			echo "power/clocks query not supported"
			printf "%s\n" "$pwr_q" | head -n 2
		else
			echo "columns: index,pci.bus_id,power.limit,power.draw,clocks.gr,clocks.sm,clocks.mem,utilization.gpu,utilization.memory"
			echo "$pwr_q"
		fi
	else
		echo "power/clocks query not supported"
	fi
else
	echo "nvidia-smi not found"
fi
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
	if command -v nvcc >/dev/null 2>&1; then
		echo "nvcc path: $nvcc_bin (on PATH)"
	else
		echo "nvcc path: $nvcc_bin (not on PATH)"
	fi
fi
nvcc_release=""
if [ "$nvcc_bin" != "" ]; then
	nvcc_ver="$("$nvcc_bin" --version 2>/dev/null || true)"
	[ "$nvcc_ver" != "" ] && printf "%s\n" "$nvcc_ver"
	nvcc_release="$(printf "%s\n" "$nvcc_ver" | sed -nE "s/.*release[[:space:]]+([0-9]+)\\.([0-9]+).*/\\1.\\2/p" | head -n 1)"
	ls -l "$nvcc_bin" || true
else
	echo "nvcc not found"
fi
if [ "$nvcc_bin" != "" ]; then
	echo
	echo "== nvcc supported gpu arch (capped) =="
	if "$nvcc_bin" --list-gpu-arch >/dev/null 2>&1; then
		"$nvcc_bin" --list-gpu-arch 2>/dev/null | head -n 200 || true
	else
		echo "nvcc --list-gpu-arch not supported"
	fi
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
cuda_h_version=""
if [ -r "$cuda_h" ]; then
	echo "$cuda_h"
	cuda_h_version="$(grep -E "^#define CUDA_VERSION " "$cuda_h" 2>/dev/null | awk "{ print \$3 }" | head -n 1 || true)"
	grep -E "^#define (CUDA_VERSION|CUDART_VERSION) " "$cuda_h" 2>/dev/null || true
else
	echo "cuda.h not found"
fi
if [ "$nvcc_release" != "" ] && [ "$cuda_h_version" != "" ]; then
	nvcc_major="$(printf "%s" "$nvcc_release" | awk -F. "{ print \$1 }")"
	nvcc_minor="$(printf "%s" "$nvcc_release" | awk -F. "{ print \$2 }")"
	nvcc_expect="$(( (nvcc_major * 1000) + (nvcc_minor * 10) ))"
	if [ "$cuda_h_version" != "$nvcc_expect" ]; then
		echo "warning: nvcc release $nvcc_release expects CUDA_VERSION $nvcc_expect but cuda.h has $cuda_h_version"
	fi
fi
if [ "$smi_cuda_ver" != "" ] && [ "$nvcc_release" != "" ]; then
	smi_major="$(printf "%s" "$smi_cuda_ver" | awk -F. "{ print \$1 }")"
	nvcc_major="$(printf "%s" "$nvcc_release" | awk -F. "{ print \$1 }")"
	if [ "$smi_major" != "$nvcc_major" ]; then
		echo "note: nvidia-smi CUDA $smi_cuda_ver differs from nvcc release $nvcc_release (driver vs toolkit)"
	fi
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
echo "== cuda demo_suite (deviceQuery, optional) =="
if [ -x /usr/local/cuda/extras/demo_suite/deviceQuery ]; then
	/usr/local/cuda/extras/demo_suite/deviceQuery 2>/dev/null | head -n 120 || true
else
	echo "deviceQuery not found"
fi
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
		out="$("$cu_bin" 2>/dev/null || true)"
		[ "$out" != "" ] && printf "%s\n" "$out"
		if [ "$compute_cap" != "" ] && [ "$out" != "" ]; then
			cc0="$(printf "%s\n" "$out" | sed -nE "s/^device0 cc: ([0-9]+)[.]([0-9]+)/\\1.\\2/p" | head -n 1)"
			if [ "$cc0" != "" ] && [ "$cc0" != "$compute_cap" ]; then
				echo "warning: compute_cap $compute_cap != runtime device0 cc $cc0"
			fi
		fi
		echo
		emit_pcie_link ", post-load"
		echo
		emit_sysfs_pcie_link ", post-load"
	else
		echo "nvcc compile failed:"
		sed -n "1,80p" "$nvcc_log" 2>/dev/null || true
		if [ "$nvcc_extra" != "" ]; then
			echo "retry: nvcc without -arch (fallback)"
			if "$nvcc_bin" -O2 -lineinfo "$cu_src" -o "$cu_bin" >"$nvcc_log" 2>&1; then
				"$cu_bin" 2>/dev/null || true
			else
				echo "nvcc fallback compile failed:"
				sed -n "1,80p" "$nvcc_log" 2>/dev/null || true
			fi
		fi
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
		ethtool -i "$iface" 2>/dev/null | grep -E "^(driver:|version:|firmware-version:|bus-info:)" || true
	done
fi
echo
echo "== rdma (roce/infiniband, optional) =="
if [ -d /sys/class/infiniband ]; then
	ls -1 /sys/class/infiniband 2>/dev/null || true
	for dev in /sys/class/infiniband/*; do
		[ -d "$dev" ] || continue
		echo "-- $(basename "$dev") --"
		[ -r "$dev/fw_ver" ] && echo "fw_ver: $(cat "$dev/fw_ver" 2>/dev/null | head -n 1 || true)"
		[ -r "$dev/hca_type" ] && echo "hca_type: $(cat "$dev/hca_type" 2>/dev/null | head -n 1 || true)"
		for port in "$dev"/ports/*; do
			[ -d "$port" ] || continue
			pn="$(basename "$port")"
			state="$(cat "$port/state" 2>/dev/null | head -n 1 || true)"
			phys="$(cat "$port/phys_state" 2>/dev/null | head -n 1 || true)"
			rate="$(cat "$port/rate" 2>/dev/null | head -n 1 || true)"
			layer="$(cat "$port/link_layer" 2>/dev/null | head -n 1 || true)"
			[ "$state$phys$rate$layer" != "" ] && echo "port$pn: state=${state:-?} phys=${phys:-?} rate=${rate:-?} layer=${layer:-?}"
		done
	done
else
	echo "no /sys/class/infiniband"
fi
if command -v rdma >/dev/null 2>&1; then
	rdma link show 2>/dev/null | head -n 80 || true
else
	echo "rdma tool not found"
fi
echo
echo "== filesystems (type + opts) =="
if command -v findmnt >/dev/null 2>&1; then
	findmnt -no TARGET,FSTYPE,OPTIONS / /home 2>/dev/null || findmnt -no TARGET,FSTYPE,OPTIONS / 2>/dev/null || true
else
	echo "findmnt not found"
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
		echo
	done
} >"$tmp"

if [ "${REDACT:-0}" = "1" ]; then
	sed -E \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4>\4/g' \
		-e 's/([0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}/<redacted-mac>/g' \
		-e 's/([0-9A-Fa-f]{0,4}:){3,7}[0-9A-Fa-f]{0,4}/<redacted-ipv6>/g' \
		-e 's/UUID: [^)]*/UUID: <redacted-gpu-uuid>/g' \
		-e 's/GPU-[0-9A-Fa-f-]{36}/<redacted-gpu-uuid>/g' \
		"$tmp"
else
	cat "$tmp"
fi
