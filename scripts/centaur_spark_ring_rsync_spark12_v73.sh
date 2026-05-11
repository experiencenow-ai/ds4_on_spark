#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
centaur_spark_ring_rsync_spark12_v73.sh -- compatibility wrapper for Centaur ring rsync

Prefer the inventory-driven command for new work:

  centaur_spark_ring_rsync_v73.sh [--remote-base <dir>] <spark1_user@host> [spark2_user@host ...]

This legacy name delegates to centaur_spark_ring_rsync_v73.sh. For compatibility
with the older form, a third positional argument that looks like a path is
translated to --remote-base.
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ "$#" -eq 3 ]; then
	case "$3" in
		/*|~*|.*)
			exec "$root/scripts/centaur_spark_ring_rsync_v73.sh" --remote-base "$3" "$1" "$2"
			;;
	esac
fi
exec "$root/scripts/centaur_spark_ring_rsync_v73.sh" "$@"
