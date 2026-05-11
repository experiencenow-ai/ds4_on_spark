#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: spark_ring_probe.sh [--topology ring|full] [user@host ...]

Mac-side ring probe wrapper for Spark hosts. Non-destructive.

Defaults:
  - Targets: aitopatom-9ab9.local spark1.local spark2.local
  - Topology: ring (each host pings its ring neighbors)

Environment:
  SPARK_SSH_USER        Default SSH username for host-only args (default: spark0)
  SSH_OPTS             Extra ssh options (default includes BatchMode + temp known_hosts)
  SPARK_KNOWN_HOSTS    SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR          Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE    Optional work tree override (defaults to $PWD)
  REDACT=1             Redact IPv4/IPv6/MAC addresses from output
  RING_PING=1          Enable peer ping checks (default: 1)

Examples:
  SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local
  REDACT=1 ./scripts/spark_ring_probe.sh --topology full spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local
EOF
}

topology="ring"
while [ $# -gt 0 ]; do
	case "$1" in
		--topology)
			topology="${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			break
			;;
	esac
done

case "$topology" in
	ring|full)
		;;
	*)
		echo "invalid --topology: $topology (expected ring|full)" >&2
		exit 2
		;;
esac

SPARK_KNOWN_HOSTS_PER_HOST="${SPARK_KNOWN_HOSTS_PER_HOST:-0}"
SPARK_SSH_USER="${SPARK_SSH_USER:-spark0}"
RING_PING="${RING_PING:-1}"

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

host_only()
{
	t="$1"
	case "$t" in
		*@*)
			printf "%s" "${t#*@}"
			;;
		*)
			printf "%s" "$t"
			;;
	esac
}

targets=""
if [ "$#" -eq 0 ]; then
	targets="$(normalize_target "aitopatom-9ab9.local") $(normalize_target "spark1.local") $(normalize_target "spark2.local")"
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

count_targets()
{
	n=0
	for _t in $targets; do
		n=$((n + 1))
	done
	echo "$n"
	return 0
}

nth_target()
{
	want="$1"
	i=0
	for t in $targets; do
		i=$((i + 1))
		if [ "$i" -eq "$want" ]; then
			echo "$t"
			return 0
		fi
	done
	echo ""
	return 0
}

peer_hosts_for_index()
{
	idx="$1"
	n="$(count_targets)"
	if [ "$n" -le 1 ]; then
		echo ""
		return 0
	fi
	if [ "$topology" = "full" ] || [ "$n" -eq 2 ]; then
		peers=""
		j=0
		for t in $targets; do
			j=$((j + 1))
			if [ "$j" -ne "$idx" ]; then
				peers="$peers $(host_only "$t")"
			fi
		done
		echo "$peers" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//'
		return 0
	fi
	next=$((idx + 1))
	prev=$((idx - 1))
	if [ "$next" -gt "$n" ]; then
		next=1
	fi
	if [ "$prev" -lt 1 ]; then
		prev="$n"
	fi
	p1="$(host_only "$(nth_target "$prev")")"
	p2="$(host_only "$(nth_target "$next")")"
	if [ "$p1" = "$p2" ]; then
		echo "$p1"
	else
		echo "$p1 $p2"
	fi
	return 0
}

tmp="$(mktemp /private/tmp/ds4_spark_ring_probe.XXXXXX)"
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
	echo "topology: $topology"
	echo "ssh opts: $SSH_OPTS"
	for t in $targets; do
		echo "known_hosts: $t -> $(known_hosts_for_target "$t")"
	done
	echo

	ssh_fail="0"
	i=0
	for target in $targets; do
		i=$((i + 1))
		kh="$(known_hosts_for_target "$target")"
		peers="$(peer_hosts_for_index "$i")"
		echo "== target: $target =="
		if ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$target" sh -s -- "$RING_PING" $peers 2>&1 <<'REMOTE'
set -eu
export LANG=C LC_ALL=C
export TERM=dumb
ring_ping="${1:-0}"
shift || true
echo "== probe meta =="
date -u
echo "target user: $(id -un 2>/dev/null || true)"
echo
echo "== identity =="
hostname
uname -a
echo
echo "== clock =="
date -u +"utc: %Y-%m-%dT%H:%M:%SZ"
date -u +"epoch: %s"
if command -v timedatectl >/dev/null 2>&1; then
	timedatectl show -p NTPSynchronized -p SystemClockSynchronized -p NTPService -p TimeUSec 2>/dev/null || true
