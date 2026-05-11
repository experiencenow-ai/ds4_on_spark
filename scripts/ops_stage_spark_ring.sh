#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_stage_spark_ring.sh -- stage DS4 deploy assets to Spark0..Spark3 (Mac-side)

Usage:
  ops_stage_spark_ring.sh [--mesh-check] [--topology ring|full] [--tcp <port>]... [--instance0 <name>] [--instance1 <name>] [--instance2 <name>] [--instance3 <name>] <spark0_user@host> <spark1_user@host> <spark2_user@host> <spark3_user@host>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the repo root (Mac-side).
  - Runs `ops_validate_deploy_assets.sh` once, then stages to all four Sparks.
  - Defaults instances to `spark0`..`spark3` (do not rely on ssh username inference).
  - `--mesh-check` runs `ops_spark_ring_mesh_check.sh` before staging.
EOF
}

mesh_check=0
topology="ring"
tcp_ports=""
instance0="spark0"
instance1="spark1"
instance2="spark2"
instance3="spark3"

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
		--instance0)
			instance0="${2:-}"
			shift 2
			;;
		--instance1)
			instance1="${2:-}"
			shift 2
			;;
		--instance2)
			instance2="${2:-}"
			shift 2
			;;
		--instance3)
			instance3="${2:-}"
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

if [ "$#" -ne 4 ]; then
	usage >&2
	exit 2
fi

spark0="$1"
spark1="$2"
spark2="$3"
spark3="$4"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "== stage spark ring deploy assets (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "topology=$topology"
echo "spark0: $spark0 (instance=$instance0)"
echo "spark1: $spark1 (instance=$instance1)"
echo "spark2: $spark2 (instance=$instance2)"
echo "spark3: $spark3 (instance=$instance3)"
echo

if [ -x "$root/scripts/ops_validate_deploy_assets.sh" ]; then
	"$root/scripts/ops_validate_deploy_assets.sh"
	echo
fi

if [ "$mesh_check" -ne 0 ]; then
	echo "== mesh check (Mac-side, optional) =="
	set -- "$spark0" "$spark1" "$spark2" "$spark3"
	if [ "$topology" != "" ]; then
		set -- --topology "$topology" "$@"
	fi
	for p in $tcp_ports; do
		set -- --tcp "$p" "$@"
	done
	"$root/scripts/ops_spark_ring_mesh_check.sh" "$@"
	echo
fi

echo "== stage spark0 =="
DS4_SKIP_VALIDATE=1 DS4_ENV_VARIANT=tp4 "$root/scripts/ops_stage_deploy_assets.sh" "$spark0" "$instance0"
echo

echo "== stage spark1 =="
DS4_SKIP_VALIDATE=1 DS4_ENV_VARIANT=tp4 "$root/scripts/ops_stage_deploy_assets.sh" "$spark1" "$instance1"
echo

echo "== stage spark2 =="
DS4_SKIP_VALIDATE=1 DS4_ENV_VARIANT=tp4 "$root/scripts/ops_stage_deploy_assets.sh" "$spark2" "$instance2"
echo

echo "== stage spark3 =="
DS4_SKIP_VALIDATE=1 DS4_ENV_VARIANT=tp4 "$root/scripts/ops_stage_deploy_assets.sh" "$spark3" "$instance3"
echo

echo "== done =="
