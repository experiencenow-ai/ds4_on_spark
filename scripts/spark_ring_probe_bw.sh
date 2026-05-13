#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: spark_ring_probe_bw.sh [user@host ...]

Mac-side bandwidth probe for Spark hosts. Non-destructive.

What it does:
  - Measures best-effort one-way throughput for each target:
    - down: remote -> mac (remote `dd if=/dev/zero` piped to mac `dd of=/dev/null`)
    - up:   mac -> remote (mac `dd if=/dev/zero` piped to remote `dd of=/dev/null`)

Defaults:
  - Targets: aitopatom-9ab9.local spark1.local spark2.local
  - Transfer size: 64 MiB each direction (override with BW_MB)

Environment:
  SPARK_SSH_USER        Default SSH username for host-only args (default: spark0)
  SSH_OPTS              Extra ssh options (default includes BatchMode + temp known_hosts)
  SSH_WALL_TIMEOUT       Wall-clock timeout for each SSH attempt (seconds; default: 45). Requires `timeout` or `gtimeout` (coreutils) on the Mac.
  SPARK_KNOWN_HOSTS     SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR           Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE     Optional work tree override (defaults to $PWD)
  REDACT=1              Redact IPv4/IPv6/MAC addresses from output
  BW_MB                 Transfer size in MiB (default: 64)
  BW_DIR                Which directions to run: both|down|up (default: both)

Examples:
  BW_MB=16 REDACT=1 SPARK_SSH_USER=spark0 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_ring_probe_bw.sh aitopatom-9ab9.local
  BW_MB=8 REDACT=1 ./scripts/spark_ring_probe_bw.sh spark0@aitopatom-9ab9.local spark0@spark1.local || true
EOF
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

SPARK_KNOWN_HOSTS_PER_HOST="${SPARK_KNOWN_HOSTS_PER_HOST:-0}"
SPARK_SSH_USER="${SPARK_SSH_USER:-spark0}"
BW_MB="${BW_MB:-64}"
BW_DIR="${BW_DIR:-both}"
SSH_WALL_TIMEOUT="${SSH_WALL_TIMEOUT:-45}"
TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
	TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
	TIMEOUT_BIN="gtimeout"
fi

case "$BW_DIR" in
	both|down|up)
		;;
	*)
		echo "invalid BW_DIR: $BW_DIR (expected both|down|up)" >&2
		exit 2
		;;
esac

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

run_ssh()
{
	kh="$1"
	shift 1
	if [ "$TIMEOUT_BIN" != "" ]; then
		"$TIMEOUT_BIN" "${SSH_WALL_TIMEOUT}s" ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$@"
	else
		ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$@"
	fi
	return $?
}

ssh_classify_err()
{
	msg="$1"
	case "$msg" in
		*"Could not resolve hostname"*|*"Name or service not known"*|*"Temporary failure in name resolution"*|*"nodename nor servname provided"*)
			echo "resolve_failed"
			;;
		*"No route to host"*|*"Network is unreachable"*)
			echo "no_route"
			;;
		*"Connection timed out"*|*"Operation timed out"*|*"Connection timeout"*)
			echo "timeout"
			;;
		*"Permission denied"*|*"Authentication failed"*)
			echo "auth_failed"
			;;
		*)
			echo "ssh_failed"
			;;
	esac
	return 0
}

