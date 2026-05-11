#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
centaur_spark_ring_sim_spark12_v73.sh -- compatibility wrapper for Centaur ring simulation

Prefer the inventory-driven command for new work:

  SPARK_NODE_COUNT=<N> sh ./scripts/centaur_spark_ring_sim_v73.sh

This legacy name defaults SPARK_NODE_COUNT=3 and delegates to
centaur_spark_ring_sim_v73.sh. Override SPARK_NODE_COUNT or RING_WORKDIR in the
environment if needed.
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SPARK_NODE_COUNT="${SPARK_NODE_COUNT:-3}"
RING_WORKDIR="${RING_WORKDIR:-$HOME/centaur-smoke/v73/ring_sim_spark12}"
export SPARK_NODE_COUNT RING_WORKDIR
exec "$root/scripts/centaur_spark_ring_sim_v73.sh" "$@"
