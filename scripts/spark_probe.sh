#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: spark_probe.sh [user@host ...]

Environment:
  SPARK_SSH_USER        Default SSH username for host-only args (default: spark0)
  SSH_OPTS             Extra ssh options (default includes BatchMode + temp known_hosts)
  SPARK_KNOWN_HOSTS    SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR          Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE    Optional work tree override (defaults to $PWD)
  REDACT=1             Redact IPv4/IPv6/MAC addresses from output
  SPARK_PROBE_FACTS=1  Facts-only mode (stable, compact; implies SPARK_PROBE_SUMMARY=1)
  SPARK_PROBE_SUMMARY=1  Print a smaller, Spark1-friendly subset of sections
  NVIDIA_SMI_FULL=1    Include full `nvidia-smi` output (process list, timestamps)
  PYTORCH_PROBE=1      Attempt a python3 torch CUDA probe (optional)
  CUDA_RUNTIME_PROBE=0 Skip the tiny `nvcc` runtime probe compile/run
  NVCC_ARCH            Optional `nvcc -arch` override (e.g., sm_121); default derives from nvidia-smi compute_cap when available

Examples:
  ./scripts/spark_probe.sh
  REDACT=1 ./scripts/spark_probe.sh | tee /private/tmp/spark0-probe.txt
  DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local
  REDACT=1 NVIDIA_SMI_FULL=1 ./scripts/spark_probe.sh
  REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_probe.sh spark0@aitopatom-9ab9.local spark0@spark1.local
  SPARK_KNOWN_HOSTS_PER_HOST=1 REDACT=1 ./scripts/spark_probe.sh spark0@spark1.local
  SPARK_SSH_USER=spark0 REDACT=1 ./scripts/spark_probe.sh aitopatom-9ab9.local spark1.local

Notes:
  - When probing multiple targets, the script continues past SSH failures and prints a `== probe summary ==`.
  - Exit status is non-zero if any target failed; use `|| true` when saving partial output.
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

SPARK_KNOWN_HOSTS_PER_HOST="${SPARK_KNOWN_HOSTS_PER_HOST:-0}"
SPARK_SSH_USER="${SPARK_SSH_USER:-spark0}"
SPARK_PROBE_FACTS="${SPARK_PROBE_FACTS:-0}"
SPARK_PROBE_SUMMARY="${SPARK_PROBE_SUMMARY:-0}"
NVIDIA_SMI_FULL="${NVIDIA_SMI_FULL:-0}"
PYTORCH_PROBE="${PYTORCH_PROBE:-0}"
CUDA_RUNTIME_PROBE="${CUDA_RUNTIME_PROBE:-1}"
NVCC_ARCH_OVERRIDE="${NVCC_ARCH:-}"

if [ "$SPARK_PROBE_FACTS" = "1" ]; then
	SPARK_PROBE_SUMMARY="1"
	NVIDIA_SMI_FULL="0"
	PYTORCH_PROBE="0"
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=2"
fi

normalize_target()
{
	t="$1"
	case "$t" in
		*@*)
			printf "%s" "$t"
			;;
		*)
			printf "%s" "${SPARK_SSH_USER}@${t}"
			;;
	esac
}

targets=""
if [ "$#" -eq 0 ]; then
	targets="$(normalize_target "aitopatom-9ab9.local")"
else
	for t in "$@"; do
		nt="$(normalize_target "$t")"
		if [ "$targets" = "" ]; then
			targets="$nt"
		else
			targets="$targets $nt"
		fi
	done
fi

