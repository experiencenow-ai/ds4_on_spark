#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: spark_ring_probe.sh [user@host ...]

Runs a compact, ring-focused probe across multiple Spark hosts. Intended for
Spark0/Spark1/Spark2/Spark3 bring-up and readiness tracking.

Environment:
  SPARK_SSH_USER               Default SSH username for host-only args (default: spark0)
  SSH_OPTS                    Extra ssh options (default includes BatchMode + temp known_hosts)
  SPARK_KNOWN_HOSTS           SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR                 Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE           Optional work tree override (defaults to $PWD)
  REDACT=1                    Redact IPv4/IPv6/MAC addresses (recommended for committed excerpts)
  SPARK_RING_PING_MATRIX=1    Run best-effort ICMP matrix from each host to every other host-only target
  SPARK_RING_PING_COUNT       Ping count (default: 2)
  SPARK_RING_PING_TIMEOUT     Ping timeout seconds (default: 1)

Examples:
  SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_ring_probe.sh aitopatom-9ab9.local spark1.local spark2.local spark3.local || true
  SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 SPARK_RING_PING_MATRIX=1 ./scripts/spark_ring_probe.sh spark0@aitopatom-9ab9.local spark0@spark1.local || true

Notes:
  - The script continues past SSH failures and prints a `== ring summary ==`.
  - Exit status is non-zero if any target failed; append `|| true` when saving partial output.
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
SPARK_RING_PING_MATRIX="${SPARK_RING_PING_MATRIX:-0}"
SPARK_RING_PING_COUNT="${SPARK_RING_PING_COUNT:-2}"
SPARK_RING_PING_TIMEOUT="${SPARK_RING_PING_TIMEOUT:-1}"

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
	targets="$(normalize_target "aitopatom-9ab9.local") $(normalize_target "spark1.local") $(normalize_target "spark2.local") $(normalize_target "spark3.local")"
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

tmp="$(mktemp /private/tmp/ds4_spark_ring_probe.XXXXXX)"
trap 'rm -f "$tmp"' EXIT INT HUP TERM

host_only_targets=""
for t in $targets; do
	h="${t#*@}"
	if [ "$host_only_targets" = "" ]; then
		host_only_targets="$h"
	else
		host_only_targets="$host_only_targets $h"
	fi
done

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
	echo "host-only targets: $host_only_targets"
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
spark_ring_ping_matrix='"$SPARK_RING_PING_MATRIX"'
spark_ring_ping_count='"$SPARK_RING_PING_COUNT"'
spark_ring_ping_timeout='"$SPARK_RING_PING_TIMEOUT"'
host_only_targets="'"$host_only_targets"'"
echo "== meta =="
date -u
echo "target user: $(id -un 2>/dev/null || true)"
echo
echo "== identity =="
hostname
uname -a
uptime 2>/dev/null || true
echo
echo "== clock =="
if command -v timedatectl >/dev/null 2>&1; then
	timedatectl status 2>/dev/null | awk '"'"'/^[[:space:]]*(Local time:|Universal time:|RTC time:|Time zone:|System clock synchronized:|NTP service:|RTC in local TZ:)/ {print}'"'"' || true
fi
if command -v chronyc >/dev/null 2>&1; then
	echo "-- chronyc tracking --"
	chronyc tracking 2>/dev/null | head -n 50 || true
fi
echo "-- date epoch --"
date +%s
echo
echo "== network (summary) =="
if command -v ip >/dev/null 2>&1; then
	ip -br link 2>/dev/null | head -n 80 || ip link show 2>/dev/null | head -n 120 || true
	echo
	ip -br addr 2>/dev/null | head -n 120 || ip addr show 2>/dev/null | head -n 200 || true
fi
echo
echo "== mtu (all links) =="
if command -v ip >/dev/null 2>&1; then
	ip -o link 2>/dev/null | awk '"'"'{for(i=1;i<=NF;i++){if($i=="mtu"){print $(2) " mtu " $(i+1)}}}'"'"' | head -n 200 || true
fi
echo
echo "== storage (non-secret) =="
if command -v lsblk >/dev/null 2>&1; then
	echo "-- lsblk (disks) --"
	(lsblk -d -o NAME,TYPE,SIZE,MODEL 2>/dev/null | head -n 80) || (lsblk -d 2>/dev/null | head -n 80) || true
	echo "-- lsblk (mounts, no loops) --"
	(lsblk -o NAME,TYPE,SIZE,MODEL,MOUNTPOINT 2>/dev/null | awk '"'"'NR==1 || $1 !~ /^loop/ {print}'"'"' | head -n 200) || true
fi
echo
echo "== gpu (non-secret) =="
if command -v nvidia-smi >/dev/null 2>&1; then
	nvidia-smi --version 2>/dev/null || nvidia-smi -h 2>/dev/null | head -n 30 || true
	q="$(nvidia-smi --query-gpu=index,name,compute_cap,pci.bus_id,driver_version --format=csv,noheader 2>/dev/null || true)"
	if [ "$q" != "" ] && ! printf "%s" "$q" | grep -qi "not a valid field"; then
		echo "$q"
	else
		q="$(nvidia-smi --query-gpu=index,name,pci.bus_id,driver_version --format=csv,noheader 2>/dev/null || true)"
		[ "$q" != "" ] && echo "$q"
		echo "note: nvidia-smi compute_cap field not supported; use scripts/spark_probe.sh for per-host cc"
	fi
fi
echo
if [ "$spark_ring_ping_matrix" = "1" ]; then
	echo "== ping matrix (best-effort) =="
	self="$(hostname 2>/dev/null || true)"
	for peer in $host_only_targets; do
		if [ "$peer" = "" ]; then
			continue
		fi
		if [ "$peer" = "$self" ]; then
			continue
		fi
		printf "%s -> %s: " "$self" "$peer"
		ping -c "$spark_ring_ping_count" -W "$spark_ring_ping_timeout" "$peer" >/dev/null 2>&1 && echo "ok" || echo "fail"
	done
fi
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
		echo "== ring summary =="
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
