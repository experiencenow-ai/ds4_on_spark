#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
route_filter="${DS4_ROUTE_FILTER:-}"
args=(--control-only --apply-control-iface)

if [ "$route_filter" != "" ]
then
	args+=(--only-ranks "$route_filter")
fi

cd "$repo_root/v2"
exec python3 scripts/ds4_check_spark_fabric_routes.py "${args[@]}" "$@"
