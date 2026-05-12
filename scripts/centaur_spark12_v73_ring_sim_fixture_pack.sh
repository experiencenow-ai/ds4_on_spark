#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_sim_fixture_pack.sh <ring_run_id> [local_bundle_dir] [fixtures_out_dir]

Create a commit-ready Spark12 Centaur v73 ring-sim evidence bundle under:
  fixtures/centaur-smoke/spark12-v73/ring_sim/<ring_run_id>/

This is intended to run on your Mac *after* you have fetched artifacts with:
  scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh

It copies only the small artifact set:
  - ring_sim.log (if present)
  - effective_manifests/
  - effective/

It also writes a README.md summarizing Centaur/pip facts (best-effort) extracted
from ring_sim.log when available.

Arguments:
  ring_run_id        Required (example: 20260512T074400Z)
  local_bundle_dir   Optional; defaults to:
                      /private/tmp/centaur-ring-sim/spark12-v73/<ring_run_id>
                      /tmp/centaur-ring-sim/spark12-v73/<ring_run_id>
  fixtures_out_dir   Optional; defaults to repo fixtures path above.

Environment:
  ALLOW_OVERWRITE    Set to 1 to overwrite an existing fixtures_out_dir.

Notes:
  - Review logs/manifests for private hostnames/paths before commit.
  - Do not commit zips, venvs, or full node roots.
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
fixtures_out="${3:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ "$local_in" = "" ]; then
	if [ -d "/private/tmp/centaur-ring-sim/spark12-v73/$run_id" ]; then
		local_in="/private/tmp/centaur-ring-sim/spark12-v73/$run_id"
	elif [ -d "/tmp/centaur-ring-sim/spark12-v73/$run_id" ]; then
		local_in="/tmp/centaur-ring-sim/spark12-v73/$run_id"
	else
		echo "missing local bundle dir; pass it explicitly as arg2" >&2
		echo "tried: /private/tmp/centaur-ring-sim/spark12-v73/$run_id" >&2
		echo "tried: /tmp/centaur-ring-sim/spark12-v73/$run_id" >&2
		exit 2
	fi
fi

if [ "$fixtures_out" = "" ]; then
	fixtures_out="$root/fixtures/centaur-smoke/spark12-v73/ring_sim/$run_id"
fi

if [ ! -d "$local_in" ]; then
	echo "local bundle dir not found: $local_in" >&2
	exit 2
fi

if [ -e "$fixtures_out" ]; then
	if [ "${ALLOW_OVERWRITE:-0}" = "1" ]; then
		:
	else
		echo "fixtures_out already exists: $fixtures_out" >&2
		echo "set ALLOW_OVERWRITE=1 to overwrite" >&2
		exit 2
	fi
fi

rm -rf "$fixtures_out"
mkdir -p "$fixtures_out"

copy_one()
{
	src="$1"
	dst="$2"
	if [ -e "$src" ]; then
		cp -R "$src" "$dst"
	else
		echo "skip (not found): $src"
	fi
}

echo "== centaur spark12 v73 ring sim fixture pack =="
echo "run_id: $run_id"
echo "local_in: $local_in"
echo "fixtures_out: $fixtures_out"

copy_one "$local_in/effective_manifests" "$fixtures_out/"
copy_one "$local_in/effective" "$fixtures_out/"
copy_one "$local_in/ring_sim.log" "$fixtures_out/"

workdir=""
node_count=""
py_ver=""
decomposer_version=""
numpy_ver=""
scipy_ver=""
sklearn_ver=""

if [ -f "$fixtures_out/ring_sim.log" ]; then
	workdir="$(sed -n '/^== ring sim workdir ==$/ {n;p;}' "$fixtures_out/ring_sim.log" | sed -n '1p')"
	node_count="$(sed -n 's/^node_count=//p' "$fixtures_out/ring_sim.log" | sed -n '1p')"
	py_ver="$(sed -n '/^== centaur package facts ==$/ {n;p;}' "$fixtures_out/ring_sim.log" | sed -n '1p')"
	decomposer_version="$(sed -n 's/^decomposer_version: //p' "$fixtures_out/ring_sim.log" | sed -n '1p')"
	numpy_ver="$(sed -n 's/^numpy==//p' "$fixtures_out/ring_sim.log" | sed -n '1p')"
	scipy_ver="$(sed -n 's/^scipy==//p' "$fixtures_out/ring_sim.log" | sed -n '1p')"
	sklearn_ver="$(sed -n 's/^scikit-learn==//p' "$fixtures_out/ring_sim.log" | sed -n '1p')"
fi

cat >"$fixtures_out/README.md" <<EOF
# Spark12 Centaur v73 ring sim bundle

Ring run id: \`$run_id\`

This bundle is intended to be safe-to-commit evidence for Centaur-on-Spark ring sim runs.
Review \`ring_sim.log\` and manifests for private hostnames/paths before committing.

Produced by fetching artifacts from Spark0 and then running:

\`\`\`bash
sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> "$run_id"
sh ./scripts/centaur_spark12_v73_ring_sim_fixture_pack.sh "$run_id"
\`\`\`

Centaur facts (from \`ring_sim.log\`, when present):

- Ring workdir: \`${workdir:-"(unknown)"}\`
- \`node_count\`: \`${node_count:-"(unknown)"}\`
- \`python3 -V\`: \`${py_ver:-"(unknown)"}\`
- \`decomposer_version\`: \`${decomposer_version:-"(unknown)"}\`
- \`numpy\`: \`${numpy_ver:-"(unknown)"}\`
- \`scipy\`: \`${scipy_ver:-"(unknown)"}\`
- \`scikit-learn\`: \`${sklearn_ver:-"(unknown)"}\`

Contents:

- \`ring_sim.log\`: command transcript + JSON outputs (no secrets assumed; still review)
- \`effective_manifests/\`: \`hyor-sync-effective\` manifest(s) for spark1/spark2
- \`effective/\`: materialized effective view for spark1/spark2

Runbook:

- \`docs/centaur-ring-spark12.md\`
EOF

echo "== done =="

