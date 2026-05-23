#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: scripts/archive_fixture.sh FIXTURE_PATH [--archive-root PATH] [--manifest PATH] [--repo-root PATH]

Moves a fixture file or directory into the archive tier, leaves an archived-fixture
stub at the original path, and records checksums in fixtures/fixtures_manifest.json.
USAGE
}

SOURCE=""
ARCHIVE_ROOT="${CENTAUR_ARCHIVE_ROOT:-/Volumes/CentaurArchive}"
MANIFEST="fixtures/fixtures_manifest.json"
REPO_ROOT="$(pwd)"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --archive-root)
      ARCHIVE_ROOT="$2"
      shift 2
      ;;
    --manifest)
      MANIFEST="$2"
      shift 2
      ;;
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ -n "$SOURCE" ]; then
        usage >&2
        exit 2
      fi
      SOURCE="$1"
      shift
      ;;
  esac
done

if [ -z "$SOURCE" ]; then
  usage >&2
  exit 2
fi

python3 - "$SOURCE" "$ARCHIVE_ROOT" "$MANIFEST" "$REPO_ROOT" <<'PY'
import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path

source_arg, archive_root_arg, manifest_arg, repo_root_arg = sys.argv[1:5]
repo_root = Path(repo_root_arg).resolve()
source = Path(source_arg)
if not source.is_absolute():
    source = repo_root / source
source = source.resolve()
archive_root = Path(archive_root_arg).resolve()
manifest = Path(manifest_arg)
if not manifest.is_absolute():
    manifest = repo_root / manifest
manifest = manifest.resolve()
if not source.exists():
    raise SystemExit(f"source does not exist: {source}")
try:
    relative = source.relative_to(repo_root)
except ValueError as exc:
    raise SystemExit(f"source must be inside repo root: {source}") from exc

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def collect(path: Path):
    if path.is_file():
        size = path.stat().st_size
        digest = file_sha256(path)
        return size, digest, [{"path": path.name, "sha256": digest, "size_bytes": size}]
    files = []
    total = 0
    tree = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        rel = item.relative_to(path).as_posix()
        digest = file_sha256(item)
        size = item.stat().st_size
        total += size
        files.append({"path": rel, "sha256": digest, "size_bytes": size})
        tree.update(rel.encode("utf-8"))
        tree.update(b"\0")
        tree.update(digest.encode("ascii"))
        tree.update(b"\0")
    return total, tree.hexdigest(), files

size_bytes, sha256, files = collect(source)
archive_path = archive_root / relative
if archive_path.exists():
    raise SystemExit(f"archive destination already exists: {archive_path}")
archive_path.parent.mkdir(parents=True, exist_ok=True)
shutil.move(str(source), str(archive_path))
archived_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
entry = {
    "path": relative.as_posix(),
    "sha256": sha256,
    "size_bytes": size_bytes,
    "archived_at": archived_at,
    "archive_path": str(archive_path),
    "kind": "directory" if archive_path.is_dir() else "file",
    "file_count": len(files),
    "files": files,
}
if manifest.exists():
    payload = json.loads(manifest.read_text(encoding="utf-8"))
else:
    payload = {"format": "centaur-fixtures-manifest-v1", "entries": []}
payload["entries"] = [row for row in payload.get("entries", []) if row.get("path") != entry["path"]]
payload["entries"].append(entry)
payload["entries"] = sorted(payload["entries"], key=lambda row: row["path"])
manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
stub = {
    "format": "centaur-archived-fixture-stub-v1",
    "path": entry["path"],
    "sha256": entry["sha256"],
    "size_bytes": entry["size_bytes"],
    "archived_at": entry["archived_at"],
    "archive_path": entry["archive_path"],
    "manifest_path": str(manifest.relative_to(repo_root)),
}
if entry["kind"] == "directory":
    source.mkdir(parents=True, exist_ok=True)
    stub_path = source / "ARCHIVED_FIXTURE.json"
else:
    source.parent.mkdir(parents=True, exist_ok=True)
    stub_path = source
stub_path.write_text(json.dumps(stub, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"archived": entry["path"], "archive_path": entry["archive_path"], "manifest": str(manifest.relative_to(repo_root)), "sha256": entry["sha256"], "size_bytes": entry["size_bytes"]}, sort_keys=True))
PY
