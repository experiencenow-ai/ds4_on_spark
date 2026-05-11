#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Pack a small, shareable artifact bundle from a Spark0 Centaur spec-impl v73 smoke run.

Usage:
  sh ./scripts/centaur_spark0_v73_pack_artifacts.sh [workdir]

Environment (optional):
  CENTAUR_WORKDIR  Explicit workdir (overrides default)
  CENTAUR_RUN_ID   If set, default workdir is ~/centaur-smoke/v73/run/$CENTAUR_RUN_ID
  CENTAUR_PACK_OUT Output tar.gz path (default: <workdir>/artifacts.tgz)

Bundle contents (when present):
  - smoke.log
  - effective_manifests/
  - hyor_effective/spark0/
  - hyor_dashboard/

Notes:
  - Does not include the venv, Centaur source tree, or hyor roots.
  - Review/redact logs before sharing outside the cluster.
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd tar
need_cmd pwd

workdir_arg="${1:-}"
workdir_env="${CENTAUR_WORKDIR:-}"
run_id="${CENTAUR_RUN_ID:-}"

workdir="$workdir_arg"
if [ "$workdir" = "" ]; then
	workdir="$workdir_env"
fi
if [ "$workdir" = "" ]; then
	if [ "$run_id" = "" ]; then
		workdir="$HOME/centaur-smoke/v73/run"
	else
		workdir="$HOME/centaur-smoke/v73/run/$run_id"
	fi
fi

if [ ! -d "$workdir" ]; then
	echo "workdir does not exist: $workdir" >&2
	exit 2
fi

out="${CENTAUR_PACK_OUT:-$workdir/artifacts.tgz}"
outdir="$(dirname -- "$out")"
mkdir -p "$outdir"

tmp="$workdir/.centaur_pack_tmp"
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

echo "== centaur spark0 v73 pack artifacts =="
echo "workdir: $workdir"
echo "out: $out"

copy_one "$workdir/smoke.log" "$tmp/smoke.log"
copy_one "$workdir/effective_manifests" "$tmp/effective_manifests"
mkdir -p "$tmp/hyor_effective"
copy_one "$workdir/hyor_effective/spark0" "$tmp/hyor_effective/spark0"
copy_one "$workdir/hyor_dashboard" "$tmp/hyor_dashboard"

(
	cd "$tmp"
	tar -czf "$out" .
)

rm -rf "$tmp"

echo "== done =="
ls -la "$out"