probe_args="$*"
if [ "$probe_args" = "" ]; then
	probe_args="(default)"
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
		if [ "$git_dir" = "" ] && [ -d "$git_worktree/.codex_git" ] && [ -r "$git_worktree/.codex_git/HEAD" ]; then
			git_dir="$git_worktree/.codex_git"
		fi
		if [ "$git_dir" = "" ] && [ -d "$git_worktree/.codex_git/.git" ] && [ -r "$git_worktree/.codex_git/.git/HEAD" ]; then
			git_dir="$git_worktree/.codex_git/.git"
		fi
		if [ "$git_dir" = "" ] && [ -d "$git_worktree/.git-codex" ] && [ -r "$git_worktree/.git-codex/HEAD" ]; then
			git_dir="$git_worktree/.git-codex"
		fi
		if [ "$git_dir" = "" ] && [ -d "$git_worktree/.git-codex/.git" ] && [ -r "$git_worktree/.git-codex/.git/HEAD" ]; then
			git_dir="$git_worktree/.git-codex/.git"
		fi
		if [ "$git_dir" = "" ] && [ -d "$git_worktree/.gitshim/repo/.git" ] && [ -r "$git_worktree/.gitshim/repo/.git/HEAD" ]; then
			git_dir="$git_worktree/.gitshim/repo/.git"
		fi
		git_hash=""
		if [ "$git_dir" != "" ]; then
			git_hash="$(git --git-dir="$git_dir" --work-tree="$git_worktree" rev-parse --short HEAD 2>/dev/null || true)"
		fi
		if [ "$git_hash" = "" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
			git_hash="$(git rev-parse --short HEAD 2>/dev/null || true)"
		fi
		if [ "$git_hash" != "" ]; then
			echo "git: $git_hash"
		else
			echo "git: (unknown)"
		fi
	fi
	echo "probe args: $probe_args"
	echo "resolved targets: $targets"
	echo "ssh opts: $SSH_OPTS"
	for t in $targets; do
		echo "known_hosts: $t -> $(known_hosts_for_target "$t")"
	done
	echo
	ssh_fail="0"
	for target in $targets; do
		kh="$(known_hosts_for_target "$target")"
		echo "== target: $target =="
		if ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$target" 'set -eu
export LANG=C LC_ALL=C
export TERM=dumb
nvidia_smi_full='"$NVIDIA_SMI_FULL"'
spark_probe_summary='"$SPARK_PROBE_SUMMARY"'
spark_probe_facts='"$SPARK_PROBE_FACTS"'
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
echo "== clock =="
date -u +"utc: %Y-%m-%dT%H:%M:%SZ"
date -u +"epoch: %s"
if command -v timedatectl >/dev/null 2>&1; then
	timedatectl show -p NTPSynchronized -p SystemClockSynchronized -p NTPService -p TimeUSec 2>/dev/null || true
fi
if command -v chronyc >/dev/null 2>&1; then
	chronyc tracking 2>/dev/null | grep -E "^(Reference ID|Stratum|Ref time|System time|Last offset|RMS offset|Frequency|Skew|Root delay|Root dispersion|Update interval|Leap status)" | head -n 40 || true
fi
echo
echo "== os =="
if [ -r /etc/os-release ]; then
	cat /etc/os-release
fi
echo
echo "== cpu =="
if [ "$spark_probe_facts" = "1" ]; then
	lscpu 2>/dev/null | grep -E "^(Architecture:|Byte Order:|CPU\\(s\\):|Model name:|Thread\\(s\\) per core:|Core\\(s\\) per socket:|Socket\\(s\\):|NUMA node\\(s\\):)" || lscpu || true
else
	lscpu || true
fi
echo
echo "== memory =="
if [ "$spark_probe_facts" = "1" ]; then
	free -h 2>/dev/null | awk '"'"'NR==1 || $1=="Mem:" || $1=="Swap:" {print}'"'"' || free -h || true
else
	free -h || true
fi
echo
echo "== toolchain =="
for tool in gcc g++ clang cmake ninja make python3 ldd; do
	if command -v "$tool" >/dev/null 2>&1; then
		echo "$tool path: $(command -v "$tool")"
	fi
done
command -v gcc >/dev/null 2>&1 && gcc --version | head -n 1 || true
command -v g++ >/dev/null 2>&1 && g++ --version | head -n 1 || true
command -v clang >/dev/null 2>&1 && clang --version | head -n 1 || true
command -v cmake >/dev/null 2>&1 && cmake --version | head -n 1 || true
command -v ninja >/dev/null 2>&1 && ninja --version || true
command -v make >/dev/null 2>&1 && make --version | head -n 1 || true
command -v python3 >/dev/null 2>&1 && python3 --version || true
command -v ldd >/dev/null 2>&1 && ldd --version 2>/dev/null | head -n 1 || true
echo
if [ "$spark_probe_summary" != "1" ] && [ "$spark_probe_facts" != "1" ]; then
	echo "== packages (cuda/nvidia, dpkg, capped) =="
	if command -v dpkg-query >/dev/null 2>&1; then
		dpkg-query -W -f='"'"'${Package}\t${Version}\n'"'"' "cuda*" "nvidia*" "libcudnn*" 2>/dev/null | head -n 200 || true
	else
		echo "dpkg-query not found"
	fi
	echo
fi
echo "== pci nvidia =="
lspci | grep -i nvidia || true
if lspci -nn >/dev/null 2>&1; then
	echo
	echo "== pci nvidia (numeric ids) =="
	lspci -nn | grep -i nvidia || true
fi
echo
if [ "$spark_probe_summary" != "1" ]; then
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
fi
have_smi="0"
if command -v nvidia-smi >/dev/null 2>&1; then
	have_smi="1"
fi
echo "== nvidia-smi version =="
if [ "$have_smi" = "1" ]; then
	(nvidia-smi --version 2>/dev/null || nvidia-smi -V 2>/dev/null || true) | sed -E '/^ERROR:/d' | head -n 20 || true
else
	echo "nvidia-smi not found"
fi
echo
echo "== nvidia-smi inventory (index + pci bus) =="
q=""
if [ "$have_smi" = "1" ]; then
	if [ "$spark_probe_facts" = "1" ]; then
		echo "columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,memory.total"
		q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,compute_cap,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
		if [ "$q" != "" ]; then
			echo "$q"
		else
			echo "columns: index,gpu_name,pci.bus_id,driver_version,memory.total"
			q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
			[ "$q" != "" ] && echo "$q"
			echo "note: nvidia-smi compute_cap field not supported; rely on nvcc runtime probe for cc"
		fi
	else
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
	fi
	else
		echo "nvidia-smi not found"
	fi
	if [ "$q" != "" ]; then
		smi_mem_total_any_na="$(printf "%s\n" "$q" | awk -F"," '"'"'{ v=$NF; gsub(/^[ \t]+|[ \t]+$/, "", v); if ( v == "[N/A]" ) { print "1"; exit } }'"'"')"
		if [ "$smi_mem_total_any_na" = "1" ]; then
			echo "note: nvidia-smi memory.total is [N/A] (unified memory); use == memory == and the cuda runtime probe global mem bytes"
		fi
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
driver_version=""
if [ "$q" != "" ]; then
	driver_version="$(printf "%s\n" "$q" | head -n 1 | awk -F"," "{ v=\$4; gsub(/^[ \\t]+|[ \\t]+$/, \"\", v); print v; }" || true)"
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
echo "== nvidia-smi -q fabric/c2c (summary) =="
if [ "$have_smi" = "1" ] && [ "$smi_q" != "" ]; then
	smi_arch="$(printf "%s\n" "$smi_q" | sed -nE "s/^[[:space:]]*Product Architecture[[:space:]]*:[[:space:]]*(.+)$/\\1/p" | head -n 1 || true)"
	smi_peer_type="$(printf "%s\n" "$smi_q" | sed -nE "s/^[[:space:]]*Peer Type[[:space:]]*:[[:space:]]*(.+)$/\\1/p" | head -n 1 || true)"
	smi_c2c_mode="$(printf "%s\n" "$smi_q" | sed -nE "s/^[[:space:]]*GPU C2C Mode[[:space:]]*:[[:space:]]*(.+)$/\\1/p" | head -n 1 || true)"
	[ "$smi_arch" != "" ] && echo "Product Architecture: $smi_arch"
	[ "$smi_peer_type" != "" ] && echo "Peer Type: $smi_peer_type"
	[ "$smi_c2c_mode" != "" ] && echo "GPU C2C Mode: $smi_c2c_mode"
else
	echo "nvidia-smi -q not available"
fi
if [ "$spark_probe_facts" = "1" ]; then
	echo
	echo "== probe mode =="
	echo "facts-only: 1"
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

	smi_q_pcie_warn()
	{
		src="$1"
		bus="$2"
		q_gen_max="$3"
		q_gen_cur="$4"
		q_width_max="$5"
		q_width_cur="$6"
		[ "$bus" = "" ] && return 0
		[ "$smi_q" = "" ] && return 0
		block="$(printf "%s\n" "$smi_q" | awk -v bus="$bus" "BEGIN{inblk=0;count=0} \$0 ~ /^[[:space:]]*Bus Id[[:space:]]*:[[:space:]]*/ { if ( \$0 ~ bus ) { inblk=1; next } if ( inblk==1 ) { exit } } inblk==1 { print; count++; if ( count >= 140 ) exit }")"
		[ "$block" = "" ] && return 0
		dev_max_gen="$(printf "%s\n" "$block" | sed -nE "s/^[[:space:]]*Device Max[[:space:]]*:[[:space:]]*([0-9]+).*/\\1/p" | head -n 1 || true)"
		host_max_gen="$(printf "%s\n" "$block" | sed -nE "s/^[[:space:]]*Host Max[[:space:]]*:[[:space:]]*([0-9]+).*/\\1/p" | head -n 1 || true)"
		dev_cur_gen="$(printf "%s\n" "$block" | sed -nE "s/^[[:space:]]*Device Current[[:space:]]*:[[:space:]]*([0-9]+).*/\\1/p" | head -n 1 || true)"
		q_max_gen="$(printf "%s" "$q_gen_max" | sed -E "s/[^0-9]//g")"
		q_cur_gen="$(printf "%s" "$q_gen_cur" | sed -E "s/[^0-9]//g")"
		if [ "$src" = "" ]; then
			src="pcie"
		fi
		if [ "$q_max_gen" != "" ] && [ "$dev_max_gen" != "" ] && [ "$host_max_gen" != "" ]; then
			if [ "$q_max_gen" -lt "$dev_max_gen" ] && [ "$q_max_gen" -lt "$host_max_gen" ]; then
				echo "warning: $src pcie.gen.max=$q_max_gen but -q shows device_max=$dev_max_gen host_max=$host_max_gen (bus $bus)"
			fi
		fi
		if [ "$q_cur_gen" != "" ] && [ "$dev_cur_gen" != "" ]; then
			if [ "$q_cur_gen" -ne "$dev_cur_gen" ]; then
				echo "note: $src pcie.gen.current=$q_cur_gen but -q device_current=$dev_cur_gen (bus $bus)"
			fi
		fi
		q_max_width="$(printf "%s" "$q_width_max" | sed -E "s/[^0-9]//g")"
		q_cur_width="$(printf "%s" "$q_width_cur" | sed -E "s/[^0-9]//g")"
		dev_max_width="$(printf "%s\n" "$block" | awk "BEGIN{inw=0} \$0 ~ /^[[:space:]]*Link Width[[:space:]]*$/ {inw=1;next} inw==1 && \$0 ~ /^[[:space:]]*Max[[:space:]]*:/ {v=\$0; sub(/.*:/,\"\",v); gsub(/^[[:space:]]+|[[:space:]]+$/,\"\",v); sub(/x.*/,\"\",v); gsub(/[^0-9]/,\"\",v); if(v!=\"\"){print v; exit}}")"
		dev_cur_width="$(printf "%s\n" "$block" | awk "BEGIN{inw=0} \$0 ~ /^[[:space:]]*Link Width[[:space:]]*$/ {inw=1;next} inw==1 && \$0 ~ /^[[:space:]]*Current[[:space:]]*:/ {v=\$0; sub(/.*:/,\"\",v); gsub(/^[[:space:]]+|[[:space:]]+$/,\"\",v); sub(/x.*/,\"\",v); gsub(/[^0-9]/,\"\",v); if(v!=\"\"){print v; exit}}")"
		if [ "$q_max_width" != "" ] && [ "$dev_max_width" != "" ]; then
			if [ "$q_max_width" -ne "$dev_max_width" ]; then
				echo "note: $src pcie.width.max=$q_max_width but -q width_max=$dev_max_width (bus $bus)"
			fi
		fi
		if [ "$q_cur_width" != "" ] && [ "$dev_cur_width" != "" ]; then
			if [ "$q_cur_width" -ne "$dev_cur_width" ]; then
				echo "note: $src pcie.width.current=$q_cur_width but -q width_current=$dev_cur_width (bus $bus)"
			fi
		fi
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
					printf "%s\n" "$pcie_q" | awk -F"," "{ b=\$2; gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", b); gmax=\$3; gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", gmax); gcur=\$4; gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", gcur); wmax=\$5; gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", wmax); wcur=\$6; gsub(/^[[:space:]]+|[[:space:]]+$/, \"\", wcur); printf \"%s\\t%s\\t%s\\t%s\\t%s\\n\", b,gmax,gcur,wmax,wcur; }" | while IFS="$(printf \"\\t\")" read -r bus gmax gcur wmax wcur; do
						smi_q_pcie_warn "nvidia-smi" "$bus" "$gmax" "$gcur" "$wmax" "$wcur"
					done
					extra_q="$(nvidia-smi --query-gpu=index,pci.bus_id,pcie.link.gen.gpucurrent,pcie.link.gen.gpumax,pcie.link.gen.hostmax,pcie.link.width.current,pcie.link.width.max --format=csv,noheader,nounits 2>/dev/null || true)"
					if [ "$extra_q" != "" ] && ! printf "%s" "$extra_q" | grep -qi "not a valid field"; then
						echo
						echo "== nvidia-smi pcie link (gpu/host max, optional${label}) =="
						echo "columns: index,pci.bus_id,pcie.link.gen.gpucurrent,pcie.link.gen.gpumax,pcie.link.gen.hostmax,pcie.link.width.current,pcie.link.width.max"
						echo "$extra_q"
					fi
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
		pcie_speed_to_gen()
		{
			s="$1"
			n="${s%% *}"
			case "$n" in
				2.5) echo 1 ;;
				5|5.0) echo 2 ;;
				8|8.0) echo 3 ;;
				16|16.0) echo 4 ;;
				32|32.0) echo 5 ;;
				64|64.0) echo 6 ;;
				*) echo "" ;;
			esac
			return 0
		}
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
					sys_cur_speed="$(cat "$sys/current_link_speed" 2>/dev/null || true)"
					sys_cur_width="$(cat "$sys/current_link_width" 2>/dev/null || true)"
					sys_max_speed="$(cat "$sys/max_link_speed" 2>/dev/null || true)"
					sys_max_width="$(cat "$sys/max_link_width" 2>/dev/null || true)"
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
					[ "$sys_cur_speed" != "" ] && echo "current_link_speed: $sys_cur_speed"
					[ "$sys_cur_width" != "" ] && echo "current_link_width: $sys_cur_width"
					[ "$sys_max_speed" != "" ] && echo "max_link_speed: $sys_max_speed"
					[ "$sys_max_width" != "" ] && echo "max_link_width: $sys_max_width"
					sys_gen_cur="$(pcie_speed_to_gen "$sys_cur_speed")"
					sys_gen_max="$(pcie_speed_to_gen "$sys_max_speed")"
					if [ "$sys_gen_cur" != "" ] || [ "$sys_gen_max" != "" ]; then
						smi_q_pcie_warn "sysfs" "$bus" "${sys_gen_max:-}" "${sys_gen_cur:-}" "${sys_max_width:-}" "${sys_cur_width:-}"
					fi
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