bw_annotate_dd_line()
{
	line="$1"
	bytes=""
	secs=""
	bps=""
	if printf "%s\n" "$line" | grep -q "bytes transferred in"; then
		bytes="$(printf "%s\n" "$line" | awk "{ print \$1 }" | head -n 1 || true)"
		secs="$(printf "%s\n" "$line" | awk "{
			for (i=1; i<=NF; i++)
			{
				if ( \$i == \"in\" )
				{
					print \$(i+1);
					exit;
				}
			}
		}" | head -n 1 || true)"
		bps="$(printf "%s\n" "$line" | tr '()' ' ' | awk '{ for (i=1; i<=NF; i++) { if ( $i ~ /^[0-9]+$/ && $(i+1) == "bytes/sec" ) { print $i; exit; } } }' | head -n 1 || true)"
	fi
	if [ "$bytes" = "" ] && printf "%s\n" "$line" | grep -q " copied,"; then
		bytes="$(printf "%s\n" "$line" | awk "{ print \$1 }" | head -n 1 || true)"
		secs="$(printf "%s\n" "$line" | awk -F'copied, ' '{ if (NF >= 2) { print $2 } }' | awk '{ print $1 }' | head -n 1 || true)"
		if [ "$bytes" != "" ] && [ "$secs" != "" ]; then
			bps="$(awk -v b="$bytes" -v s="$secs" 'BEGIN{ if (s > 0) printf "%.0f", (b / s); }')"
		fi
	fi
	if [ "$bps" != "" ]; then
		mib_s="$(awk -v v="$bps" 'BEGIN{ printf "%.1f", (v / 1048576.0); }')"
		mbit_s="$(awk -v v="$bps" 'BEGIN{ printf "%.1f", ((v * 8.0) / 1000000.0); }')"
		printf "%s [MiB/s=%s Mbit/s=%s]" "$line" "$mib_s" "$mbit_s"
	else
		printf "%s" "$line"
	fi
	return 0
}

tmp="$(mktemp /private/tmp/ds4_spark_ring_probe_bw.XXXXXX)"
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
		if [ "$git_dir" = "" ] && [ -r "$git_worktree/.git" ] && [ ! -d "$git_worktree/.git" ]; then
			worktree_gitdir="$(sed -nE 's/^gitdir:[[:space:]]*(.*)/\1/p' "$git_worktree/.git" | head -n 1 || true)"
			if [ "$worktree_gitdir" != "" ] && [ -r "$worktree_gitdir/commondir" ]; then
				common_rel="$(cat "$worktree_gitdir/commondir" 2>/dev/null || true)"
				if [ "$common_rel" != "" ]; then
					common_abs="$(cd "$worktree_gitdir" 2>/dev/null && cd "$common_rel" 2>/dev/null && pwd -P 2>/dev/null || true)"
					if [ "$common_abs" != "" ] && [ -r "$common_abs/HEAD" ]; then
						git_dir="$common_abs"
					fi
				fi
			fi
		fi
		git_hash=""
		if [ "$git_dir" != "" ]; then
			git_hash="$(git --git-dir="$git_dir" --work-tree="$git_worktree" rev-parse --short HEAD 2>/dev/null || true)"
		fi
		[ "$git_hash" != "" ] && echo "git: $git_hash" || echo "git: (unknown)"
	fi
	echo "probe args: $probe_args"
	echo "resolved targets: $targets"
	echo "bw mb: $BW_MB"
	echo "bw dir: $BW_DIR"
	echo "ssh opts: $SSH_OPTS"
	echo "ssh wall timeout_s: $SSH_WALL_TIMEOUT"
	for t in $targets; do
		echo "known_hosts: $t -> $(known_hosts_for_target "$t")"
	done
	echo

	ssh_fail="0"
	for target in $targets; do
		kh="$(known_hosts_for_target "$target")"
		echo "== target: $target =="

		if [ "$BW_DIR" = "both" ] || [ "$BW_DIR" = "down" ]; then
			printf "down (remote->mac) %s MiB: " "$BW_MB"
			ssh_err="$(mktemp /private/tmp/ds4_spark_ring_probe_bw.ssherr.XXXXXX)"
			dd_line_tmp="$(mktemp /private/tmp/ds4_spark_ring_probe_bw.ddline.XXXXXX)"
				run_ssh "$kh" "$target" sh -s -- "$BW_MB" 2>"$ssh_err" <<-'REMOTE' | dd of=/dev/null bs=1M 2>&1 | tail -n 1 >"$dd_line_tmp" || true
					set -eu
					mb="${1:-64}"
					dd if=/dev/zero bs=1M count="$mb" 2>/dev/null
REMOTE
			dd_line="$(cat "$dd_line_tmp" 2>/dev/null || true)"
			bytes="$(printf "%s\n" "$dd_line" | awk '{ print $1 }' || true)"
			if [ "$bytes" != "" ] && [ "$bytes" != "0" ]; then
				bw_annotate_dd_line "$dd_line"
				echo
			else
				ssh_err_line="$(head -n 2 "$ssh_err" 2>/dev/null | tr '\n' ' ' | sed -E 's/[[:space:]]+$//' || true)"
				ssh_status=""
				if [ "$ssh_err_line" != "" ]; then
					ssh_status="$(ssh_classify_err "$ssh_err_line")"
					echo "ssh status: $ssh_status"
					echo "ssh: $ssh_err_line"
				fi
				[ "$dd_line" != "" ] && echo "dd: $dd_line"
				echo "failed"
				ssh_fail=$((ssh_fail + 1))
			fi
			rm -f "$dd_line_tmp" || true
			rm -f "$ssh_err" || true
		fi

		if [ "$BW_DIR" = "both" ] || [ "$BW_DIR" = "up" ]; then
			printf "up (mac->remote) %s MiB: " "$BW_MB"
			ssh_err_up="$(mktemp /private/tmp/ds4_spark_ring_probe_bw.ssherrup.XXXXXX)"
				up_line="$(dd if=/dev/zero bs=1M count="$BW_MB" 2>/dev/null | run_ssh "$kh" "$target" 'dd of=/dev/null bs=1M 2>&1 | tail -n 1' 2>"$ssh_err_up" || true)"
			if [ "$up_line" != "" ]; then
				bw_annotate_dd_line "$up_line"
				echo
			else
				ssh_err_line="$(head -n 2 "$ssh_err_up" 2>/dev/null | tr '\n' ' ' | sed -E 's/[[:space:]]+$//' || true)"
				if [ "$ssh_err_line" != "" ]; then
					echo "ssh status: $(ssh_classify_err "$ssh_err_line")"
					echo "ssh: $ssh_err_line"
				fi
				echo "failed"
				ssh_fail=$((ssh_fail + 1))
			fi
			rm -f "$ssh_err_up" || true
		fi
		echo
	done

	if [ "$ssh_fail" != "0" ]; then
		echo "== probe summary =="
		echo "failures: $ssh_fail"
	fi
} >"$tmp"

	if [ "${REDACT:-0}" = "1" ]; then
		sed -E \
			-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
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
