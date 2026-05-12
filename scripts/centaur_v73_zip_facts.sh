#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_v73_zip_facts.sh <path/to/centaur_spec_impl_v73.zip>

Prints Centaur v73 "package facts" suitable for bug reports:
  - zip path + ls -la (mtime/size)
  - zip_sha256
  - DECOMPOSER_VERSION (from centaur.py)
  - requirements.txt (from the zip)
  - zip entry listing (names only)

Required commands:
  - python3
  - unzip

Example:
  sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip

Notes:
  - Does not extract the zip to disk.
  - Output is intended to be pasted into PRs/issues after sanitization.
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
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

need_cmd python3
need_cmd unzip

zip="$1"
if [ ! -f "$zip" ]; then
	echo "zip not found: $zip" >&2
	exit 2
fi

echo "== centaur v73 zip facts =="
echo "zip: $zip"
ls -la "$zip" | sed -n '1p'

sha256="$(python3 - "$zip" <<'PY'
import hashlib,sys
p=sys.argv[1]
h=hashlib.sha256()
with open(p,'rb') as f:
    for chunk in iter(lambda: f.read(1<<20), b''):
        h.update(chunk)
print(h.hexdigest())
PY
)"
echo "zip_sha256: $sha256"

decomposer_version="$(python3 - "$zip" <<'PY'
import re
import sys
import zipfile

zip_path=sys.argv[1]
try:
    with zipfile.ZipFile(zip_path) as z:
        data=z.read("centaur_spec_impl_v73/centaur.py").decode("utf-8","replace").splitlines()
except Exception:
    print("")
    sys.exit(0)

for line in data:
    m=re.match(r'^DECOMPOSER_VERSION\\s*=\\s*\"([^\"]+)\"', line)
    if m:
        print(m.group(1))
        sys.exit(0)
print("")
PY
)"
if [ "$decomposer_version" = "" ]; then
	decomposer_version="(unknown)"
fi
echo "decomposer_version: $decomposer_version"

echo "requirements.txt:"
unzip -p "$zip" centaur_spec_impl_v73/requirements.txt 2>/dev/null || echo "(missing)"

echo "zip entries:"
unzip -l "$zip" | sed -n '4,$p' | awk '{print $4}' | sed -n '1,200p'

