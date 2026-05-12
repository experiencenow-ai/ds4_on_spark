#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark0_v73_fixture_pack.sh <run_id> [local_bundle_dir] [fixtures_out_dir]

Create a commit-ready Spark0 Centaur v73 smoke evidence bundle under:
  fixtures/centaur-smoke/spark0-v73/<run_id>/

This is intended to run on your Mac *after* you have fetched artifacts with:
  scripts/centaur_spark0_v73_fetch_artifacts.sh

It copies only the small artifact set:
  - smoke.log (if present)
  - smoke_facts.json (if present)
  - pip_freeze.txt (if present)
  - effective_manifests/
  - hyor_effective/
  - hyor_dashboard/

It also writes a README.md summarizing zip/pip facts (best-effort) extracted
from smoke.log when available.

Arguments:
  run_id            Required (example: 20260512T093838Z)
  local_bundle_dir  Optional; defaults to:
                     /private/tmp/centaur-smoke/spark0-v73/<run_id>
                     /tmp/centaur-smoke/spark0-v73/<run_id>
  fixtures_out_dir  Optional; defaults to repo fixtures path above.

Environment:
  ALLOW_OVERWRITE   Set to 1 to overwrite an existing fixtures_out_dir.

Notes:
  - Review the copied log/dashboard for private hostnames/paths before commit.
  - Do not commit zips or venvs.
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
	if [ -d "/private/tmp/centaur-smoke/spark0-v73/$run_id" ]; then
		local_in="/private/tmp/centaur-smoke/spark0-v73/$run_id"
	elif [ -d "/tmp/centaur-smoke/spark0-v73/$run_id" ]; then
		local_in="/tmp/centaur-smoke/spark0-v73/$run_id"
	else
		echo "missing local bundle dir; pass it explicitly as arg2" >&2
		echo "tried: /private/tmp/centaur-smoke/spark0-v73/$run_id" >&2
		echo "tried: /tmp/centaur-smoke/spark0-v73/$run_id" >&2
		exit 2
	fi
fi

if [ "$fixtures_out" = "" ]; then
	fixtures_out="$root/fixtures/centaur-smoke/spark0-v73/$run_id"
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

echo "== centaur spark0 v73 fixture pack =="
echo "run_id: $run_id"
echo "local_in: $local_in"
echo "fixtures_out: $fixtures_out"

copy_one "$local_in/effective_manifests" "$fixtures_out/"
copy_one "$local_in/hyor_effective" "$fixtures_out/"
copy_one "$local_in/hyor_dashboard" "$fixtures_out/"
copy_one "$local_in/smoke.log" "$fixtures_out/"
copy_one "$local_in/smoke_facts.json" "$fixtures_out/"
copy_one "$local_in/pip_freeze.txt" "$fixtures_out/"

zip_path=""
zip_sha256=""
zip_mtime=""
zip_size=""
decomposer_version=""
py_ver=""
pip_ver=""
req_sha256=""
numpy_ver=""
scipy_ver=""
sklearn_ver=""

if [ -f "$fixtures_out/smoke.log" ]; then
	zip_path="$(sed -n 's/^zip: //p' "$fixtures_out/smoke.log" | sed -n '1p')"
	zip_sha256="$(sed -n 's/^zip_sha256: //p' "$fixtures_out/smoke.log" | sed -n '1p')"
	decomposer_version="$(sed -n 's/^decomposer_version: //p' "$fixtures_out/smoke.log" | sed -n '1p')"
	py_ver="$(sed -n '/^== python ==$/ {n;p;}' "$fixtures_out/smoke.log" | sed -n '1p')"
	numpy_ver="$(sed -n 's/^numpy==//p' "$fixtures_out/smoke.log" | sed -n '1p')"
	scipy_ver="$(sed -n 's/^scipy==//p' "$fixtures_out/smoke.log" | sed -n '1p')"
	sklearn_ver="$(sed -n 's/^scikit-learn==//p' "$fixtures_out/smoke.log" | sed -n '1p')"
