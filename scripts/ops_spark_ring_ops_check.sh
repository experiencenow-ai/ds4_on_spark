#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_ring_ops_check.sh -- Mac-side 3-node ops snapshot (safe)

Usage:
  ops_spark_ring_ops_check.sh [--out <path>] [--inventory-file <path>] [--topology ring|full] [--tcp <port>]... [--system|--user] [--preflight auto|tp2|tp3|tp4] [--strict] [--journal [--lines N]] [--staged-env-audit] [--staged-readiness] [--staged-readiness-strict] [--staged-readiness-preflight auto|tp2|tp3|tp4] [--instance<N> <name>]... <spark0_user@host> <spark1_user@host> [spark2_user@host ...]
  ops_spark_ring_ops_check.sh [--out <path>] [--inventory-file <path>] [--topology ring|full] [--tcp <port>]... [--system|--user] [--preflight auto|tp2|tp3|tp4] [--strict] [--journal [--lines N]] [--staged-env-audit] [--staged-readiness] [--staged-readiness-strict] [--staged-readiness-preflight auto|tp2|tp3|tp4] [--instance<N> <name>]... --inventory-file <path>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - `--out` writes the full snapshot output to a file (and prints it to stdout).
  - For `--preflight auto` (default), picks based on node_count:
      2 => tp2, 3 => tp3, 4 => tp4 (other sizes must pass --preflight explicitly)
  - Runs:
      1) mesh checks (ping/route + optional tcp probes) via ops_spark_ring_mesh_check.sh
      2) systemd status snapshot via ops_spark_ring_status.sh
      3) optional staged env audit (requires prior staging) via ops_spark_ring_staged_env_audit.sh
      4) optional staged readiness (requires prior staging) via ops_spark_ring_staged_readiness.sh
EOF
}

run_main()
{
inventory_file=""
topology="ring"
tcp_ports=""
systemd_mode="system"
preflight="auto"
strict=0
with_journal=0
journal_lines=80
staged_env_audit=0
staged_readiness=0
staged_readiness_strict=0
staged_readiness_preflight="auto"
instance_opts=""
out_path=""

while [ $# -gt 0 ]; do
	case "$1" in
		--out)
			out_path="${2:-}"
			shift 2
			;;
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
		--staged-readiness)
			staged_readiness=1
			shift
			;;
		--staged-readiness-strict)
			staged_readiness=1
			staged_readiness_strict=1
			shift
			;;
		--staged-readiness-preflight)
			staged_readiness=1
			staged_readiness_preflight="${2:-}"
			shift 2
			;;
		--instance[0-9]*)
			idx="${1#--instance}"
			case "$idx" in
				*[!0-9]*|"")
					echo "invalid instance option: $1" >&2
					exit 2
					;;
			esac
			instance_opts="$instance_opts $1 ${2:-}"
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

do_work()
{
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

	case "$staged_readiness_preflight" in
		auto|tp2|tp3|tp4)
			;;
		*)
			echo "invalid --staged-readiness-preflight: $staged_readiness_preflight (expected auto|tp2|tp3|tp4)" >&2
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

	infer_preflight()
	{
		if [ "$preflight" != "auto" ]; then
			echo "$preflight"
			return 0
		fi
		case "$#" in
			2) echo "tp2" ;;
			3) echo "tp3" ;;
			4) echo "tp4" ;;
			*)
				echo "cannot infer --preflight from node_count=$#; pass --preflight tp2|tp3|tp4" >&2
				return 2
				;;
		esac
	}

	picked_preflight="$(infer_preflight "$@")" || exit $?
	picked_staged_preflight="$staged_readiness_preflight"
	if [ "$picked_staged_preflight" = "auto" ]; then
		picked_staged_preflight="$picked_preflight"
	fi

	echo "== spark ring ops check (Mac-side) =="
	date -Is 2>/dev/null || date || true
	echo "topology=$topology"
	echo "systemd_mode=$systemd_mode"
	echo "preflight=$picked_preflight"
	echo "strict=$strict"
	echo "journal=$with_journal"
	echo "journal_lines=$journal_lines"
	echo "staged_env_audit=$staged_env_audit"
	echo "staged_readiness=$staged_readiness"
	echo "staged_readiness_strict=$staged_readiness_strict"
	echo "staged_readiness_preflight=$picked_staged_preflight"
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
	status_args="$status_args --preflight $picked_preflight"
	if [ "$strict" -ne 0 ]; then
		status_args="$status_args --strict"
	fi
	if [ "$with_journal" -ne 0 ]; then
		status_args="$status_args --journal --lines $journal_lines"
	fi
	"$scripts_dir/ops_spark_ring_status.sh" $status_args $instance_opts "$@" || true
	echo

	if [ "$staged_env_audit" -ne 0 ]; then
		echo "== staged env audit (requires prior staging) =="
		"$scripts_dir/ops_spark_ring_staged_env_audit.sh" $instance_opts "$@" || true
		echo
	fi

	if [ "$staged_readiness" -ne 0 ]; then
		echo "== staged readiness (requires prior staging) =="
		readiness_args=""
		readiness_args="$readiness_args --topology $topology"
		if [ "$tcp_ports" != "" ]; then
			for p in $tcp_ports; do
				readiness_args="$readiness_args --tcp $p"
			done
		fi
		readiness_args="$readiness_args --preflight $picked_staged_preflight"
		if [ "$staged_readiness_strict" -ne 0 ]; then
			readiness_args="$readiness_args --strict"
		fi
		"$scripts_dir/ops_spark_ring_staged_readiness.sh" $readiness_args $instance_opts "$@" || true
		echo
	fi

	echo "== next =="
	case "$picked_preflight" in
		tp2)
			echo "readiness rubric: docs/ops-tp2-readiness.md"
			echo "deployment guide: docs/deployment-spark0-spark1.md"
			;;
		tp3)
			echo "readiness rubric: docs/spark-ring-ops-readiness-tp3.md"
			echo "operating checklist: docs/spark-ring-ops-checklist-tp3.md"
			;;
		tp4)
			echo "readiness rubric: docs/ops-tp4-readiness.md"
			echo "operating checklist: docs/spark-ring-ops-checklist.md"
			;;
		*)
			echo "readiness rubric: docs/spark-ring-ops-readiness-tp3.md"
			echo "operating checklist: docs/spark-ring-ops-checklist-tp3.md"
			;;
	esac
	echo "== done =="
}

if [ "$out_path" != "" ]; then
	tmp="${out_path}.tmp.$$"
	out_dir="$(dirname -- "$out_path" 2>/dev/null || echo ".")"
	if [ "$out_dir" != "" ] && [ "$out_dir" != "." ]; then
		mkdir -p "$out_dir"
	fi
	cleanup_tmp()
	{
		rm -f "$tmp" 2>/dev/null || true
	}
	trap cleanup_tmp EXIT INT TERM HUP
	umask 077
	if do_work "$@" >"$tmp" 2>&1; then rc=0; else rc=$?; fi
	mv "$tmp" "$out_path"
	cat "$out_path"
	exit "$rc"
fi

do_work "$@"
}

run_main "$@"