emit_smi_q_pci_link()
{
	label="$1"
	echo "== nvidia-smi -q pci link (capped${label}) =="
	if [ "$have_smi" = "1" ] && [ "$smi_q" != "" ]; then
		pci_lines="$(printf "%s\n" "$smi_q" | awk '"'"'BEGIN{in_pci=0;count=0} $0 ~ /^[[:space:]]*PCI[[:space:]]*$/ {in_pci=1;next} in_pci==1 && $0 ~ /^[[:space:]]*Fan Speed/ {exit} in_pci==1 {print;count++; if(count>=120) exit }'"'"')"
		if [ "$pci_lines" != "" ]; then
			printf "%s\n" "$pci_lines"
		else
			echo "no PCI section found in nvidia-smi -q"
		fi
	else
		echo "nvidia-smi -q not available"
	fi
	return 0
}

	emit_sysfs_pcie_link_summary()
	{
		label="$1"
		echo "== pci link (sysfs, gpu endpoints, current/max${label}) =="
		pcie_speed_to_gen()
		{
			s="$1"
			n="${s%% *}"
			case "$n" in
				2.5) echo 1 ;;
				5|5.0) echo 2 ;;
				8|8.0) echo 3 ;;
				16|16.0) echo 4 ;;
				32|32.0) echo 5 ;;
				64|64.0) echo 6 ;;
				*) echo "" ;;
			esac
			return 0
		}
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
					sys_cur_speed="$(cat "$sys/current_link_speed" 2>/dev/null || true)"
					sys_cur_width="$(cat "$sys/current_link_width" 2>/dev/null || true)"
					sys_max_speed="$(cat "$sys/max_link_speed" 2>/dev/null || true)"
					sys_max_width="$(cat "$sys/max_link_width" 2>/dev/null || true)"
					[ "$sys_cur_speed" != "" ] && echo "current_link_speed: $sys_cur_speed"
					[ "$sys_cur_width" != "" ] && echo "current_link_width: $sys_cur_width"
					[ "$sys_max_speed" != "" ] && echo "max_link_speed: $sys_max_speed"
					[ "$sys_max_width" != "" ] && echo "max_link_width: $sys_max_width"
					sys_gen_cur="$(pcie_speed_to_gen "$sys_cur_speed")"
					sys_gen_max="$(pcie_speed_to_gen "$sys_max_speed")"
					if [ "$sys_gen_cur" != "" ] || [ "$sys_gen_max" != "" ]; then
						smi_q_pcie_warn "sysfs" "$bus" "${sys_gen_max:-}" "${sys_gen_cur:-}" "${sys_max_width:-}" "${sys_cur_width:-}"
					fi
				else
					echo "sysfs device not found: $sys"
				fi
			done
		else
			echo "nvidia-smi inventory missing bus ids"
		fi
	else
		echo "no /sys/bus/pci/devices"
	fi
	return 0
}