fi
if [ -f "$fixtures_out/smoke_facts.json" ]; then
	if command -v python3 >/dev/null 2>&1; then
		zip_path="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
print(d.get("zip_path","") or "")
PY
)"
		zip_sha256="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
print(d.get("zip_sha256","") or "")
PY
)"
		zip_mtime="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
st=(d.get("zip_stat") or {})
print(st.get("mtime_utc","") or "")
PY
)"
		zip_size="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
st=(d.get("zip_stat") or {})
v=st.get("size_bytes")
if v is None:
    print("")
else:
    print(str(v))
PY
)"
		decomposer_version="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
print(d.get("decomposer_version","") or "")
PY
)"
		py_ver="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
py=(d.get("python") or {}).get("version") or ""
print(py)
PY
)"
		pip_ver="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
pip=(d.get("pip") or {}).get("version") or ""
print(pip)
PY
)"
		req_sha256="$(python3 - "$fixtures_out/smoke_facts.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,"r",encoding="utf-8",errors="replace"))
except Exception:
    print("")
    raise SystemExit(0)
r=(d.get("requirements") or {}).get("sha256") or ""
print(r)
PY
)"
	fi
fi
if [ -f "$fixtures_out/pip_freeze.txt" ]; then
	numpy_ver="$(sed -n 's/^numpy==//p' "$fixtures_out/pip_freeze.txt" | sed -n '1p')"
	scipy_ver="$(sed -n 's/^scipy==//p' "$fixtures_out/pip_freeze.txt" | sed -n '1p')"
	sklearn_ver="$(sed -n 's/^scikit-learn==//p' "$fixtures_out/pip_freeze.txt" | sed -n '1p')"
fi

cat >"$fixtures_out/README.md" <<EOF
# Spark0 Centaur v73 smoke bundle

Run id: \`$run_id\`

This bundle is intended to be safe-to-commit evidence for Centaur-on-Spark smoke runs.
Review \`smoke.log\` and any dashboard output for private hostnames/paths before committing.

Produced by fetching artifacts from Spark0 and then running:

\`\`\`bash
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$run_id"
sh ./scripts/centaur_spark0_v73_fixture_pack.sh "$run_id"
\`\`\`

Centaur zip (from \`smoke.log\`, when present):

- Path: \`${zip_path:-"(unknown)"}\`
- Mtime (UTC): \`${zip_mtime:-"(unknown)"}\`
- Size (bytes): \`${zip_size:-"(unknown)"}\`
- \`zip_sha256\`: \`${zip_sha256:-"(unknown)"}\`
- \`decomposer_version\`: \`${decomposer_version:-"(unknown)"}\`

Spark0 environment (from \`smoke.log\`, when present):

- \`python3 -V\`: \`${py_ver:-"(unknown)"}\`
- \`pip\`: \`${pip_ver:-"(unknown)"}\`
- \`requirements.txt sha256\`: \`${req_sha256:-"(unknown)"}\`
- \`numpy\`: \`${numpy_ver:-"(unknown)"}\`
- \`scipy\`: \`${scipy_ver:-"(unknown)"}\`
- \`scikit-learn\`: \`${sklearn_ver:-"(unknown)"}\`

Contents:

- \`smoke.log\`: command transcript + JSON outputs (no secrets assumed; still review)
- \`smoke_facts.json\`: structured zip/python/pip facts (when present)
- \`pip_freeze.txt\`: sanitized dependency versions (when present)
- \`effective_manifests/\`: \`hyor-sync-effective\` manifest(s)
- \`hyor_effective/\`: materialized effective view for \`spark0\`
- \`hyor_dashboard/\`: HTML/JSON dashboard output

Runbook:

- \`docs/centaur-spark0-v73-smoke.md\`
EOF

redact="$root/scripts/centaur_redact_fixture_bundle.sh"
if [ -x "$redact" ]; then
	echo "== redact bundle (best-effort) =="
	sh "$redact" "$fixtures_out" || true
fi

echo "== done =="
