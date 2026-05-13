#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_tp23_readiness.sh -- safe DS4 TP=2 + TP=3 readiness checks (transition helper)

Usage:
  ops_tp23_readiness.sh --self <name> [--strict] [--strict-tp2] [--strict-tp3] \
    [--peer <host>] [--peer-ssh <user@host>] \
    [--topology ring|full] [--hosts <h0,h1,h2>] [--tcp <port>]... \
    [--env <path>]...

Notes:
  - Non-destructive; does not require sudo.
  - Runs ops_tp2_readiness.sh then ops_tp3_readiness.sh using the same env inputs.
  - Intended for TP=2 -> TP=3 transition periods where you want both sets of checks.
EOF
}

self=""
strict_all=0
strict_tp2=0
strict_tp3=0
peer=""
peer_ssh=""
topology="ring"
hosts_csv=""
tcp_ports=""
env_paths=""

while [ $# -gt 0 ]; do
	case "$1" in
		--self)
			self="${2:-}"
			shift 2
			;;
		--strict)
			strict_all=1
			shift
			;;
		--strict-tp2)
			strict_tp2=1
			shift
			;;
		--strict-tp3)
			strict_tp3=1
			shift
			;;
		--peer)
			peer="${2:-}"
			shift 2
			;;
		--peer-ssh)
			peer_ssh="${2:-}"
			shift 2
			;;
		--topology)
			topology="${2:-}"
			shift 2
			;;
		--hosts)
			hosts_csv="${2:-}"
			shift 2
			;;
		--tcp)
			tcp_ports="$tcp_ports ${2:-}"
			shift 2
			;;
		--env)
			env_paths="$env_paths ${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "unknown arg: $1" >&2
			usage >&2
			exit 2
			;;
	esac
done

if [ "$self" = "" ]; then
	echo "--self is required" >&2
	usage >&2
	exit 2
fi

case "$topology" in
	ring|full)
		;;
	*)
		echo "invalid --topology: $topology (expected ring|full)" >&2
		exit 2
		;;
esac

scripts_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
tp2="$scripts_dir/ops_tp2_readiness.sh"
tp3="$scripts_dir/ops_tp3_readiness.sh"

if [ ! -x "$tp2" ]; then
	echo "missing executable: $tp2" >&2
	exit 2
fi
if [ ! -x "$tp3" ]; then
	echo "missing executable: $tp3" >&2
	exit 2
fi

tp2_fail=0
tp3_fail=0

set -- "$tp2" --self "$self"
if [ "$peer" != "" ]; then
	set -- "$@" --peer "$peer"
fi
if [ "$peer_ssh" != "" ]; then
	set -- "$@" --peer-ssh "$peer_ssh"
fi
if [ "$strict_all" -ne 0 ] || [ "$strict_tp2" -ne 0 ]; then
	set -- "$@" --strict
fi
if [ "$env_paths" != "" ]; then
	for p in $env_paths; do
		set -- "$@" --env "$p"
	done
fi
if ! "$@"; then
	tp2_fail=1
fi

set -- "$tp3" --self "$self" --topology "$topology"
if [ "$hosts_csv" != "" ]; then
	set -- "$@" --hosts "$hosts_csv"
fi
if [ "$tcp_ports" != "" ]; then
	for p in $tcp_ports; do
		set -- "$@" --tcp "$p"
	done
fi
if [ "$strict_all" -ne 0 ] || [ "$strict_tp3" -ne 0 ]; then
	set -- "$@" --strict
fi
if [ "$env_paths" != "" ]; then
	for p in $env_paths; do
		set -- "$@" --env "$p"
	done
fi
if ! "$@"; then
	tp3_fail=1
fi

if [ "$tp2_fail" -ne 0 ] || [ "$tp3_fail" -ne 0 ]; then
	echo "tp23: readiness failed (tp2=$tp2_fail tp3=$tp3_fail)" >&2
	exit 1
fi

echo "tp23: ok"
