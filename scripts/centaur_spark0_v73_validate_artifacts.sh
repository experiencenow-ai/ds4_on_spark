#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Validate expected artifacts from the Spark0 Centaur spec-impl v73 smoke.

Usage:
  sh ./scripts/centaur_spark0_v73_validate_artifacts.sh [workdir]

Environment (optional):
  CENTAUR_WORKDIR  Explicit workdir (overrides default)
  CENTAUR_RUN_ID   If set, default workdir is ~/centaur-smoke/v73/run/$CENTAUR_RUN_ID

Defaults:
  ~/centaur-smoke/v73/run  (or per-run subdir when CENTAUR_RUN_ID is set)

Checks (required):
  - effective_manifests/hyor_effective_manifest_spark0.json
  - hyor_effective/spark0/
  - hyor_dashboard/

Checks (optional):
  - smoke.log (when the run used CENTAUR_LOG)
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

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

echo "== centaur spark0 smoke artifact check =="
echo "workdir: $workdir"

need_file "$workdir/effective_manifests/hyor_effective_manifest_spark0.json"
need_dir "$workdir/hyor_effective/spark0"
need_dir "$workdir/hyor_dashboard"

if [ -f "$workdir/smoke.log" ]; then
	echo "ok file: $workdir/smoke.log"
else
	echo "warn missing file: $workdir/smoke.log (set CENTAUR_LOG to capture)" >&2
fi

if [ "$missing" -eq 0 ]; then
	echo "STATUS: PASS"
	exit 0
fi

echo "STATUS: FAIL (missing $missing required artifact(s))" >&2
exit 3
