#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Pack a small, shareable artifact bundle from a Centaur v73 Spark1/Spark2 ring run.

Usage:
  sh ./scripts/centaur_spark12_v73_pack_ring_artifacts.sh [--mode sim|rsync] [workdir]

Environment (optional):
  RING_WORKDIR     Explicit base workdir (overrides default mode base)
  RING_RUN_ID      If set, default workdir is $RING_WORKDIR/run/$RING_RUN_ID
  RING_PACK_OUT    Output tar.gz path (default: <workdir>/ring_artifacts.tgz)

Defaults:
  mode=rsync -> ~/centaur-smoke/v73/ring_rsync_spark12
  mode=sim   -> ~/centaur-smoke/v73/ring_sim_spark12

Bundle contents (when present):
  - ring_rsync.log (rsync mode only)
  - effective_manifests/
  - effective/ (only when sync-apply was used)

Notes:
  - Does not include venvs, Centaur sources, or full node roots.
  - Review/redact logs before sharing outside the cluster.
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

mode="rsync"
if [ "${1:-}" = "--mode" ]; then
	if [ "${2:-}" = "" ]; then
		usage >&2
		exit 2
	fi
	mode="$2"
	shift 2
fi

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd tar

workdir_arg="${1:-}"
base_env="${RING_WORKDIR:-}"
run_id="${RING_RUN_ID:-}"

default_base="$HOME/centaur-smoke/v73/ring_rsync_spark12"
if [ "$mode" = "sim" ]; then
	default_base="$HOME/centaur-smoke/v73/ring_sim_spark12"
elif [ "$mode" != "rsync" ]; then
	echo "unknown --mode: $mode (expected sim or rsync)" >&2
	exit 2
fi

base="$base_env"
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

out="${RING_PACK_OUT:-$workdir/ring_artifacts.tgz}"
outdir="$(dirname -- "$out")"
mkdir -p "$outdir"

tmp="$workdir/.centaur_ring_pack_tmp"
rm -rf "$tmp"
mkdir -p "$tmp"

copy_one()
{
	src="$1"
	dst="$2"
	if [ -e "$src" ]; then
		mkdir -p "$(dirname -- "$dst")"
		cp -a "$src" "$dst"
	else
		echo "skip (not found): $src"
	fi
}

echo "== centaur spark12 v73 pack ring artifacts =="
echo "mode: $mode"
echo "workdir: $workdir"
echo "out: $out"

if [ "$mode" = "rsync" ]; then
	copy_one "$workdir/ring_rsync.log" "$tmp/ring_rsync.log"
fi
copy_one "$workdir/effective_manifests" "$tmp/effective_manifests"
copy_one "$workdir/effective" "$tmp/effective"

(
	cd "$tmp"
	tar -czf "$out" .
)

rm -rf "$tmp"

echo "== done =="
ls -la "$out"

