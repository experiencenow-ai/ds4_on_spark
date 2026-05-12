#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_redact_fixture_bundle.sh <bundle_dir>

Best-effort redaction for commit-ready Centaur fixture bundles.

This is intentionally narrow: it only redacts hostnames/IPs that commonly show
up in captured logs and dashboards (for example "spark0@foo.local" or JSON
"hostname" fields). It does not attempt to fully anonymize every possible path
or identifier.

Edits files in-place.

Environment:
  REDACT_DISABLE=1   Skip redaction (no-op).
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

if [ "${REDACT_DISABLE:-0}" = "1" ]; then
	echo "== redaction disabled (REDACT_DISABLE=1) =="
	exit 0
fi

bundle_dir="$1"
if [ ! -d "$bundle_dir" ]; then
	echo "bundle_dir not found: $bundle_dir" >&2
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

python3 - "$bundle_dir" <<'PY'
import os
import re
import sys

root = sys.argv[1]

def should_edit(path: str) -> bool:
    base = os.path.basename(path)
    if base in ("README.md", "smoke.log", "ring_sim.log", "ring_rsync.log", "dashboard.json", "dashboard.html"):
        return True
    if base.endswith(".log") or base.endswith(".md") or base.endswith(".json") or base.endswith(".html") or base.endswith(".txt"):
        return True
    return False

spark_user_re = re.compile(r"\b(spark[0-9]+)@([A-Za-z0-9][A-Za-z0-9._-]*)\b")
mdns_host_re = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9._-]*\.local\b")
ipv4_re = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

json_hostname_re = re.compile(r'("hostname"\s*:\s*")[^"]*(")')
html_hostname_re = re.compile(r"(&quot;hostname&quot;\s*:\s*&quot;)[^&]*(&quot;)")

def redact_text(text: str) -> str:
    text = spark_user_re.sub(lambda m: f"{m.group(1)}@<{m.group(1)}-host>", text)
    text = mdns_host_re.sub("<redacted-host>.local", text)
    text = ipv4_re.sub("<redacted-ip>", text)
    text = json_hostname_re.sub(r'\1<redacted-hostname>\2', text)
    text = html_hostname_re.sub(r"\1<redacted-hostname>\2", text)
    return text

edited = 0
for dirpath, _, filenames in os.walk(root):
    for name in filenames:
        path = os.path.join(dirpath, name)
        if not should_edit(path):
            continue
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        new_text = redact_text(text)
        if new_text != text:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_text)
            edited += 1

print(f"redacted_files: {edited}")
PY

