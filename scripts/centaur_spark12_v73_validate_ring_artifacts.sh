#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Validate expected artifacts from the Centaur v73 Spark1/Spark2 ring rehearsal.

Usage:
  sh ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh [--mode sim|rsync] [workdir]

Environment (optional):
  RING_WORKDIR  Explicit base workdir (overrides default mode base)
  RING_RUN_ID   If set, default workdir is $RING_WORKDIR/run/$RING_RUN_ID

Defaults:
  mode=sim  -> ~/centaur-smoke/v73/ring_sim_spark12
  mode=rsync -> ~/centaur-smoke/v73/ring_rsync_spark12

Checks (required):
  - effective_manifests/hyor_effective_manifest_spark1.json
  - effective_manifests/hyor_effective_manifest_spark2.json
  - controller/, spark0/, spark1/, spark2/ roots exist

Checks (optional):
  - effective/spark1 and effective/spark2 (expected only when sync-apply was run)
  - ring log (only when RING_LOG was enabled)
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

mode="sim"
if [ "${1:-}" = "--mode" ]; then
	if [ "${2:-}" = "" ]; then
		usage >&2
		exit 2
	fi
	mode="$2"
	shift 2
fi

workdir_arg="${1:-}"
workdir_env="${RING_WORKDIR:-}"
run_id="${RING_RUN_ID:-}"

default_base="$HOME/centaur-smoke/v73/ring_sim_spark12"
if [ "$mode" = "rsync" ]; then
	default_base="$HOME/centaur-smoke/v73/ring_rsync_spark12"
elif [ "$mode" != "sim" ]; then
	echo "unknown --mode: $mode (expected sim or rsync)" >&2
	exit 2
fi

base="$workdir_env"
if [ "$base" = "" ]; then
	base="$default_base"
fi

workdir="$workdir_arg"
if [ "$workdir" = "" ]; then
	if [ "$run_id" = "" ]; then
		workdir="$base"
	else
		workdir="$base/run/$run_id"
	fi
fi

if [ ! -d "$workdir" ]; then
	echo "workdir does not exist: $workdir" >&2
	exit 2
fi

missing=0

need_file()
{
	p="$1"
	if [ -f "$p" ]; then
		echo "ok file: $p"
		return 0
	fi
	echo "missing file: $p" >&2
	missing=$((missing + 1))
	return 0
}

need_dir()
{
	p="$1"
	if [ -d "$p" ]; then
		echo "ok dir: $p"
		return 0
	fi
	echo "missing dir: $p" >&2
	missing=$((missing + 1))
	return 0
}

warn_dir()
{
	p="$1"
	if [ -d "$p" ]; then
		echo "ok dir: $p"
	else
		echo "warn missing dir: $p (expected only when sync-apply ran)" >&2
	fi
}

echo "== centaur ring artifact check =="
echo "mode: $mode"
echo "workdir: $workdir"

need_dir "$workdir/controller"
need_dir "$workdir/spark0"
need_dir "$workdir/spark1"
need_dir "$workdir/spark2"

need_file "$workdir/effective_manifests/hyor_effective_manifest_spark1.json"
need_file "$workdir/effective_manifests/hyor_effective_manifest_spark2.json"

warn_dir "$workdir/effective/spark1"
warn_dir "$workdir/effective/spark2"

if [ "$missing" -eq 0 ]; then
	echo "STATUS: PASS"
	exit 0
fi

echo "STATUS: FAIL (missing $missing required artifact(s))" >&2
exit 3

