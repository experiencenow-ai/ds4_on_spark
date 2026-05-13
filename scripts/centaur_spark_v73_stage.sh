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
  STAGE_SKIP_PREFLIGHT    Set to 1 to skip SSH preflight checks
  STAGE_SKIP_PREREQS      Set to 1 to skip remote prereq checks (python3/venv/unzip; rsync only when used)

Examples:
  ./scripts/centaur_spark_v73_stage.sh spark1@aitopatom-spark1.local
  ./scripts/centaur_spark_v73_stage.sh spark2@aitopatom-spark2.local "~/centaur-smoke/v73"
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

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd ssh

need_copy_tool()
{
	if command -v rsync >/dev/null 2>&1; then
		return 0
	fi
	if command -v scp >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: rsync or scp" >&2
	exit 2
}

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

copy_to_remote()
{
	mode="$1"
	src="$2"
	dst="$3"
	case "$mode" in
		rsync)
			rsync -av -e "ssh $SSH_OPTS" "$src" "$dst"
			return 0
			;;
		scp)
			scp $SSH_OPTS "$src" "$dst"
			return 0
			;;
	esac
	echo "invalid copy mode: $mode" >&2
	return 1
}

ssh_preflight()
{
	t="$1"
	if ssh $SSH_OPTS "$t" "true" >/dev/null 2>&1; then
		echo "preflight: ssh ok: $t"
		return 0
	fi
	echo "preflight: ssh failed: $t" >&2
	return 1
}

echo "== centaur v73 stage to $target =="
echo "remote_dir: $remote_dir"

need_copy_tool

if [ "${STAGE_SKIP_PREFLIGHT:-0}" != "1" ]; then
	echo "== stage preflight ssh =="
	ssh_preflight "$target" || exit 21
else
	echo "== skip preflight (STAGE_SKIP_PREFLIGHT=1) =="
fi

copy_mode="scp"
if command -v rsync >/dev/null 2>&1; then
	if ssh $SSH_OPTS "$target" "command -v rsync >/dev/null 2>&1" >/dev/null 2>&1; then
		copy_mode="rsync"
	fi
fi
echo "copy_mode: $copy_mode"

if [ "${STAGE_SKIP_PREREQS:-0}" != "1" ]; then
	prereqs="$root/scripts/centaur_spark_v73_prereqs_check.sh"
	if [ -x "$prereqs" ]; then
		if [ "$copy_mode" = "rsync" ]; then
			echo "== stage prereqs (copy=rsync) =="
			SSH_OPTS="$SSH_OPTS" sh "$prereqs" --check-rsync "$target" || exit 22
		else
			echo "== stage prereqs (copy=scp) =="
			SSH_OPTS="$SSH_OPTS" sh "$prereqs" "$target" || exit 22
		fi
	else
		echo "note: prereqs checker missing; skipping: $prereqs" >&2
	fi
else
	echo "== skip prereqs (STAGE_SKIP_PREREQS=1) =="
fi

ssh_run "$target" "mkdir -p $remote_dir"
remote_dir_abs="$(ssh_run "$target" "cd $remote_dir && pwd -P")"
echo "remote_dir_abs: $remote_dir_abs"
copy_to_remote "$copy_mode" "$zip" "$target:$remote_dir/centaur_spec_impl_v73.zip"

if [ -f "$catalog" ]; then
	copy_to_remote "$copy_mode" "$catalog" "$target:$remote_dir/unit_model_catalog.json"
else
	echo "note: catalog fixture not found; skipping: $catalog" >&2
fi
