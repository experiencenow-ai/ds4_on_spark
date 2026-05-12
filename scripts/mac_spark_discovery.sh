#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: mac_spark_discovery.sh [host...]

Runs lightweight macOS-side discovery for Spark hosts:
- Interface snapshots (en0/en1, no MAC addresses)
- ARP table (MACs stripped)
- Bonjour SSH browse
- Optional mDNS resolution checks for *.local targets
- TCP/22 reachability probes
- Optional ping RTT/loss snapshot (mac->targets, compact)

Environment:
  DS4_GIT_DIR       Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE Optional work tree override (defaults to $PWD)
  REDACT=1    Redact IPv4/IPv6/MAC addresses from output
  PING_CHECK=0  Disable ping RTT/loss checks (default: 1)

Examples:
  ./scripts/mac_spark_discovery.sh
  REDACT=1 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local
  DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. REDACT=1 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local spark2.local
  ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local 10.0.0.2
  ./scripts/mac_spark_discovery.sh spark0@aitopatom-9ab9.local
EOF
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

if [ "$#" -gt 0 ]; then
	targets="$*"
else
	targets="aitopatom-9ab9.local spark1.local spark2.local"
fi

PING_CHECK="${PING_CHECK:-1}"

tmp="$(mktemp /private/tmp/ds4_mac_spark_discovery.XXXXXX)"
trap 'rm -f "$tmp"' EXIT INT HUP TERM

{
echo "== meta =="
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
echo "targets: $targets"
echo
echo "== interfaces =="
for iface in en0 en1; do
	echo "-- $iface --"
	ifconfig "$iface" 2>/dev/null | awk '
		/^[[:space:]]*status:/ { print; next }
		/^[[:space:]]*mtu/ { print; next }
		/^[[:space:]]*inet / { print; next }
		/^[[:space:]]*inet6 / { print; next }
	' || true
done
echo
echo "== routes =="
netstat -rn -f inet 2>/dev/null | head -n 40 || true
netstat -rn -f inet6 2>/dev/null | head -n 40 || true
echo
echo "== arp =="
arp -an 2>/dev/null | sed -E 's/ at [^ ]+ on / on /' || true
echo
echo "== ssh service browse, 5 seconds =="
dns-sd -B _ssh._tcp local &
pid="$!"
sleep 5
kill "$pid" >/dev/null 2>&1 || true
wait "$pid" >/dev/null 2>&1 || true
echo
echo "== mdns resolution, 3 seconds each =="
for host in $targets; do
	host_only="${host#*@}"
	case "$host_only" in
		*.local)
			echo "-- $host_only --"
			dns-sd -G v4v6 "$host_only" &
			pid="$!"
			sleep 3
			kill "$pid" >/dev/null 2>&1 || true
			wait "$pid" >/dev/null 2>&1 || true
			;;
		*)
			;;
	esac
done
echo
echo "== route selection (macOS) =="
for host in $targets; do
	host_only="${host#*@}"
	echo "-- $host_only --"
	if command -v route >/dev/null 2>&1; then
		out="$(route -n get "$host_only" 2>&1 || true)"
		if [ "$out" = "" ]; then
			echo "route: (no output)"
		else
			echo "$out" | awk '
				/^[[:space:]]*(route to:|destination:|gateway:|interface:|ifscope:|flags:|mtu:|recvpipe:|sendpipe:|ssthresh:|rtt,|rttvar:|hopcount:)/ { print; next }
				/^route: / { print; next }
			' | head -n 40 || true
		fi
	else
		echo "route not found"
	fi
done
echo
echo "== known target checks =="
for host in $targets; do
	printf "%s: " "$host"
	host_only="${host#*@}"
	nc -vz -G 2 "$host_only" 22 >/dev/null 2>&1 && echo "ssh reachable" || echo "not reachable"
done
echo
echo "== ping (mac->targets, compact) =="
if [ "$PING_CHECK" = "1" ]; then
	for host in $targets; do
		host_only="${host#*@}"
		printf "%s: " "$host_only"
		out="$(ping -c 3 -n -W 1000 "$host_only" 2>&1 || true)"
		if printf "%s\n" "$out" | grep -qiE '(unknown host|cannot resolve|nodename nor servname provided|not known)'; then
			echo "resolve_failed"
			continue
		fi
		pkt="$(printf "%s\n" "$out" | grep -E "packets transmitted" | tail -n 1 || true)"
		rtt="$(printf "%s\n" "$out" | grep -E "^round-trip" | tail -n 1 || true)"
		if [ "$pkt" = "" ]; then
			echo "ping_failed"
			continue
		fi
		tx="$(printf "%s" "$pkt" | awk '{print $1}' 2>/dev/null || true)"
		rx="$(printf "%s" "$pkt" | awk '{print $4}' 2>/dev/null || true)"
		loss="$(printf "%s" "$pkt" | sed -nE 's/.* ([0-9.]+)% packet loss.*/\1/p' 2>/dev/null || true)"
		avg_ms="$(printf "%s" "$rtt" | sed -nE 's/.*= ([0-9.]+)\/([0-9.]+)\/([0-9.]+)\/([0-9.]+) ms.*/\2/p' 2>/dev/null || true)"
		if [ "$avg_ms" != "" ]; then
			echo "tx=$tx rx=$rx loss=${loss}% rtt_avg_ms=$avg_ms"
		else
			echo "tx=$tx rx=$rx loss=${loss}%"
		fi
	done
else
	echo "disabled (PING_CHECK=0)"
fi
} >"$tmp"

if [ "${REDACT:-0}" = "1" ]; then
	sed -E \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){2}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){1}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4>\4/g' \
		-e 's/([0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}/<redacted-mac>/g' \
		-e 's/(^|[^0-9A-Za-z_.-])([0-9A-Fa-f:]*::[0-9A-Fa-f:]*)([^0-9A-Za-z_.-]|$)/\1<redacted-ipv6>\3/g' \
		-e 's/([0-9A-Fa-f]{0,4}:){3,7}[0-9A-Fa-f]{0,4}/<redacted-ipv6>/g' \
		"$tmp"
else
	cat "$tmp"
fi
