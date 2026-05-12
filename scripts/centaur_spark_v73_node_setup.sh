#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Spark node Centaur spec-impl v73 setup (runs on Spark1/Spark2/etc; no sudo).

Creates/refreshes a local Centaur v73 extraction + venv under a user-writable
directory, then runs `centaur.py selftest --json`.

This is intended to make Spark1/Spark2 ring+HTTP bring-up reproducible.

Environment (optional):
  CENTAUR_ZIP         Path to centaur_spec_impl_v73.zip
                    (default: ~/centaur-smoke/v73/centaur_spec_impl_v73.zip)
  CENTAUR_WORKDIR     Workspace dir to create centaur + venv
                    (default: ~/centaur-smoke/v73/run)
  CENTAUR_PIP_ARGS    Optional extra args for pip install (e.g. "--no-index --find-links=/path/to/wheels")
  CENTAUR_SKIP_PIP    Set to 1 to skip pip install (assumes venv already has deps)
  CENTAUR_CLEAR_VENV  Set to 1 to pass `--clear` when creating the venv
  CENTAUR_LOG         Optional log path (duplicates stdout/stderr via tee)
  CENTAUR_TRACE       Set to 1 to enable shell tracing (prints exact commands)

Example (on Spark1):
  export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip
  export CENTAUR_LOG=~/centaur-smoke/v73/run/node_setup_spark1.log
  sh ./centaur_spark_v73_node_setup.sh

Notes:
  - Installs numpy/scipy/scikit-learn from Centaur requirements; ensure you
    have network or cached wheels.
  - Do not commit zips or venvs into this repo.
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

zip="${CENTAUR_ZIP:-$HOME/centaur-smoke/v73/centaur_spec_impl_v73.zip}"
if [ ! -f "$zip" ]; then
	echo "CENTAUR_ZIP not found: $zip" >&2
	echo "stage the zip to ~/centaur-smoke/v73 first or set CENTAUR_ZIP=/path/to/centaur_spec_impl_v73.zip" >&2
	exit 2
fi

workdir="${CENTAUR_WORKDIR:-$HOME/centaur-smoke/v73/run}"
pkgdir="$workdir/centaur_spec_impl_v73"
venvdir="$workdir/venv"

mkdir -p "$workdir"

log="${CENTAUR_LOG:-}"
artifact_dir="$workdir"
if [ "$log" != "" ]; then
	need_cmd tee
	need_cmd mkfifo
	need_cmd dirname
	mkdir -p "$(dirname -- "$log")"
	artifact_dir="$(dirname -- "$log")"
	fifo="$workdir/.centaur_node_setup_log.fifo"
	rm -f "$fifo"
	mkfifo "$fifo"
	exec 3>&1 4>&2
	tee "$log" <"$fifo" &
	teepid="$!"
	cleanup_log()
	{
		exec >&3 2>&4
		rm -f "$fifo"
		wait "$teepid" 2>/dev/null || true
	}
	trap 'cleanup_log' EXIT INT TERM
	exec >"$fifo" 2>&1
fi

if [ "${CENTAUR_TRACE:-0}" = "1" ]; then
	set -x
fi

echo "== centaur v73 node setup =="
echo "zip: $zip"
echo "workdir: $workdir"
echo "pwd: $(pwd)"
ls -la "$zip" | sed -n '1p'
zip_sha256="$(python3 - "$zip" <<'PY'
import hashlib,sys
p=sys.argv[1]
h=hashlib.sha256()
with open(p,'rb') as f:
    for chunk in iter(lambda: f.read(1024*1024), b''):
        h.update(chunk)
print(h.hexdigest())
PY
)"
echo "zip_sha256: $zip_sha256"

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

echo "== centaur package facts =="
decomposer_version="$(python3 - "$pkgdir/centaur.py" <<'PY'
import ast
import sys

p=sys.argv[1]
try:
    t=open(p,"r",encoding="utf-8",errors="replace").read()
