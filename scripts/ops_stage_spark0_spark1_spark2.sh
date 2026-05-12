#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_stage_spark0_spark1_spark2.sh -- compatibility wrapper for Spark ring staging

Prefer the inventory-driven command for new work:

  ops_stage_spark_ring.sh [--mesh-check] [--topology ring|full] [--tcp <port>]... [--instance<N> <name>]... <spark0_user@host> <spark1_user@host> [spark2_user@host ...]

This legacy name delegates all arguments to ops_stage_spark_ring.sh.
EOF
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec "$root/scripts/ops_stage_spark_ring.sh" "$@"