fi
echo
echo "== network (links + addrs, compact) =="
if command -v ip >/dev/null 2>&1; then
	ip -br link 2>/dev/null || true
	echo
	echo "== network (mtu, compact) =="
	ip -o link show 2>/dev/null | awk '{
		name=$2
		sub(/:$/, "", name)
		if ( name == "lo" )
			next
		mtu=""
		state=""
		for (i=1; i<=NF; i++) {
			if ( $i == "mtu" )
				mtu=$(i+1)
			if ( $i == "state" )
				state=$(i+1)
		}
		if ( mtu == "" )
			mtu="?"
		if ( state == "" )
			state="?"
		printf "%s mtu=%s state=%s\n", name, mtu, state
	}' | head -n 80 || true
	echo
	ip -4 -br addr 2>/dev/null || true
	echo
	ip -6 -br addr 2>/dev/null || true
	echo
	ip route show default 2>/dev/null || true
	ip -6 route show default 2>/dev/null || true
else
	echo "ip not found"
fi
echo
echo "== storage (df, lsblk model/size) =="
df -h 2>/dev/null | head -n 60 || true
if command -v lsblk >/dev/null 2>&1; then
	lsblk -o NAME,TYPE,SIZE,MODEL,MOUNTPOINT,FSTYPE 2>/dev/null | head -n 120 || true
fi
echo
echo "== gpu/toolchain facts (compact) =="
if command -v nvidia-smi >/dev/null 2>&1; then
	(nvidia-smi --version 2>/dev/null || nvidia-smi -V 2>/dev/null || true) | sed -E "/^ERROR:/d" | head -n 20 || true
	echo "columns: index,gpu_name,pci.bus_id,driver_version,compute_cap,memory.total"
	q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,compute_cap,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
	if [ "$q" != "" ]; then
		echo "$q"
	else
		echo "columns: index,gpu_name,pci.bus_id,driver_version,memory.total"
		q="$(nvidia-smi --query-gpu=index,gpu_name,pci.bus_id,driver_version,memory.total --format=csv,noheader,nounits 2>/dev/null || true)"
		[ "$q" != "" ] && echo "$q"
	fi
else
	echo "nvidia-smi not found"
fi
nvcc_path="$(command -v nvcc 2>/dev/null || true)"
if [ "$nvcc_path" = "" ] && [ -x /usr/local/cuda/bin/nvcc ]; then
	nvcc_path="/usr/local/cuda/bin/nvcc"
fi
echo "nvcc path: $nvcc_path"
[ "$nvcc_path" != "" ] && "$nvcc_path" --version 2>/dev/null | head -n 5 || true
if [ -r /usr/local/cuda/version.json ]; then
	cuda_ver="$(sed -nE "s/^[[:space:]]*\\\"cuda\\\"[[:space:]]*:[[:space:]]*\\\"([^\\\"]+)\\\".*/\\1/p" /usr/local/cuda/version.json | head -n 1 || true)"
	[ "$cuda_ver" != "" ] && echo "cuda version.json cuda: $cuda_ver"
fi
echo
	if [ "$ring_ping" = "1" ]; then
		echo "== peer ping (best effort, rtt) =="
		if [ "$#" -eq 0 ]; then
			echo "peers: (none)"
		else
			echo "peers: $*"
			for peer in "$@"; do
				out=""
				if out="$(ping -c 3 -W 1 "$peer" 2>&1)"; then
					status="ping_ok"
				else
					status="ping_failed"
				fi
				loss="$(printf "%s\n" "$out" | awk '/packets transmitted/ { for (i=1; i<=NF; i++) if ($i ~ /%/) { print $i; exit } }' || true)"
				rtt="$(printf "%s\n" "$out" | awk -F' = ' '/^rtt / { print $2; exit }' | sed -E 's/ ms$//' || true)"
				printf "%s: %s" "$peer" "$status"
				[ "$loss" != "" ] && printf " loss=%s" "$loss"
				[ "$rtt" != "" ] && printf " rtt_ms=%s" "$rtt"
				echo
			done
		fi
	fi
REMOTE
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
		"$tmp"
else
	cat "$tmp"
fi

if [ "${ssh_fail:-0}" != "0" ]; then
	exit 1
fi
