#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_ring_ops_check.sh -- Mac-side 3-node ops snapshot (safe)

Usage:
  ops_spark_ring_ops_check.sh [--inventory-file <path>] [--topology ring|full] [--tcp <port>]... [--system|--user] [--preflight tp2|tp3|tp4] [--strict] [--journal [--lines N]] [--staged-env-audit] <spark0_user@host> <spark1_user@host> [spark2_user@host ...]
  ops_spark_ring_ops_check.sh [--inventory-file <path>] [--topology ring|full] [--tcp <port>]... [--system|--user] [--preflight tp2|tp3|tp4] [--strict] [--journal [--lines N]] [--staged-env-audit] --inventory-file <path>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Runs:
      1) mesh checks (ping/route + optional tcp probes) via ops_spark_ring_mesh_check.sh
      2) systemd status snapshot via ops_spark_ring_status.sh
      3) optional staged env audit (requires prior staging) via ops_spark_ring_staged_env_audit.sh
EOF
}

inventory_file=""
topology="ring"
tcp_ports=""
systemd_mode="system"
preflight="auto"
strict=0
with_journal=0
journal_lines=80
staged_env_audit=0

while [ $# -gt 0 ]; do
	case "$1" in
		--inventory-file)
			inventory_file="${2:-}"
			shift 2
			;;
		--topology)
			topology="${2:-}"
			shift 2
			;;
		--tcp)
			tcp_ports="$tcp_ports ${2:-}"
			shift 2
			;;
		--system)
			systemd_mode="system"
			shift
			;;
		--user)
			systemd_mode="user"
			shift
			;;
		--preflight)
			preflight="${2:-}"
			shift 2
			;;
		--strict)
			strict=1
			shift
			;;
		--journal)
			with_journal=1
			shift
			;;
		--lines)
			journal_lines="${2:-}"
			shift 2
			;;
		--staged-env-audit)
			staged_env_audit=1
			shift
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

case "$systemd_mode" in
	system|user)
		;;
	*)
		echo "invalid systemd mode: $systemd_mode (expected system|user)" >&2
		exit 2
		;;
esac

case "$preflight" in
	auto|tp2|tp3|tp4)
		;;
	*)
		echo "invalid --preflight: $preflight (expected auto|tp2|tp3|tp4)" >&2
		exit 2
		;;
esac

case "$journal_lines" in
	''|*[!0-9]*)
		echo "invalid --lines: $journal_lines (expected uint)" >&2
		exit 2
		;;
esac

scripts_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ "$inventory_file" != "" ]; then
	if [ ! -f "$inventory_file" ]; then
		echo "inventory file not found: $inventory_file" >&2
		exit 2
	fi
	while IFS= read -r line || [ "$line" != "" ]; do
		case "$line" in
			""|\#*)
				continue
				;;
		esac
		set -- "$@" "$line"
	done < "$inventory_file"
fi

if [ "$#" -lt 2 ]; then
	usage >&2
	exit 2
fi

echo "== spark ring ops check (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "topology=$topology"
echo "systemd_mode=$systemd_mode"
echo "preflight=$preflight"
echo "strict=$strict"
echo "journal=$with_journal"
echo "journal_lines=$journal_lines"
echo "staged_env_audit=$staged_env_audit"
echo

echo "== mesh check =="
args=""
if [ "$tcp_ports" != "" ]; then
	for p in $tcp_ports; do
		args="$args --tcp $p"
	done
fi
"$scripts_dir/ops_spark_ring_mesh_check.sh" --topology "$topology" $args "$@"
echo

echo "== systemd status snapshot =="
status_args=""
if [ "$systemd_mode" = "user" ]; then
	status_args="$status_args --user"
else
	status_args="$status_args --system"
fi
status_args="$status_args --preflight $preflight"
if [ "$strict" -ne 0 ]; then
	status_args="$status_args --strict"
fi
if [ "$with_journal" -ne 0 ]; then
	status_args="$status_args --journal --lines $journal_lines"
fi
"$scripts_dir/ops_spark_ring_status.sh" $status_args "$@" || true
echo

if [ "$staged_env_audit" -ne 0 ]; then
	echo "== staged env audit (requires prior staging) =="
	"$scripts_dir/ops_spark_ring_staged_env_audit.sh" "$@" || true
	echo
fi

echo "== next =="
echo "readiness rubric: docs/spark-ring-ops-readiness-tp3.md"
echo "operating checklist: docs/spark-ring-ops-checklist-tp3.md"
echo "== done =="