emit_pcie_link ""
echo
if [ "$spark_probe_facts" != "1" ] && [ "$spark_probe_summary" != "1" ]; then
	emit_sysfs_pcie_link ""
	echo
	emit_smi_q_pci_link ""
	echo
else
	emit_sysfs_pcie_link_summary ""
	echo
fi
if [ "$spark_probe_facts" != "1" ]; then
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
fi
if [ "$spark_probe_summary" != "1" ]; then
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
fi
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
	if [ "$spark_probe_summary" != "1" ]; then
		echo "== nvcc supported gpu arch (capped) =="
		if "$nvcc_bin" --list-gpu-arch >/dev/null 2>&1; then
			nvcc_list_arch="$("$nvcc_bin" --list-gpu-arch 2>/dev/null | head -n 200 || true)"
			[ "$nvcc_list_arch" != "" ] && printf "%s\n" "$nvcc_list_arch"
		else
			echo "nvcc --list-gpu-arch not supported"
		fi
		echo
		echo "== nvcc supported gpu code (capped) =="
		if "$nvcc_bin" --list-gpu-code >/dev/null 2>&1; then
			nvcc_list_code="$("$nvcc_bin" --list-gpu-code 2>/dev/null | head -n 200 || true)"
			[ "$nvcc_list_code" != "" ] && printf "%s\n" "$nvcc_list_code"
			if [ "${nvcc_arch:-}" != "" ] && [ "$nvcc_list_code" != "" ]; then
				if printf "%s\n" "$nvcc_list_code" | grep -qx "$nvcc_arch"; then
					:
				else
					echo "warning: selected nvcc arch $nvcc_arch not listed in nvcc --list-gpu-code"
				fi
			fi
		else
			echo "nvcc --list-gpu-code not supported"
		fi
	else
		if [ "${nvcc_arch:-}" != "" ]; then
			if "$nvcc_bin" --list-gpu-code >/dev/null 2>&1; then
				if "$nvcc_bin" --list-gpu-code 2>/dev/null | tr -d "\r" | grep -qx "$nvcc_arch"; then
					echo "nvcc supports gpu code: $nvcc_arch"
				else
					echo "warning: selected nvcc arch $nvcc_arch not listed in nvcc --list-gpu-code"
				fi
			fi
		fi
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
cuda_json_ver=""
if [ -r /usr/local/cuda/version.json ]; then
	if command -v python3 >/dev/null 2>&1; then
		cuda_json_ver="$(python3 - <<'PY' 2>/dev/null || true
