#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark_v73_stage.sh <spark_user@host> [remote_dir]

Stages the Centaur spec-impl v73 zip (and optional tiny model catalog fixture)
to a Spark node without sudo/system changes.

Environment:
  CENTAUR_ZIP             Local zip path (default: /Users/mac/Downloads/centaur_spec_impl_v73.zip)
  CENTAUR_CATALOG_FIXTURE Optional local JSON path to stage as unit_model_catalog.json
                          (default: fixtures/centaur-smoke/spark0-v73/unit_model_catalog.json)
  SSH_OPTS                Optional ssh options override (default includes BatchMode + temp known_hosts)

Examples:
  ./scripts/centaur_spark_v73_stage.sh spark1@aitopatom-spark1.local
  ./scripts/centaur_spark_v73_stage.sh spark2@aitopatom-spark2.local ~/centaur-smoke/v73
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

target="$1"
remote_dir="${2:-}"
if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi

zip="${CENTAUR_ZIP:-/Users/mac/Downloads/centaur_spec_impl_v73.zip}"
if [ ! -f "$zip" ]; then
	echo "missing centaur zip: $zip" >&2
	echo "set CENTAUR_ZIP=/path/to/centaur_spec_impl_v73.zip" >&2
	exit 2
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
default_catalog="$root/fixtures/centaur-smoke/spark0-v73/unit_model_catalog.json"
catalog="${CENTAUR_CATALOG_FIXTURE:-$default_catalog}"

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

rsync_run()
{
	rsync -av -e "ssh $SSH_OPTS" "$@"
}

echo "== centaur v73 stage to $target =="
echo "remote_dir: $remote_dir"

ssh_run "$target" "mkdir -p $remote_dir"
rsync_run "$zip" "$target:$remote_dir/centaur_spec_impl_v73.zip"

if [ -f "$catalog" ]; then
	rsync_run "$catalog" "$target:$remote_dir/unit_model_catalog.json"
else
	echo "note: catalog fixture not found; skipping: $catalog" >&2
fi

