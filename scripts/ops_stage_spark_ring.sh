#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_stage_spark_ring.sh -- stage DS4 deploy assets to an ordered Spark ring (Mac-side)

Usage:
  ops_stage_spark_ring.sh [--mesh-check] [--topology ring|full] [--tcp <port>]... [--instance<N> <name>]... <spark0_user@host> <spark1_user@host> [spark2_user@host ...]

Environment:
  SSH_OPTS   Optional ssh options override.
  DS4_ENV_VARIANT Optional deploy env variant override (for example tp3 or tp4).

Notes:
  - Non-destructive; intended to run from the repo root (Mac-side).
  - Host order defines rank/order: arg0=spark0, arg1=spark1, etc.
  - Defaults instance names to `spark0`, `spark1`, ... based on host order.
  - Override an instance with `--instance0 name`, `--instance1 name`, etc.
  - `--mesh-check` runs `ops_spark_ring_mesh_check.sh` before staging.
EOF
}

mesh_check=0
topology="ring"
tcp_ports=""

while [ $# -gt 0 ]; do
	case "$1" in
		--mesh-check)
			mesh_check=1
			shift
			;;
		--topology)
			topology="${2:-}"
			shift 2
			;;
		--tcp)
			tcp_ports="$tcp_ports ${2:-}"
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

case "$topology" in
	ring|full)
		;;
	*)
		echo "invalid --topology: $topology (expected ring|full)" >&2
		exit 2
		;;
esac

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

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "== stage spark ring deploy assets (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "topology=$topology"
echo "node_count=$node_count"
env_variant="${DS4_ENV_VARIANT:-}"
if [ "$env_variant" = "" ]; then
	case "$node_count" in
		3) env_variant="tp3" ;;
		4) env_variant="tp4" ;;
	esac
fi
if [ "$env_variant" != "" ]; then
	echo "env_variant=$env_variant"
fi
i=0
while [ "$i" -lt "$node_count" ]; do
	echo "spark$i: $(value_at target "$i") (instance=$(instance_for_index "$i"))"
	i=$((i + 1))
done
echo

if [ -x "$root/scripts/ops_validate_deploy_assets.sh" ]; then
	"$root/scripts/ops_validate_deploy_assets.sh"
	echo
fi

if [ "$mesh_check" -ne 0 ]; then
	echo "== mesh check (Mac-side, optional) =="
	set --
	if [ "$topology" != "" ]; then
		set -- --topology "$topology" "$@"
	fi
	for p in $tcp_ports; do
		set -- --tcp "$p" "$@"
	done
	i=0
	while [ "$i" -lt "$node_count" ]; do
		set -- "$@" "$(value_at target "$i")"
		i=$((i + 1))
	done
	"$root/scripts/ops_spark_ring_mesh_check.sh" "$@"
	echo
fi

i=0
while [ "$i" -lt "$node_count" ]; do
	echo "== stage spark$i =="
	if [ "$env_variant" != "" ]; then
		DS4_SKIP_VALIDATE=1 DS4_ENV_VARIANT="$env_variant" "$root/scripts/ops_stage_deploy_assets.sh" "$(value_at target "$i")" "$(instance_for_index "$i")"
	else
		DS4_SKIP_VALIDATE=1 "$root/scripts/ops_stage_deploy_assets.sh" "$(value_at target "$i")" "$(instance_for_index "$i")"
	fi
	echo
	i=$((i + 1))
done

echo "== done =="