import json,sys,re
p="/usr/local/cuda/version.json"
try:
    d=json.load(open(p))
except Exception:
    sys.exit(0)
v=""
if isinstance(d,dict):
    cuda=d.get("cuda")
    if isinstance(cuda,dict):
        v=cuda.get("version","")
    elif isinstance(cuda,str):
        v=cuda
    if not v and isinstance(d.get("version"),str):
        v=d.get("version","")
if isinstance(v,str):
    m=re.search(r"[0-9]+(?:[.][0-9]+)+",v)
    if m:
        sys.stdout.write(m.group(0))
PY
)"
	fi
	if [ "$cuda_json_ver" = "" ]; then
		cuda_json_ver="$(sed -nE "s/.*\\\"version\\\"[[:space:]]*:[[:space:]]*\\\"([0-9]+(\\.[0-9]+)+)\\\".*/\\1/p" /usr/local/cuda/version.json 2>/dev/null | head -n 1 || true)"
	fi
	if [ "$spark_probe_summary" != "1" ]; then
		echo
		echo "== cuda version.json (capped) =="
		cat /usr/local/cuda/version.json 2>/dev/null | head -n 80 || true
	else
		if [ "$cuda_json_ver" != "" ]; then
			echo
			echo "== cuda version.json (summary) =="
			echo "cuda: $cuda_json_ver"
		fi
	fi
