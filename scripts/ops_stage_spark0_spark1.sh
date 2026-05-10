#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_stage_spark0_spark1.sh -- stage DS4 deploy assets to Spark0 + Spark1 (Mac-side)

Usage:
  ops_stage_spark0_spark1.sh [--mesh-check] [--tcp <port>]... [--instance0 <name>] [--instance1 <name>] <spark0_user@host> <spark1_user@host>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the repo root (Mac-side).
  - Runs `ops_validate_deploy_assets.sh` once, then stages to both Sparks.
  - Defaults instances to `spark0` and `spark1` (do not rely on ssh username inference).
  - `--mesh-check` runs `ops_spark01_mesh_check.sh` before staging.
EOF
}

mesh_check=0
tcp_ports=""
instance0="spark0"
instance1="spark1"

while [ $# -gt 0 ]; do
	case "$1" in
		--mesh-check)
			mesh_check=1
			shift
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
		-h|--help)
			usage
			exit 0
			;;
		*)
			break
			;;
	esac
done

if [ "$#" -ne 2 ]; then
	usage >&2
	exit 2
fi

spark0="$1"
spark1="$2"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ "$instance0" = "" ] || [ "$instance1" = "" ]; then
	echo "instance names must be non-empty" >&2
	exit 2
fi

echo "== stage spark0/spark1 deploy assets (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "spark0: $spark0 (instance=$instance0)"
echo "spark1: $spark1 (instance=$instance1)"
echo

if [ -x "$root/scripts/ops_validate_deploy_assets.sh" ]; then
	"$root/scripts/ops_validate_deploy_assets.sh"
	echo
fi

if [ "$mesh_check" -ne 0 ]; then
	echo "== mesh check (Mac-side, optional) =="
	if [ "$tcp_ports" != "" ]; then
		set -- "$spark0" "$spark1"
		for p in $tcp_ports; do
			set -- --tcp "$p" "$@"
		done
		"$root/scripts/ops_spark01_mesh_check.sh" "$@"
	else
		"$root/scripts/ops_spark01_mesh_check.sh" "$spark0" "$spark1"
	fi
	echo
fi

echo "== stage spark0 =="
DS4_SKIP_VALIDATE=1 "$root/scripts/ops_stage_deploy_assets.sh" "$spark0" "$instance0"
echo

echo "== stage spark1 =="
DS4_SKIP_VALIDATE=1 "$root/scripts/ops_stage_deploy_assets.sh" "$spark1" "$instance1"
echo

echo "== done =="
