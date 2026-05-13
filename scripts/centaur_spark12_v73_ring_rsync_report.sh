#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_rsync_report.sh <ring_run_id> [local_bundle_dir] [out_md]

Generate a sanitized Markdown summary for a fetched Spark12 Centaur v73 ring-rsync bundle.

This is intended to run on your Mac after:
  sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "<ring_run_id>"

Arguments:
  ring_run_id        Required (example: 20260512T123456Z)
  local_bundle_dir   Optional; defaults to:
                      /private/tmp/centaur-ring/spark12-v73/<ring_run_id>
                      /tmp/centaur-ring/spark12-v73/<ring_run_id>
  out_md             Optional; defaults to stdout

Notes:
  - Does not attempt to scrub private hostnames inside logs; review before posting.
  - Redacts obvious local username paths like /Users/<name>/ and /home/<name>/.
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
	if [ -d "/private/tmp/centaur-ring/spark12-v73/$run_id" ]; then
		local_in="/private/tmp/centaur-ring/spark12-v73/$run_id"
	elif [ -d "/tmp/centaur-ring/spark12-v73/$run_id" ]; then
		local_in="/tmp/centaur-ring/spark12-v73/$run_id"
	else
		echo "missing local bundle dir; pass it explicitly as arg2" >&2
		echo "tried: /private/tmp/centaur-ring/spark12-v73/$run_id" >&2
		echo "tried: /tmp/centaur-ring/spark12-v73/$run_id" >&2
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
import os
import re
import sys
from datetime import datetime, timezone

run_id=sys.argv[1]
bundle_dir=sys.argv[2]
out_md=sys.argv[3] if len(sys.argv) > 3 else ""

log_path=os.path.join(bundle_dir,"ring_rsync.log")
local_log_path=os.path.join(bundle_dir,"ring_rsync.local.log")
eff_dir=os.path.join(bundle_dir,"effective_manifests")

def redact_user_paths(s: str) -> str:
    if not s:
        return s
    s=re.sub(r"/Users/[^/]+/","/Users/<redacted>/",s)
    s=re.sub(r"/home/[^/]+/","/home/<redacted>/",s)
    return s

def redact_ssh_target(s: str) -> str:
    if not s:
        return s
    s=re.sub(r"\\b[a-zA-Z0-9_.-]+@[^\\s\"']+\\b","<redacted-target>",s)
    return s

def read_text(path: str) -> str:
    try:
        with open(path,"r",encoding="utf-8",errors="replace") as f:
            return f.read()
    except Exception:
        return ""

log=read_text(log_path)
local_log=read_text(local_log_path)

log_present=os.path.exists(log_path)
local_log_present=os.path.exists(local_log_path)
eff_present=os.path.isdir(eff_dir)

def grep_first(pattern: str) -> str:
    if not log:
        return ""
    m=re.search(pattern,log,re.M)
    return m.group(1).strip() if m else ""

workdir=redact_user_paths(grep_first(r"^workdir:\\s+(.+)$"))
node_count=grep_first(r"^node_count=(\\d+)$")
decomposer_version=grep_first(r"^decomposer_version:\\s+(.+)$")

python_ver=""
if log:
    m=re.search(r"^== centaur package facts ==\\s*$\\n([^\\n]+)$",log,re.M)
    if m:
        python_ver=m.group(1).strip()

def freeze_get(name: str) -> str:
    if not log:
        return ""
    m=re.search(rf"^{re.escape(name)}==([^\\s]+)\\s*$",log,re.M)
    return m.group(1).strip() if m else ""

numpy_ver=freeze_get("numpy")
scipy_ver=freeze_get("scipy")
sklearn_ver=freeze_get("scikit-learn")

ssh_line=""
if local_log:
    m=re.search(r"^ssh\\s+.+$",local_log,re.M)
    if m:
        ssh_line=m.group(0).strip()

ssh_line=redact_user_paths(redact_ssh_target(ssh_line))

def list_effective_manifests() -> list[str]:
    out=[]
    if not os.path.isdir(eff_dir):
        return out
    for fn in sorted(os.listdir(eff_dir)):
        if fn.startswith("."):
            continue
        path=os.path.join(eff_dir,fn)
        if os.path.isfile(path):
            out.append(fn)
    return out

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

effective_files=list_effective_manifests()
artifacts=list_artifacts(bundle_dir)
now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

lines=[]
lines.append(f"# Spark12 Centaur v73 ring rsync report ({run_id})")
lines.append("")
lines.append(f"Generated: `{now}`")
lines.append("")
lines.append("## Classification (pick one)")
lines.append("")
lines.append("- **Centaur bug**: a `centaur.py` command fails due to parsing/schema/state/logic.")
lines.append("- **DS4 runtime bug**: host/runtime prevents Centaur from running (deps, permissions, mesh/rsync).")
lines.append("")
lines.append("## Bundle location (Mac)")
lines.append("")
lines.append(f"- `local_bundle_dir`: `{redact_user_paths(bundle_dir)}`")
lines.append("- evidence files:")
lines.append(f"  - `ring_rsync.log`: {'present' if log_present else 'missing'}")
lines.append(f"  - `ring_rsync.local.log`: {'present' if local_log_present else 'missing'}")
lines.append(f"  - `effective_manifests/`: {'present' if eff_present else 'missing'}")
lines.append("")
lines.append("## Ring facts (from `ring_rsync.log`)")
lines.append("")
if workdir:
    lines.append(f"- `ring_workdir`: `{workdir}`")
if node_count:
    lines.append(f"- `node_count`: `{node_count}`")
if python_ver:
    lines.append(f"- `python3 -V`: `{python_ver}`")
if decomposer_version:
    lines.append(f"- `decomposer_version`: `{decomposer_version}`")
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
if ssh_line:
    lines.append("Observed (from `ring_rsync.local.log`; review/redact before posting):")
    lines.append("")
    lines.append("```bash")
    lines.append(ssh_line)
    lines.append("```")
else:
    lines.append("- Add the exact `ssh ...` command you used to run the ring wrapper.")
lines.append("")
lines.append("## Outputs")
lines.append("")
if effective_files:
    lines.append("- `effective_manifests/`:")
    for fn in effective_files[:25]:
        lines.append(f"  - `{fn}`")
else:
    lines.append("- `effective_manifests/`: (none detected)")
lines.append("")
lines.append("## Artifacts (local bundle listing)")
lines.append("")
lines.append("```text")
for rel,size in artifacts[:80]:
    if size is None:
        lines.append(f"{rel}")
    else:
        lines.append(f"{rel} ({size} bytes)")
if len(artifacts) > 80:
    lines.append(f"... ({len(artifacts)-80} more)")
lines.append("```")
lines.append("")
lines.append("## Notes")
lines.append("")
lines.append("- Review logs for private hostnames/IPs and redact before sharing.")
lines.append("- For the shared checklist + sanitization rules, see `docs/centaur-bug-report.md`.")
lines.append("")

md="\\n".join(lines)
if out_md:
    with open(out_md,"w",encoding="utf-8") as f:
        f.write(md)
else:
    sys.stdout.write(md)
PY
