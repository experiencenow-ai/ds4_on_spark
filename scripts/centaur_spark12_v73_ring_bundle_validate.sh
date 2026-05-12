#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_bundle_validate.sh <ring_run_id> [local_bundle_dir] [mode]

Validates a fetched Spark12 ring bundle on your Mac.

mode:
  sim    Spark0-local multi-root ring rehearsal (expects ring_sim.log + effective/)
  rsync   Spark0-orchestrated rsync-staged ring-step (expects ring_rsync.log)
  (omit) autodetect from bundle contents

Defaults (when local_bundle_dir omitted):
  sim:  /private/tmp/centaur-ring-sim/spark12-v73/<ring_run_id> (or /tmp/...)
  rsync: /private/tmp/centaur-ring/spark12-v73/<ring_run_id> (or /tmp/...)

Environment:
  STRICT=1  Fail on missing log markers (default: 1)
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

run_id="$1"
local_in="${2:-}"
mode="${3:-}"

strict="${STRICT:-1}"

choose_base()
{
	base="/tmp"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp"
	fi
	printf "%s" "$base"
}

if [ "$local_in" = "" ]; then
	base="$(choose_base)"
	if [ "$mode" = "sim" ]; then
		local_in="$base/centaur-ring-sim/spark12-v73/$run_id"
	elif [ "$mode" = "rsync" ]; then
		local_in="$base/centaur-ring/spark12-v73/$run_id"
	else
		if [ -d "$base/centaur-ring-sim/spark12-v73/$run_id" ]; then
			local_in="$base/centaur-ring-sim/spark12-v73/$run_id"
		else
			local_in="$base/centaur-ring/spark12-v73/$run_id"
		fi
	fi
fi

if [ ! -d "$local_in" ]; then
	echo "local ring bundle dir not found: $local_in" >&2
	exit 2
fi

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd sh

if [ "$mode" = "" ]; then
	if [ -f "$local_in/ring_sim.log" ]; then
		mode="sim"
	elif [ -f "$local_in/ring_rsync.log" ]; then
		mode="rsync"
	else
		echo "failed to autodetect mode (missing ring_sim.log and ring_rsync.log); pass mode=sim|rsync" >&2
		exit 2
	fi
fi

echo "== centaur spark12 v73 ring bundle validate =="
echo "ring_run_id: $run_id"
echo "mode: $mode"
echo "local_bundle_dir: $local_in"

req_file()
{
	p="$1"
	if [ -f "$p" ]; then
		echo "ok: file: $p"
		return 0
	fi
	echo "missing: file: $p" >&2
	exit 2
}

req_dir()
{
	p="$1"
	if [ -d "$p" ]; then
		echo "ok: dir: $p"
		return 0
	fi
	echo "missing: dir: $p" >&2
	exit 2
}

check_marker()
{
	log="$1"
	m="$2"
	if command -v rg >/dev/null 2>&1; then
		if rg -n "$m" "$log" >/dev/null 2>&1; then
			echo "ok: marker: $m"
			return 0
		fi
	else
		if grep -F "$m" "$log" >/dev/null 2>&1; then
			echo "ok: marker: $m"
			return 0
		fi
	fi
	if [ "$strict" = "1" ]; then
		echo "missing marker in log (STRICT=1): $m" >&2
		exit 2
	fi
	echo "warn: missing marker (STRICT!=1): $m" >&2
	return 0
}

if [ "$mode" = "sim" ]; then
	req_file "$local_in/ring_sim.log"
	req_dir "$local_in/effective_manifests"
	req_dir "$local_in/effective"
	check_marker "$local_in/ring_sim.log" "== ring sim workdir =="
	check_marker "$local_in/ring_sim.log" "== done =="
elif [ "$mode" = "rsync" ]; then
	req_file "$local_in/ring_rsync.log"
	req_dir "$local_in/effective_manifests"
	check_marker "$local_in/ring_rsync.log" "== centaur v73 ring rsync step =="
	check_marker "$local_in/ring_rsync.log" "== done =="
else
	echo "unknown mode: $mode (expected sim|rsync)" >&2
	exit 2
fi

opt_file()
{
	p="$1"
	if [ -f "$p" ]; then
		echo "ok: file: $p"
		return 0
	fi
	echo "note: missing optional file: $p"
	return 0
}

opt_file "$local_in/ring_sim.local.log"
opt_file "$local_in/ring_rsync.local.log"

echo "== ok =="