fi
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
echo "== cuda/toolchain facts (summary) =="
[ "$driver_version" != "" ] && echo "driver: $driver_version"
[ "$smi_cuda_ver" != "" ] && echo "smi CUDA: $smi_cuda_ver"
[ "$nvcc_release" != "" ] && echo "nvcc release: $nvcc_release" || echo "nvcc release: (none)"
[ "$cuda_json_ver" != "" ] && echo "cuda version.json: $cuda_json_ver"
[ "$cuda_h_version" != "" ] && echo "cuda.h CUDA_VERSION: $cuda_h_version"
[ "$compute_cap" != "" ] && echo "compute_cap: $compute_cap" || echo "compute_cap: (unknown)"
[ "$nvcc_arch" != "" ] && echo "nvcc arch: $nvcc_arch" || echo "nvcc arch: default"
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
	int cc = 0,max_cc = -1,max_cc_major = 0,max_cc_minor = 0;
	int runtime_v = 0,driver_v = 0;
	int drv_major = 0,drv_minor = 0,rt_major = 0,rt_minor = 0;
	char pci_bus_id[64];
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
	drv_major = (driver_v / 1000);
	drv_minor = ((driver_v % 1000) / 10);
	rt_major = (runtime_v / 1000);
	rt_minor = ((runtime_v % 1000) / 10);
	std::printf("cuda driver api version: %d (%d.%d)\n",driver_v,drv_major,drv_minor);
	std::printf("cuda runtime api version: %d (%d.%d)\n",runtime_v,rt_major,rt_minor);
	for (dev=0; dev<device_count; dev++)
	{
		if ( cudaGetDeviceProperties(&prop,dev) != cudaSuccess )
		{
			std::printf("cudaGetDeviceProperties failed for dev %d\n",dev);
			return(2);
		}
		cc = ((prop.major * 100) + prop.minor);
		if ( cc > max_cc )
		{
			max_cc = cc;
			max_cc_major = prop.major;
			max_cc_minor = prop.minor;
		}
		std::printf("device%d name: %s\n",dev,prop.name);
		std::printf("device%d cc: %d.%d\n",dev,prop.major,prop.minor);
		std::printf("device%d global mem (bytes): %llu\n",dev,(unsigned long long)prop.totalGlobalMem);
		std::printf("device%d sms: %d\n",dev,prop.multiProcessorCount);
		pci_bus_id[0] = 0;
		if ( cudaDeviceGetPCIBusId(pci_bus_id,(int)sizeof(pci_bus_id),dev) == cudaSuccess )
			std::printf("device%d pci bus id: %s\n",dev,pci_bus_id);
		else
			std::printf("device%d pci bus id: (unavailable)\n",dev);
	}
	if ( max_cc >= 0 )
		std::printf("runtime max cc: %d.%d\n",max_cc_major,max_cc_minor);
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
			rtmax="$(printf "%s\n" "$out" | sed -nE "s/^runtime max cc: ([0-9]+)[.]([0-9]+)/\\1.\\2/p" | head -n 1)"
			if [ "$rtmax" = "" ]; then
				rtmax="$(printf "%s\n" "$out" | sed -nE "s/^device[0-9]+ cc: ([0-9]+)[.]([0-9]+)/\\1.\\2/p" | awk -F. "{ v=(\$1*100)+\$2; if ( v > best ) { best=v; bestc=\$0; } } END { if ( bestc != \"\" ) print bestc; }")"
			fi
			cc0="$(printf "%s\n" "$out" | sed -nE "s/^device0 cc: ([0-9]+)[.]([0-9]+)/\\1.\\2/p" | head -n 1)"
			if [ "$rtmax" != "" ] && [ "$rtmax" != "$compute_cap" ]; then
				echo "warning: compute_cap $compute_cap != runtime max cc $rtmax"
			fi
			if [ "$cc0" != "" ] && [ "$cc0" != "$compute_cap" ]; then
				echo "warning: compute_cap $compute_cap != runtime device0 cc $cc0"
			fi
		fi
		echo
		emit_pcie_link ", post-load"
		echo
		if [ "$spark_probe_summary" != "1" ]; then
			emit_sysfs_pcie_link ", post-load"
		else
			emit_sysfs_pcie_link_summary ", post-load"
		fi
		echo
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
echo "== network links (no IPs) =="
ip -d -br link 2>/dev/null || ip -br link 2>/dev/null || true
if command -v ethtool >/dev/null 2>&1; then
	ifaces="$(ip -br link 2>/dev/null | awk '"'"'$1 != "lo" && ($2 == "UP" || $2 == "UNKNOWN") { print $1 }'"'"' | tr '"'"'\n'"'"' '"'"' '"'"' || true)"
	for iface in $ifaces; do
		echo "-- ethtool $iface --"
		ethtool "$iface" 2>/dev/null | grep -E "^(Settings for|\\s*Speed:|\\s*Duplex:|\\s*Auto-negotiation:|\\s*Link detected:)" || true
		ethtool -i "$iface" 2>/dev/null | grep -E "^(driver:|version:|firmware-version:|bus-info:)" || true
	done
fi
echo
if [ "$spark_probe_facts" != "1" ]; then
	echo "== network =="
	ip -br -4 addr 2>/dev/null || ip -brief addr 2>/dev/null || ip addr || true
	ip -4 route 2>/dev/null || ip route || true
	ip -6 route 2>/dev/null || true
	echo
fi
if [ "$spark_probe_summary" != "1" ]; then
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
fi
echo "== filesystems (type + opts) =="
if command -v findmnt >/dev/null 2>&1; then
	findmnt -no TARGET,FSTYPE,OPTIONS / /home 2>/dev/null || findmnt -no TARGET,FSTYPE,OPTIONS / 2>/dev/null || true
else
	echo "findmnt not found"
fi
echo
echo "== storage =="
if [ "$spark_probe_facts" != "1" ]; then
	df -h / /home 2>/dev/null | awk '"'"'NR==1 {print; next} !seen[$1]++ {print}'"'"' || df -h / || true
	if [ "$spark_probe_summary" != "1" ]; then
		lsblk_out="$(lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS -e 7 2>/dev/null || true)"
		if [ "$lsblk_out" != "" ]; then
			printf "%s\n" "$lsblk_out"
		else
			lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS 2>/dev/null | awk '"'"'NR==1 {print; next} $1 !~ /^loop/'"'"' || true
		fi
		echo
	fi
fi
echo "== disks (summary) =="
disks_out="$(lsblk -d -o NAME,SIZE,MODEL,ROTA,TYPE -e 7 2>/dev/null || true)"
if [ "$disks_out" != "" ]; then
	printf "%s\n" "$disks_out" | head -n 20 || true
else
	lsblk -d -o NAME,SIZE,MODEL,ROTA,TYPE 2>/dev/null | awk '"'"'NR==1 {print; next} $1 !~ /^loop/'"'"' | head -n 20 || true
fi
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
	' 2>&1
		then
			:
		else
			rc="$?"
			echo "ssh: failed rc=$rc"
			ssh_fail=$((ssh_fail + 1))
		fi
		echo
	done
	if [ "$ssh_fail" != "0" ]; then
		echo "== probe summary =="
		echo "ssh failures: $ssh_fail"
	fi
} >"$tmp"

if [ "${REDACT:-0}" = "1" ]; then
	sed -E \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4>\4/g' \
		-e 's/([0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}/<redacted-mac>/g' \
		-e 's/(^|[^0-9A-Za-z_.-])([0-9A-Fa-f:]*::[0-9A-Fa-f:]*)([^0-9A-Za-z_.-]|$)/\1<redacted-ipv6>\3/g' \
		-e 's/([0-9A-Fa-f]{0,4}:){3,7}[0-9A-Fa-f]{0,4}/<redacted-ipv6>/g' \
		-e 's/UUID: [^)]*/UUID: <redacted-gpu-uuid>/g' \
		-e 's/GPU-[0-9A-Fa-f-]{36}/<redacted-gpu-uuid>/g' \
		"$tmp"
else
	cat "$tmp"
fi

if [ "${ssh_fail:-0}" != "0" ]; then
	exit 1
fi
