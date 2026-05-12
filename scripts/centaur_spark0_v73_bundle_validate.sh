#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark0_v73_bundle_validate.sh <run_id> [local_bundle_dir]

Validates a fetched Spark0 Centaur v73 smoke bundle on your Mac.

Defaults:
  local_bundle_dir:
    /private/tmp/centaur-smoke/spark0-v73/<run_id>
    /tmp/centaur-smoke/spark0-v73/<run_id>

Environment:
  STRICT=1  Fail on missing log markers (default: 1)

Checks:
  - smoke.log exists
  - expected artifact directories exist (when fetched)
  - (optional) smoke_facts.json parses as JSON
  - smoke.log contains key step banners (strict by default)
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

if [ "$local_in" = "" ]; then
	base="/tmp"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp"
	fi
	local_in="$base/centaur-smoke/spark0-v73/$run_id"
fi

if [ ! -d "$local_in" ]; then
	echo "local bundle dir not found: $local_in" >&2
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

strict="${STRICT:-1}"

smoke_log="$local_in/smoke.log"
if [ ! -f "$smoke_log" ]; then
	echo "missing: $smoke_log" >&2
	exit 2
fi

echo "== centaur spark0 v73 bundle validate =="
echo "run_id: $run_id"
echo "local_bundle_dir: $local_in"
echo "smoke_log: $smoke_log"

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

req_dir "$local_in/effective_manifests"
req_dir "$local_in/hyor_dashboard"
req_dir "$local_in/hyor_effective/spark0"

opt_file "$local_in/smoke_facts.json"
opt_file "$local_in/pip_freeze.txt"
opt_file "$local_in/smoke.local.log"

check_marker()
{
	m="$1"
	if command -v rg >/dev/null 2>&1; then
		if rg -n "$m" "$smoke_log" >/dev/null 2>&1; then
			echo "ok: marker: $m"
			return 0
		fi
	else
		if grep -F "$m" "$smoke_log" >/dev/null 2>&1; then
			echo "ok: marker: $m"
			return 0
		fi
	fi
	if [ "$strict" = "1" ]; then
		echo "missing marker in smoke.log (STRICT=1): $m" >&2
		exit 2
	fi
	echo "warn: missing marker (STRICT!=1): $m" >&2
	return 0
}

check_marker "== centaur v73 smoke (spark0) =="
check_marker "== centaur selftest =="
check_marker "== hyor: init controller/node workspaces =="
check_marker "== hyor: publish baseline + node_type =="
check_marker "== hyor: ring-step (metadata) =="
check_marker "== hyor: ring-step (effective) =="
check_marker "== hyor: agent config write"
check_marker "== hyor: node announce + runtime init =="
check_marker "== hyor: provider + model catalog registration"
check_marker "== hyor: benchmark suite + record + results =="
check_marker "== hyor: dashboard =="
check_marker "== done =="

facts_json="$local_in/smoke_facts.json"
if [ -f "$facts_json" ]; then
	need_cmd python3
	echo "== smoke_facts.json =="
	python3 - "$facts_json" <<'PY'
import json,sys
p=sys.argv[1]
with open(p,"r",encoding="utf-8") as f:
    d=json.load(f)
print("utc:",d.get("utc",""))
print("zip_sha256:",d.get("zip_sha256",""))
print("decomposer_version:",d.get("decomposer_version",""))
py=d.get("python") or {}
print("python_version:",py.get("version",""))
PY
fi

echo "== ok =="
