#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: spark_ring_probe_mtu.sh [--topology ring|full] [user@host ...]

Mac-side MTU probe wrapper for Spark hosts. Non-destructive.

What it does (best-effort):
  - For each reachable host, ping peers with "DF" jumbo payload (IPv4)
  - Reports whether 1500-MTU payload (1472 bytes) and 9000-MTU payload (8972 bytes) succeed

Defaults:
  - Targets: aitopatom-9ab9.local spark1.local spark2.local
  - Topology: ring (each host probes its ring neighbors)

Environment:
  SPARK_SSH_USER        Default SSH username for host-only args (default: spark0)
  SSH_OPTS             Extra ssh options (default includes BatchMode + temp known_hosts)
  SPARK_KNOWN_HOSTS    SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR          Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE    Optional work tree override (defaults to $PWD)
  REDACT=1             Redact IPv4/IPv6/MAC addresses from output
  MTU_PAYLOADS         Override payload list (default: "1472,8972"; comma-separated)

Examples:
  SPARK_SSH_USER=spark0 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_ring_probe_mtu.sh aitopatom-9ab9.local spark1.local spark2.local || true
  REDACT=1 ./scripts/spark_ring_probe_mtu.sh --topology full spark0@aitopatom-9ab9.local spark0@spark1.local spark0@spark2.local || true
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
MTU_PAYLOADS="${MTU_PAYLOADS:-1472,8972}"

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

tmp="$(mktemp /private/tmp/ds4_spark_ring_probe_mtu.XXXXXX)"
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
		git_hash=""
		if [ "$git_dir" != "" ]; then
			git_hash="$(git --git-dir="$git_dir" --work-tree="$git_worktree" rev-parse --short HEAD 2>/dev/null || true)"
		fi
		[ "$git_hash" != "" ] && echo "git: $git_hash" || echo "git: (unknown)"
	fi
	echo "probe args: $probe_args"
	echo "resolved targets: $targets"
	echo "topology: $topology"
	echo "mtu payloads: $MTU_PAYLOADS"
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
		payloads_arg="$(printf "%s" "$MTU_PAYLOADS" | tr ' ' ',' | tr -s ',' | sed -E 's/^,+//; s/,+$//')"
		echo "== target: $target =="
		if ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$target" sh -s -- "$payloads_arg" $peers 2>&1 <<'REMOTE'
set -eu
export LANG=C LC_ALL=C
export TERM=dumb
payloads_csv="${1:-}"
shift || true
echo "== probe meta =="
date -u
echo "target user: $(id -un 2>/dev/null || true)"
echo
echo "== mtu probe (ipv4, df, best effort) =="
if [ "$#" -eq 0 ]; then
	echo "peers: (none)"
	exit 0
fi
echo "peers: $*"

have_m_flag="1"
if ping -h 2>/dev/null | grep -q -- " -M "; then
	:
else
	have_m_flag="0"
fi

classify_ping_fail()
{
	out="$1"
	case "$out" in
		*"Name or service not known"*|*"Temporary failure in name resolution"*|*"unknown host"*)
			echo "resolve_failed"
			;;
		*"No route to host"*|*"Network is unreachable"*)
			echo "no_route"
			;;
		*"Frag needed"*|*"Packet too big"*|*"Message too long"*|*"mtu="*)
			echo "mtu_blocked"
			;;
		*"100% packet loss"*|*"Request timeout"*|*"time out"*)
			echo "timeout"
			;;
		*"Destination Host Unreachable"*|*"Destination Net Unreachable"*)
			echo "unreachable"
			;;
		*)
			echo "fail"
			;;
	esac
	return 0
}

for peer in "$@"; do
	echo "-- $peer --"
	payloads="$(printf "%s" "$payloads_csv" | tr ',' ' ' | tr -s ' ' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
	for sz in $payloads; do
		label="payload=${sz}"
		if [ "$have_m_flag" = "1" ]; then
			if out="$(ping -c 1 -W 1 -M do -s "$sz" "$peer" 2>&1)"; then
				echo "$label: ok"
			else
				echo "$label: fail status=$(classify_ping_fail "$out")"
			fi
		else
			if out="$(ping -c 1 -W 1 -s "$sz" "$peer" 2>&1)"; then
				echo "$label: ok (no DF)"
			else
				echo "$label: fail status=$(classify_ping_fail "$out")"
			fi
		fi
	done
done
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
			-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
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
