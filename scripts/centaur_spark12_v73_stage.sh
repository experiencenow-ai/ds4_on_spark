#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_stage.sh <spark1_user@host> <spark2_user@host> [remote_dir]

Convenience wrapper to stage Centaur spec-impl v73 zip to both Spark1 and
Spark2 using `scripts/centaur_spark_v73_stage.sh`.

Environment:
  CENTAUR_ZIP             Local zip path (default: /Users/mac/Downloads/centaur_spec_impl_v73.zip)
  CENTAUR_CATALOG_FIXTURE Optional local JSON path to stage as unit_model_catalog.json
  SSH_OPTS                Optional ssh options override (passed through)

Example:
  ./scripts/centaur_spark12_v73_stage.sh spark1@<spark1-host> spark2@<spark2-host> ~/centaur-smoke/v73
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

if [ "${2:-}" = "" ]; then
	usage >&2
	exit 2
fi

spark1="$1"
spark2="$2"
remote_dir="${3:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
stage="$root/scripts/centaur_spark_v73_stage.sh"
if [ ! -x "$stage" ]; then
	echo "missing stage script: $stage" >&2
	exit 2
fi

if [ "$remote_dir" = "" ]; then
	"$stage" "$spark1"
	"$stage" "$spark2"
else
	"$stage" "$spark1" "$remote_dir"
	"$stage" "$spark2" "$remote_dir"
fi

