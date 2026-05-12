#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark0_v73_smoke_report.sh <run_id> [local_bundle_dir] [out_md]

Generate a sanitized Markdown summary for a fetched Spark0 Centaur v73 smoke bundle.

This is intended to run on your Mac after:
  sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "<run_id>"

Arguments:
  run_id            Required (example: 20260512T073455Z)
  local_bundle_dir  Optional; defaults to:
                     /private/tmp/centaur-smoke/spark0-v73/<run_id>
                     /tmp/centaur-smoke/spark0-v73/<run_id>
  out_md            Optional; defaults to stdout (useful for piping into PRs/issues)

Notes:
  - Does not attempt to scrub hostnames inside logs; review before posting.
  - Redacts obvious local username paths like /Users/<name>/.
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
out_md="${3:-}"

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

need_cmd python3

python3 - "$run_id" "$local_in" "$out_md" <<'PY'
import json
import os
import re
import sys
from datetime import datetime, timezone

run_id=sys.argv[1]
bundle_dir=sys.argv[2]
out_md=sys.argv[3] if len(sys.argv) > 3 else ""

facts_path=os.path.join(bundle_dir,"smoke_facts.json")
freeze_path=os.path.join(bundle_dir,"pip_freeze.txt")
log_path=os.path.join(bundle_dir,"smoke.log")

def redact_user_paths(s: str) -> str:
    if not s:
        return s
    s=re.sub(r"/Users/[^/]+/","/Users/<redacted>/",s)
    s=re.sub(r"\\b/home/[^/]+/","/home/<redacted>/",s)
    return s

def read_json(path: str):
    try:
        with open(path,"r",encoding="utf-8",errors="replace") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str):
    try:
        with open(path,"r",encoding="utf-8",errors="replace") as f:
            return f.read()
    except Exception:
        return ""

facts=read_json(facts_path) or {}
freeze=read_text(freeze_path)
log=read_text(log_path)

zip_path=redact_user_paths(facts.get("zip_path","") or "")
zip_sha256=facts.get("zip_sha256","") or ""
zip_stat=facts.get("zip_stat") or {}
zip_mtime=zip_stat.get("mtime_utc","") or ""
zip_size=zip_stat.get("size_bytes","")
decomposer_version=facts.get("decomposer_version","") or ""

py=facts.get("python") or {}
py_ver=py.get("version","") or ""
py_exe=redact_user_paths(py.get("executable","") or "")
py_platform=py.get("platform","") or ""
py_machine=py.get("machine","") or ""

pip=facts.get("pip") or {}
pip_ver=pip.get("version","") or ""

req=facts.get("requirements") or {}
req_sha=req.get("sha256","") or ""
req_lines=req.get("lines") or []
if not isinstance(req_lines,list):
    req_lines=[]

def freeze_get(name: str) -> str:
    for line in freeze.splitlines():
        if line.startswith(name+"=="):
            return line.split("==",1)[1].strip()
    return ""

numpy_ver=freeze_get("numpy")
scipy_ver=freeze_get("scipy")
sklearn_ver=freeze_get("scikit-learn")

if not zip_sha256 and log:
    m=re.search(r"^zip_sha256: (.+)$",log,re.M)
    if m:
        zip_sha256=m.group(1).strip()
if not decomposer_version and log:
    m=re.search(r"^decomposer_version: (.+)$",log,re.M)
    if m:
        decomposer_version=m.group(1).strip()

def list_artifacts(root: str):
    out=[]
    for base,dirs,files in os.walk(root):
        dirs.sort()
        files.sort()
        for fn in files:
            p=os.path.join(base,fn)
            rel=os.path.relpath(p,root)
            if rel.startswith("."):
                continue
            try:
                st=os.stat(p)
                out.append((rel,int(st.st_size)))
            except Exception:
                out.append((rel,None))
    return out

artifacts=list_artifacts(bundle_dir)
now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

lines=[]
lines.append(f"# Spark0 Centaur v73 smoke report ({run_id})")
lines.append("")
lines.append(f"Generated: `{now}`")
lines.append("")
lines.append("## Classification (pick one)")
lines.append("")
lines.append("- **Centaur bug**: a `centaur.py` command fails due to parsing/schema/state/logic.")
lines.append("- **DS4 runtime bug**: host/runtime prevents Centaur from running (deps, permissions, missing wheels).")
lines.append("")
lines.append("## Bundle location (Mac)")
lines.append("")
lines.append(f"- `local_bundle_dir`: `{redact_user_paths(bundle_dir)}`")
lines.append("")
lines.append("## Centaur package facts")
lines.append("")
if zip_path:
    lines.append(f"- `zip_path`: `{zip_path}`")
if zip_mtime:
    lines.append(f"- `zip_mtime_utc`: `{zip_mtime}`")
if zip_size != "":
    lines.append(f"- `zip_size_bytes`: `{zip_size}`")
if zip_sha256:
    lines.append(f"- `zip_sha256`: `{zip_sha256}`")
if decomposer_version:
    lines.append(f"- `decomposer_version`: `{decomposer_version}`")
if req_sha:
    lines.append(f"- `requirements_sha256`: `{req_sha}`")
if req_lines:
    lines.append("- `requirements.txt`:")
    for line in req_lines[:25]:
        lines.append(f"  - `{line}`")
lines.append("")
lines.append("## Python + deps")
lines.append("")
if py_ver:
    lines.append(f"- `python`: `{py_ver}`")
if py_machine:
    lines.append(f"- `machine`: `{py_machine}`")
if py_platform:
    lines.append(f"- `platform`: `{py_platform}`")
if py_exe:
    lines.append(f"- `venv_executable`: `{py_exe}`")
if pip_ver:
    lines.append(f"- `pip`: `{pip_ver}`")
if numpy_ver or scipy_ver or sklearn_ver:
    lines.append("- key deps:")
    if numpy_ver:
        lines.append(f"  - `numpy=={numpy_ver}`")
    if scipy_ver:
        lines.append(f"  - `scipy=={scipy_ver}`")
    if sklearn_ver:
        lines.append(f"  - `scikit-learn=={sklearn_ver}`")
lines.append("")
lines.append("## Spark commands run (fill in)")
lines.append("")
lines.append("```bash")
lines.append('export SSH_OPTS="..."')
lines.append(f"export CENTAUR_RUN_ID={run_id}")
lines.append("sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>")
lines.append("```")
lines.append("")
lines.append("## Artifacts present")
lines.append("")
if artifacts:
    for rel,size in artifacts[:200]:
        if size is None:
            lines.append(f"- `{rel}`")
        else:
            lines.append(f"- `{rel}` ({size} bytes)")
    if len(artifacts) > 200:
        lines.append(f"- ... ({len(artifacts)-200} more)")
else:
    lines.append("- (none found)")
lines.append("")
lines.append("## Notes")
lines.append("")
lines.append("- Review `smoke.log` and any `hyor_dashboard/` output for hostnames/paths before posting.")
lines.append("- Prefer attaching `smoke_facts.json` + `pip_freeze.txt` for reproducible version context.")
lines.append("")

md="\n".join(lines)
if out_md:
    os.makedirs(os.path.dirname(out_md) or ".",exist_ok=True)
    with open(out_md,"w",encoding="utf-8") as f:
        f.write(md)
else:
    sys.stdout.write(md)
    sys.stdout.write("\n")
PY
if [ "$out_md" != "" ]; then
	echo "wrote: $out_md"
fi
