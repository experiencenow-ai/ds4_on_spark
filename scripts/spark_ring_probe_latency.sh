#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: spark_ring_probe_latency.sh [user@host ...]

Mac-side best-effort latency probe for Spark hosts. Non-destructive.

What it does:
  - Measures wall-clock time for a tiny non-interactive SSH command (`true`).
  - Reports per-target p50/min/max/avg based on LAT_ITERS samples.

Notes:
  - This is NOT ICMP ping. It includes TCP + SSH handshake overhead.
  - Use this when ICMP is blocked/flaky but SSH key auth works.

Defaults:
  - Targets: aitopatom-9ab9.local spark1.local spark2.local
  - LAT_ITERS: 3

Environment:
  SPARK_SSH_USER        Default SSH username for host-only args (default: spark0)
  SSH_OPTS              Extra ssh options (default includes BatchMode + temp known_hosts)
  SSH_WALL_TIMEOUT       Wall-clock timeout for each SSH attempt (seconds; default: 45). Requires `timeout` on the Mac.
  SPARK_KNOWN_HOSTS     SSH known_hosts path (default: /private/tmp/ds4_spark_known_hosts)
  SPARK_KNOWN_HOSTS_PER_HOST=1  Use per-target known_hosts when SPARK_KNOWN_HOSTS is unset
  DS4_GIT_DIR           Optional git dir override for printing `git: <hash>`
  DS4_GIT_WORK_TREE     Optional work tree override (defaults to $PWD)
  REDACT=1              Redact IPv4/IPv6/MAC addresses from output (mostly irrelevant here)
  LAT_ITERS             Number of SSH samples per target (default: 3)
  LAT_WARMUP=1          Run an un-timed SSH warm-up per target (default: 1)

Examples:
  LAT_ITERS=5 REDACT=1 SPARK_KNOWN_HOSTS_PER_HOST=1 ./scripts/spark_ring_probe_latency.sh spark0@aitopatom-9ab9.local
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
LAT_ITERS="${LAT_ITERS:-3}"
LAT_WARMUP="${LAT_WARMUP:-1}"
SSH_WALL_TIMEOUT="${SSH_WALL_TIMEOUT:-45}"

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

run_ssh()
{
	kh="$1"
	shift 1
	if command -v timeout >/dev/null 2>&1; then
		timeout "${SSH_WALL_TIMEOUT}s" ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$@"
	else
		ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$@"
	fi
	return $?
}

tmpdir="$(mktemp -d /private/tmp/ds4_spark_ring_probe_lat.XXXXXX)"
trap 'rm -rf "$tmpdir"' EXIT INT HUP TERM

measure_target()
{
	target="$1"
	kh="$2"
	out_samples="$3"
	i=0
	rm -f "$out_samples"
	if [ "$LAT_WARMUP" = "1" ]; then
		set +e
		warm_out="$(run_ssh "$kh" "$target" 'true' 2>&1 >/dev/null)"
		warm_rc="$?"
		if [ "$warm_rc" -ne 0 ]; then
			class="$(ssh_classify_err "$warm_out")"
			if [ "$warm_rc" -eq 124 ] || [ "$warm_rc" -eq 137 ]; then
				class="timeout"
			fi
			echo "warmup: failed ($class)"
			printf "%s\n" "$warm_out" | sed -n '1,8p' | sed -E 's/^[[:space:]]+//'
			return 1
		fi
		set -e
	fi
	while [ "$i" -lt "$LAT_ITERS" ]; do
		i=$((i + 1))
		set +e
		if command -v timeout >/dev/null 2>&1; then
			out="$( { /usr/bin/time -p timeout "${SSH_WALL_TIMEOUT}s" ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$target" 'true' >/dev/null; } 2>&1 )"
		else
			out="$( { /usr/bin/time -p ssh $SSH_OPTS -o UserKnownHostsFile="$kh" "$target" 'true' >/dev/null; } 2>&1 )"
		fi
		rc="$?"
		set -e
		if [ "$rc" -ne 0 ]; then
			class="$(ssh_classify_err "$out")"
			if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
				class="timeout"
			fi
			echo "sample $i: failed ($class)"
			printf "%s\n" "$out" | grep -v -E '^(real|user|sys)[[:space:]]' | sed -n '1,8p' | sed -E 's/^[[:space:]]+//'
			return 1
		fi
		real_s="$(printf "%s\n" "$out" | awk '/^real[[:space:]]+/ { print $2; exit }' || true)"
		if [ "$real_s" = "" ]; then
			echo "sample $i: failed (no_real_time)"
			printf "%s\n" "$out" | grep -v -E '^(real|user|sys)[[:space:]]' | sed -n '1,8p' | sed -E 's/^[[:space:]]+//'
			return 1
		fi
		printf "%s\n" "$real_s" >>"$out_samples"
	done
	return 0
}

