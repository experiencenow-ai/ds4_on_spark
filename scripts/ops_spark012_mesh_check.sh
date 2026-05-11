#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark012_mesh_check.sh -- compatibility wrapper for Spark ring mesh checks

Prefer the inventory-driven command for new work:

  ops_spark_ring_mesh_check.sh [--topology ring|full] [--tcp <port>]... <spark0_user@host> <spark1_user@host> [spark2_user@host ...]

This legacy name delegates all arguments to ops_spark_ring_mesh_check.sh.
EOF
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec "$root/scripts/ops_spark_ring_mesh_check.sh" "$@"
