#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: scripts/archive_restore.sh FIXTURE_PATH [--manifest PATH] [--repo-root PATH] [--force]

Restores an archived fixture from the archive path recorded in the fixtures
manifest. By default it only replaces an archived-fixture stub.
USAGE
}

TARGET=""
MANIFEST="fixtures/fixtures_manifest.json"
REPO_ROOT="$(pwd)"
FORCE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --manifest)
      MANIFEST="$2"
      shift 2
      ;;
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ -n "$TARGET" ]; then
        usage >&2
        exit 2
      fi
      TARGET="$1"
      shift
      ;;
  esac
done

if [ -z "$TARGET" ]; then
  usage >&2
  exit 2
fi

python3 - "$TARGET" "$MANIFEST" "$REPO_ROOT" "$FORCE" <<'PY'
import hashlib
import json
import shutil
import sys
from pathlib import Path

target_arg, manifest_arg, repo_root_arg, force_arg = sys.argv[1:5]
repo_root = Path(repo_root_arg).resolve()
target = Path(target_arg)
if not target.is_absolute():
    target = repo_root / target
target = target.resolve()
manifest = Path(manifest_arg)
if not manifest.is_absolute():
    manifest = repo_root / manifest
manifest = manifest.resolve()
force = force_arg == "1"
if not manifest.exists():
    raise SystemExit(f"manifest does not exist: {manifest}")
try:
    relative = target.relative_to(repo_root).as_posix()
except ValueError as exc:
    raise SystemExit(f"target must be inside repo root: {target}") from exc
payload = json.loads(manifest.read_text(encoding="utf-8"))
entry = next((row for row in payload.get("entries", []) if row.get("path") == relative), None)
if entry is None:
    raise SystemExit(f"no manifest entry for: {relative}")
archive_path = Path(str(entry["archive_path"]))
if not archive_path.exists():
    raise SystemExit(f"archive path does not exist: {archive_path}")

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def tree_sha256(path: Path) -> str:
    if path.is_file():
        return file_sha256(path)
    h = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        rel = item.relative_to(path).as_posix()
        digest = file_sha256(item)
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()

def is_stub(path: Path) -> bool:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("format") == "centaur-archived-fixture-stub-v1"
        except Exception:
            return False
    stub = path / "ARCHIVED_FIXTURE.json"
    if stub.is_file() and len(list(path.iterdir())) == 1:
        try:
            return json.loads(stub.read_text(encoding="utf-8")).get("format") == "centaur-archived-fixture-stub-v1"
        except Exception:
            return False
    return False

if target.exists():
    if not force and not is_stub(target):
        raise SystemExit(f"target exists and is not an archive stub; pass --force to replace: {target}")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
target.parent.mkdir(parents=True, exist_ok=True)
if archive_path.is_dir():
    shutil.copytree(archive_path, target)
else:
    shutil.copy2(archive_path, target)
restored_sha256 = tree_sha256(target)
if restored_sha256 != entry["sha256"]:
    raise SystemExit(f"checksum mismatch after restore: {restored_sha256} != {entry['sha256']}")
print(json.dumps({"restored": relative, "archive_path": str(archive_path), "sha256": restored_sha256}, sort_keys=True))
PY
