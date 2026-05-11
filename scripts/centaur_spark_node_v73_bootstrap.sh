#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Centaur spec-impl v73 bootstrap for a Spark node (Spark1/Spark2/Spark3).

This runs on the node itself (no sudo/service changes) and prepares:
  - Centaur v73 extraction under CENTAUR_WORKDIR/centaur_spec_impl_v73
  - python3 venv under CENTAUR_WORKDIR/venv
  - pip install of requirements.txt (unless CENTAUR_SKIP_PIP=1)
  - centaur.py selftest --json

Environment:
  CENTAUR_ZIP      Path to centaur_spec_impl_v73.zip (required)
  CENTAUR_WORKDIR  Workspace dir (default: ~/centaur-smoke/v73/run)
  CENTAUR_PIP_ARGS Optional extra args for pip install (e.g. "--no-index --find-links=/path/to/wheels")
  CENTAUR_SKIP_PIP Set to 1 to skip pip install (assumes venv already has deps)

Example (on Spark1):
  export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip
  sh ./centaur_spark_node_v73_bootstrap.sh | tee ~/centaur-smoke/v73/run/bootstrap.log
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

need_cmd python3
need_cmd unzip

if python3 -c 'import venv' >/dev/null 2>&1; then
	:
else
	echo "python3 venv module missing; on Debian/Ubuntu install python3-venv" >&2
	exit 2
fi

zip="${CENTAUR_ZIP:-}"
if [ "$zip" = "" ]; then
	echo "CENTAUR_ZIP is required" >&2
	usage >&2
	exit 2
fi
if [ ! -f "$zip" ]; then
	echo "CENTAUR_ZIP not found: $zip" >&2
	exit 2
fi

workdir="${CENTAUR_WORKDIR:-$HOME/centaur-smoke/v73/run}"
pkgdir="$workdir/centaur_spec_impl_v73"
venvdir="$workdir/venv"

mkdir -p "$workdir"

echo "== centaur v73 bootstrap (node) =="
echo "zip: $zip"
echo "workdir: $workdir"

echo "== python =="
python3 -V
python3 -c 'import sys,platform; print("executable:",sys.executable); print("platform:",platform.platform())'

echo "== unpack centaur =="
rm -rf "$pkgdir"
unzip -q "$zip" -d "$workdir"
if [ ! -f "$pkgdir/centaur.py" ]; then
	echo "expected $pkgdir/centaur.py after unzip" >&2
	exit 2
fi

echo "== venv =="
python3 -m venv "$venvdir"
venv_py="$venvdir/bin/python3"
if [ ! -x "$venv_py" ]; then
	echo "expected venv python: $venv_py" >&2
	exit 2
fi

echo "== pip install (centaur requirements) =="
"$venv_py" -m pip -V
if [ "${CENTAUR_SKIP_PIP:-0}" = "1" ]; then
	echo "skipping pip install (CENTAUR_SKIP_PIP=1)"
else
	pip_args="${CENTAUR_PIP_ARGS:-}"
	if [ "$pip_args" = "" ]; then
		"$venv_py" -m pip install -r "$pkgdir/requirements.txt"
	else
		"$venv_py" -m pip install $pip_args -r "$pkgdir/requirements.txt"
	fi
fi

echo "== centaur package facts =="
ls -la "$pkgdir" | sed -n '1,20p'
sha256="$(python3 - <<PY
import hashlib,sys
p=sys.argv[1]
h=hashlib.sha256()
with open(p,'rb') as f:
    h.update(f.read())
print(h.hexdigest())
PY
"$zip")"
echo "zip_sha256: $sha256"

echo "== pip freeze (sanitized) =="
"$venv_py" -m pip freeze | sed -E 's@file://[^ ]+@file://REDACTED@g'

echo "== centaur selftest =="
"$venv_py" -m py_compile "$pkgdir/centaur.py" "$pkgdir/tests/test_centaur.py"
"$venv_py" -u "$pkgdir/centaur.py" selftest --json

echo "== done =="
echo "workdir: $workdir"
