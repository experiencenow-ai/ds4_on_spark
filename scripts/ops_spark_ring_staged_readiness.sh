#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_ring_staged_readiness.sh -- Mac-side readiness checks using staged env (safe)

Usage:
  ops_spark_ring_staged_readiness.sh [--inventory-file <path>] [--topology ring|full] [--tcp <port>]... [--preflight auto|tp2|tp3|tp4|tp23] [--strict] [--instance<N> <name>]... <spark0_user@host> <spark1_user@host> [spark2_user@host ...]
  ops_spark_ring_staged_readiness.sh [--inventory-file <path>] [--topology ring|full] [--tcp <port>]... [--preflight auto|tp2|tp3|tp4|tp23] [--strict] [--instance<N> <name>]... --inventory-file <path>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac after staging deploy assets.
  - Runs readiness scripts ON each Spark using staged paths:
      /tmp/ds4-scripts/ops_tp{2,3,4}_readiness.sh
      /tmp/ds4-config/ds4.env.example (optional)
      /tmp/ds4-config/ds4-<instance>.env.example
  - For `--preflight auto` (default), picks based on node_count:
      2 => tp2, 3 => tp3, 4 => tp4
EOF
}

inventory_file=""
topology="ring"
tcp_ports=""
preflight="auto"
strict=0

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
		--preflight)
			preflight="${2:-}"
			shift 2
			;;
		--strict)
			strict=1
			shift
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

case "$topology" in
	ring|full)
		;;
	*)
		echo "invalid --topology: $topology (expected ring|full)" >&2
		exit 2
		;;
esac

case "$preflight" in
	auto|tp2|tp3|tp4|tp23)
		;;
	*)
		echo "invalid --preflight: $preflight (expected auto|tp2|tp3|tp4|tp23)" >&2
		exit 2
		;;
esac

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

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
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

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

picked_preflight="$preflight"
if [ "$picked_preflight" = "auto" ]; then
	case "$node_count" in
		2) picked_preflight="tp2" ;;
		3) picked_preflight="tp3" ;;
		4) picked_preflight="tp4" ;;
		*)
			echo "cannot infer --preflight from node_count=$node_count; pass --preflight tp2|tp3|tp4" >&2
			exit 2
			;;
	esac
fi

case "$picked_preflight" in
	tp2)
		;;
	tp3)
		if [ "$node_count" -lt 3 ]; then
			echo "tp3 readiness requires >=3 nodes; node_count=$node_count" >&2
			exit 2
		fi
		;;
	tp4)
		if [ "$node_count" -lt 4 ]; then
			echo "tp4 readiness requires >=4 nodes; node_count=$node_count" >&2
			exit 2
		fi
		;;
	tp23)
		if [ "$node_count" -ne 3 ]; then
			echo "tp23 readiness requires exactly 3 nodes; node_count=$node_count" >&2
			exit 2
		fi
		;;
esac

echo "== staged DS4 readiness (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "topology=$topology"
echo "node_count=$node_count"
echo "preflight=$picked_preflight"
echo "strict=$strict"
i=0
while [ "$i" -lt "$node_count" ]; do
	echo "spark$i: $(value_at target "$i") (instance=$(instance_for_index "$i"))"
	i=$((i + 1))
done
echo

err=0
i=0
while [ "$i" -lt "$node_count" ]; do
	target="$(value_at target "$i")"
	instance="$(instance_for_index "$i")"
	env_shared="-/tmp/ds4-config/ds4.env.example"
	env_instance="/tmp/ds4-config/ds4-${instance}.env.example"

	run_one()
	{
		remote_script="$1"
		label="$2"

		echo "== spark$i ($target) staged $label readiness =="
		echo "env=$env_shared $env_instance"
		echo

		set --
		set -- sh -c '
set -eu
script="${1:-}"
self="${2:-}"
topology="${3:-}"
strict="${4:-0}"
env_shared="${5:-}"
env_instance="${6:-}"
tcp_ports="${7:-}"
if [ ! -f "$env_instance" ]; then
	echo "missing staged env: $env_instance" >&2
	exit 2
fi
if [ ! -f "$script" ]; then
	echo "missing staged readiness script: $script" >&2
	exit 2
fi
case "$script" in
	/tmp/ds4-scripts/ops_tp2_readiness.sh)
		args="--self $self --env $env_shared --env $env_instance"
		if [ "$strict" -ne 0 ] 2>/dev/null; then
			args="--strict $args"
		fi
		exec sh "$script" $args
		;;
	/tmp/ds4-scripts/ops_tp3_readiness.sh|/tmp/ds4-scripts/ops_tp4_readiness.sh)
		args="--self $self --topology $topology --env $env_shared --env $env_instance"
		if [ "$strict" -ne 0 ] 2>/dev/null; then
			args="--strict $args"
		fi
		for p in $tcp_ports; do
			args="$args --tcp $p"
		done
		exec sh "$script" $args
		;;
	*)
		echo "unexpected readiness script path: $script" >&2
		exit 2
		;;
	esac
' sh "$remote_script" "$instance" "$topology" "$strict" "$env_shared" "$env_instance" "$tcp_ports"

		if ! ssh_run "$target" "$@" ; then
			echo "readiness failed: spark$i ($target, instance=$instance, preflight=$label)" >&2
			err=1
		fi
		echo
	}

	if [ "$picked_preflight" = "tp23" ]; then
		run_one "/tmp/ds4-scripts/ops_tp2_readiness.sh" "tp2"
		run_one "/tmp/ds4-scripts/ops_tp3_readiness.sh" "tp3"
	else
		run_one "/tmp/ds4-scripts/ops_${picked_preflight}_readiness.sh" "$picked_preflight"
	fi

	i=$((i + 1))
done

if [ "$err" -ne 0 ]; then
	exit 1
fi
exit 0