summarize_samples()
{
	samples_file="$1"
	n="$(wc -l <"$samples_file" | tr -d ' ' 2>/dev/null || echo 0)"
	if [ "$n" -le 0 ]; then
		echo "status: no_samples"
		return 0
	fi
	sort -n "$samples_file" >"${samples_file}.sorted"
	p50_idx=$(((n + 1) / 2))
	p50_s="$(sed -n "${p50_idx}p" "${samples_file}.sorted" 2>/dev/null || true)"
	min_s="$(head -n 1 "${samples_file}.sorted" 2>/dev/null || true)"
	max_s="$(tail -n 1 "${samples_file}.sorted" 2>/dev/null || true)"
	avg_s="$(awk '{ s += $1; n += 1 } END { if (n > 0) printf "%.6f", (s / n); }' "$samples_file" 2>/dev/null || true)"
	p50_ms="$(awk -v v="$p50_s" 'BEGIN{ if (v != "") printf "%.1f", (v * 1000.0); }')"
	min_ms="$(awk -v v="$min_s" 'BEGIN{ if (v != "") printf "%.1f", (v * 1000.0); }')"
	max_ms="$(awk -v v="$max_s" 'BEGIN{ if (v != "") printf "%.1f", (v * 1000.0); }')"
	avg_ms="$(awk -v v="$avg_s" 'BEGIN{ if (v != "") printf "%.1f", (v * 1000.0); }')"
	printf "status: ok (n=%s)\n" "$n"
	printf "ssh_latency_ms_p50: %s\n" "${p50_ms:-}"
	printf "ssh_latency_ms_min: %s\n" "${min_ms:-}"
	printf "ssh_latency_ms_max: %s\n" "${max_ms:-}"
	printf "ssh_latency_ms_avg: %s\n" "${avg_ms:-}"
	return 0
}

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
		echo "lat iters: $LAT_ITERS"
		echo "lat warmup: $LAT_WARMUP"
		echo "ssh opts: $SSH_OPTS"
		echo "ssh wall timeout_s: $SSH_WALL_TIMEOUT"
		for t in $targets; do
			echo "known_hosts: $t -> $(known_hosts_for_target "$t")"
		done
	echo
	for target in $targets; do
		kh="$(known_hosts_for_target "$target")"
		samples="${tmpdir}/samples.$(printf "%s" "$target" | sed -E 's/[^A-Za-z0-9_.-]/_/g')"
		echo "== target: $target =="
		if measure_target "$target" "$kh" "$samples"; then
			summarize_samples "$samples"
		else
			echo "status: failed"
		fi
		echo
	done
} >"${tmpdir}/out.txt"

if [ "${REDACT:-0}" = "1" ]; then
	sed -E \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){2}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){1}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3}\/[0-9]{1,2})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4cidr>\4/g' \
		-e 's/(^|[^0-9A-Za-z_.-])(([0-9]{1,3}[.]){3}[0-9]{1,3})([^0-9A-Za-z_.-]|$)/\1<redacted-ipv4>\4/g' \
		-e 's/([0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}/<redacted-mac>/g' \
		-e 's/(^|[^0-9A-Za-z_.-])([0-9A-Fa-f:]*::[0-9A-Fa-f:]*)([^0-9A-Za-z_.-]|$)/\1<redacted-ipv6>\3/g' \
		-e 's/([0-9A-Fa-f]{0,4}:){3,7}[0-9A-Fa-f]{0,4}/<redacted-ipv6>/g' \
		"${tmpdir}/out.txt"
else
	cat "${tmpdir}/out.txt"
fi