except Exception:
    print("")
    raise SystemExit(0)
try:
    m=ast.parse(t)
except Exception:
    print("")
    raise SystemExit(0)
v=""
for node in getattr(m,"body",[]):
    if isinstance(node, ast.Assign):
        for tgt in getattr(node,"targets",[]):
            if isinstance(tgt, ast.Name) and tgt.id=="DECOMPOSER_VERSION":
                val=getattr(node,"value",None)
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    v=val.value
print(v)
PY
)"
if [ "$decomposer_version" = "" ]; then
	decomposer_version="(unknown)"
fi
echo "decomposer_version: $decomposer_version"
echo "requirements.txt:"
sed -n '1,40p' "$pkgdir/requirements.txt"

echo "== venv =="
if [ "${CENTAUR_CLEAR_VENV:-0}" = "1" ]; then
	python3 -m venv --clear "$venvdir"
else
	python3 -m venv "$venvdir"
fi
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

echo "== pip freeze (sanitized) =="
freeze_file="$artifact_dir/pip_freeze.txt"
"$venv_py" -m pip freeze | sed -E 's@file://[^ ]+@file://REDACTED@g' >"$freeze_file"
echo "freeze_file: $freeze_file"
sed -n '1,120p' "$freeze_file"

echo "== write node setup facts (json) =="
facts_json="$artifact_dir/node_setup_facts.json"
"$venv_py" - "$zip" "$zip_sha256" "$decomposer_version" "$workdir" "$freeze_file" "$pkgdir/requirements.txt" >"$facts_json" <<'PY'
import json
import os
import platform
import sys
from datetime import datetime, timezone

zip_path=sys.argv[1]
zip_sha256=sys.argv[2]
decomposer_version=sys.argv[3]
workdir=sys.argv[4]
freeze_path=sys.argv[5]
requirements_path=sys.argv[6]

pip_freeze=[]
try:
	with open(freeze_path,"r",encoding="utf-8",errors="replace") as f:
		for line in f:
			line=line.strip()
			if line:
				pip_freeze.append(line)
except Exception:
	pip_freeze=[]

req_lines=[]
req_sha256=""
try:
	import hashlib

	h=hashlib.sha256()
	with open(requirements_path,"rb") as f:
		b=f.read()
	h.update(b)
	req_sha256=h.hexdigest()
	t=b.decode("utf-8","replace").splitlines()
	for line in t:
		line=line.strip()
		if not line:
			continue
		req_lines.append(line)
except Exception:
	req_lines=[]
	req_sha256=""

zip_stat={}
try:
	st=os.stat(zip_path)
	zip_stat={
		"size_bytes": int(st.st_size),
		"mtime_utc": datetime.fromtimestamp(st.st_mtime,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
	}
except Exception:
	zip_stat={}

pip_info={}
try:
	import pip  # type: ignore

	pip_info={
		"version": getattr(pip,"__version__", ""),
	}
except Exception:
	pip_info={}

out={
	"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
	"zip_path": zip_path,
	"zip_sha256": zip_sha256,
	"zip_stat": zip_stat,
	"decomposer_version": decomposer_version,
	"workdir": workdir,
	"python": {
		"version": sys.version.splitlines()[0],
		"executable": sys.executable,
		"platform": platform.platform(),
		"machine": platform.machine(),
	},
	"pip": pip_info,
	"requirements": {
		"path": requirements_path,
		"sha256": req_sha256,
		"lines": req_lines,
	},
	"pip_freeze": pip_freeze,
}
json.dump(out,sys.stdout,indent=2,sort_keys=True)
sys.stdout.write("\n")
PY
echo "facts_json: $facts_json"

echo "== centaur selftest =="
"$venv_py" -m py_compile "$pkgdir/centaur.py" "$pkgdir/tests/test_centaur.py"
"$venv_py" -u "$pkgdir/centaur.py" selftest --json

echo "== done =="
echo "centaur_root: $pkgdir"
echo "centaur_venv: $venvdir"
