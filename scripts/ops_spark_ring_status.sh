#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_ring_status.sh -- Mac-side DS4 systemd status snapshot (safe)

Usage:
  ops_spark_ring_status.sh [--system|--user] [--preflight tp2|tp3|tp4] [--strict] [--journal [--lines N]] [--instance<N> <name>]... [--inventory-file <path>] <spark0_user@host> <spark1_user@host> [spark2_user@host ...]
  ops_spark_ring_status.sh [--system|--user] [--preflight tp2|tp3|tp4] [--strict] [--journal [--lines N]] [--instance<N> <name>]... --inventory-file <path>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Host order defines rank/order: arg0=spark0, arg1=spark1, etc (unless overridden via --instanceN).
  - Default preflight is inferred from host count:
      2 hosts => tp2, 3 hosts => tp3, 4 hosts => tp4
  - With --strict, the script snapshots topology-specific strict units:
      tp2 => ds4-strict@.service + ds4-preflight-strict@.service
      tp3 => ds4-tp3-strict@.service + ds4-preflight-tp3-strict@.service
      tp4 => ds4-tp4-strict@.service + ds4-preflight-tp4-strict@.service
  - `--inventory-file` reads targets from a newline-delimited file; blank lines and `#` comments are ignored.
EOF
}

systemd_mode="system"
preflight="auto"
strict=0
with_journal=0
journal_lines=80
inventory_file=""

while [ $# -gt 0 ]; do
	case "$1" in
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
		--inventory-file)
			inventory_file="${2:-}"
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
			eval "instance_$idx=\${2:-}"
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
		echo "invalid --preflight: $preflight (expected tp2|tp3|tp4)" >&2
		exit 2
		;;
esac

case "$journal_lines" in
	''|*[!0-9]*)
		echo "invalid --lines: $journal_lines (expected uint)" >&2
		exit 2
		;;
esac

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
fi

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

node_count="$#"
i=0
while [ "$#" -gt 0 ]; do
	eval "target_$i=\$1"
	i=$((i + 1))
	shift
done

value_at()
{
	prefix="$1"
	idx="$2"
	eval "printf '%s' \"\${${prefix}_${idx}:-}\""
}

instance_for_index()
{
	idx="$1"
	value="$(value_at instance "$idx")"
	if [ "$value" != "" ]; then
		echo "$value"
		return 0
	fi
	echo "spark$idx"
}

infer_preflight()
{
	if [ "$preflight" != "auto" ]; then
		echo "$preflight"
		return 0
	fi
	case "$node_count" in
		2) echo "tp2" ;;
		3) echo "tp3" ;;
		4) echo "tp4" ;;
		*) echo "tp2" ;;
	esac
}

units_for()
{
	topo="$1"
	instance="$2"

	ds4_unit="ds4@${instance}.service"
	preflight_unit="ds4-preflight@${instance}.service"

	if [ "$topo" = "tp3" ]; then
		preflight_unit="ds4-preflight-tp3@${instance}.service"
	fi
	if [ "$topo" = "tp4" ]; then
		preflight_unit="ds4-preflight-tp4@${instance}.service"
	fi
	if [ "$strict" -ne 0 ]; then
		if [ "$topo" = "tp2" ]; then
			ds4_unit="ds4-strict@${instance}.service"
			preflight_unit="ds4-preflight-strict@${instance}.service"
		fi
		if [ "$topo" = "tp3" ]; then
			ds4_unit="ds4-tp3-strict@${instance}.service"
			preflight_unit="ds4-preflight-tp3-strict@${instance}.service"
		fi
		if [ "$topo" = "tp4" ]; then
			ds4_unit="ds4-tp4-strict@${instance}.service"
			preflight_unit="ds4-preflight-tp4-strict@${instance}.service"
		fi
	fi

	printf '%s\n' "$ds4_unit" "$preflight_unit"
}

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

topo="$(infer_preflight)"

echo "== spark ring systemd status (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "systemd_mode=$systemd_mode"
echo "node_count=$node_count"
echo "preflight=$topo"
echo "strict=$strict"
echo "journal=$with_journal"
echo

i=0
while [ "$i" -lt "$node_count" ]; do
	target="$(value_at target "$i")"
	instance="$(instance_for_index "$i")"

	set -- $(units_for "$topo" "$instance")
	ds4_unit="$1"
	preflight_unit="$2"

	echo "== spark$i ($target) (instance=$instance) =="
	ssh_run "$target" sh -c '
set -eu
mode="${1:-system}"
ds4_unit="${2:-}"
preflight_unit="${3:-}"
with_journal="${4:-0}"
journal_lines="${5:-80}"

if [ "$mode" = "user" ]; then
	uid="$(id -u 2>/dev/null || echo "")"
	if [ "$uid" != "" ] && [ -d "/run/user/$uid" ]; then
		export XDG_RUNTIME_DIR="/run/user/$uid"
		export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus"
	fi
	sc="systemctl --user"
	jc="journalctl --user"
else
	sc="systemctl"
	jc="journalctl"
fi

echo "host=$(hostname 2>/dev/null || echo unknown)"
date -Is 2>/dev/null || date || true

show_unit()
{
	unit="$1"
	echo "-- unit: $unit --"
	if $sc show "$unit" >/dev/null 2>&1; then
		$sc show "$unit" -p LoadState -p ActiveState -p SubState -p Result -p ExecMainStatus -p ExecMainPID -p ActiveEnterTimestamp -p FragmentPath 2>/dev/null || true
		$sc is-enabled "$unit" 2>/dev/null || true
		$sc is-active "$unit" 2>/dev/null || true
	else
		echo "unavailable: $unit"
	fi
	if [ "$with_journal" -ne 0 ]; then
		echo "-- journal: $unit (tail $journal_lines) --"
		$jc -u "$unit" -n "$journal_lines" --no-pager 2>/dev/null || true
	fi
}

show_unit "$ds4_unit"
show_unit "$preflight_unit"
' sh "$systemd_mode" "$ds4_unit" "$preflight_unit" "$with_journal" "$journal_lines" || true
	echo

	i=$((i + 1))
done

echo "== done =="
