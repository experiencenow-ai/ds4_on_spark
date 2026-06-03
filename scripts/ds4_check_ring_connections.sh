#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/v2"
exec python3 scripts/ds4_check_spark_fabric_routes.py "$@"
