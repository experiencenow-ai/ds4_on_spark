#!/usr/bin/env python3
"""Apply an explicit, size-checked cleanup manifest to one Spark node.

The default operation is a read-only validation/plan. Applying a manifest is
deliberately narrow: it cannot target canonical roots, mounts, symlinks, a
Git checkout, or a path that changed since the inventory was captured.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "layout" / "spark_layout.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_stats(path: Path) -> tuple[int, int]:
    total = 0
    files = 0
    seen: set[tuple[int, int]] = set()
    if path.is_file():
        info = path.stat(follow_symlinks=False)
        return info.st_blocks * 512, 1
    if not path.is_dir():
        return 0, 0
    for root, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
        for name in names:
            item = Path(root) / name
            try:
                info = item.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            inode = (info.st_dev, info.st_ino)
            if inode in seen:
                continue
            seen.add(inode)
            total += info.st_blocks * 512
            files += 1
    return total, files


def is_open(path: Path) -> tuple[bool, str]:
    lsof = shutil.which("lsof")
    if lsof is not None:
        result = subprocess.run(
            [lsof, "-Fn", "--", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, "lsof reports an open path"
        return False, "lsof clear"
    fuser = shutil.which("fuser")
    if fuser is not None:
        result = subprocess.run(
            [fuser, "-m", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, "fuser reports an open path"
        return False, "fuser clear"
    return True, "neither lsof nor fuser is available"


def is_mount(path: Path) -> bool:
    if os.path.ismount(path):
        return True
    findmnt = shutil.which("findmnt")
    if findmnt is None:
        return False
    result = subprocess.run(
        [findmnt, "-T", str(path), "-n", "-o", "TARGET"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False
    target = result.stdout.strip().splitlines()[-1].strip()
    return Path(target).resolve() == path.resolve()


def validate_entry(entry: dict[str, Any], node_root: Path) -> list[str]:
    errors: list[str] = []
    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or raw_path == "":
        return ["path is required"]
    path = Path(raw_path).expanduser()
    try:
        relative = path.resolve(strict=False).relative_to(node_root.resolve())
    except ValueError:
        return [f"path is outside node root: {path}"]
    if str(relative) in {"", "."}:
        errors.append("node root itself is not a cleanup target")
    canonical = set(load_json(CONTRACT_PATH)["roots"].values())
    if relative.parts and relative.parts[0] in canonical:
        errors.append(f"canonical root is protected: {relative.parts[0]}")
    if ".git" in relative.parts or relative.parts[:2] == ("src", "ds4_on_spark"):
        errors.append("Git checkout is protected")
    if path.is_symlink():
        errors.append("symlinks are not cleanup targets")
    if not path.exists():
        errors.append("path does not exist")
        return errors
    if is_mount(path):
        errors.append("mounted path is protected")
    expected_bytes = entry.get("bytes_on_disk")
    expected_files = entry.get("files")
    actual_bytes, actual_files = tree_stats(path)
    if not isinstance(expected_bytes, int) or actual_bytes != expected_bytes:
        errors.append(f"size changed: expected={expected_bytes} actual={actual_bytes}")
    if not isinstance(expected_files, int) or actual_files != expected_files:
        errors.append(f"file count changed: expected={expected_files} actual={actual_files}")
    opened, reason = is_open(path)
    if opened:
        errors.append(reason)
    return errors


def receipt_path(node_root: Path) -> Path:
    receipt_dir = node_root / "sparkdata" / ".layout" / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    return receipt_dir / f"cleanup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"


def apply_entry(entry: dict[str, Any], node_root: Path, archive_root: Path | None) -> dict[str, Any]:
    path = Path(entry["path"]).expanduser()
    action = entry.get("action", "delete")
    result: dict[str, Any] = {"path": str(path), "action": action}
    if action == "delete":
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        result["status"] = "deleted"
        return result
    if action == "archive":
        if archive_root is None:
            raise ValueError("archive action requires --archive-root")
        relative = path.resolve(strict=False).relative_to(node_root.resolve())
        target = archive_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"archive target exists: {target}")
        shutil.move(str(path), str(target))
        result.update({"status": "archived", "target": str(target)})
        return result
    raise ValueError(f"unsupported action: {action}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-root", default=str(Path.home()))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive-root")
    args = parser.parse_args()
    node_root = Path(args.node_root).expanduser().resolve()
    manifest = load_json(Path(args.manifest).expanduser().resolve())
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        print("manifest must contain a non-empty entries list", file=sys.stderr)
        return 64
    if manifest.get("node") not in (None, "*", node_root.name):
        print(f"manifest node does not match {node_root.name}", file=sys.stderr)
        return 64
    checked: list[dict[str, Any]] = []
    failed = False
    for entry in entries:
        if not isinstance(entry, dict):
            checked.append({"status": "invalid", "error": "entry is not an object"})
            failed = True
            continue
        errors = validate_entry(entry, node_root)
        row = {"path": entry.get("path"), "errors": errors}
        if errors:
            row["status"] = "refused"
            failed = True
        else:
            row["status"] = "ready"
        checked.append(row)
    print(json.dumps({"node": node_root.name, "entries": checked}, indent=2, sort_keys=True))
    if failed or not args.apply:
        return 1 if failed else 0
    archive_root = Path(args.archive_root).expanduser().resolve() if args.archive_root else None
    results = []
    for entry in entries:
        results.append(apply_entry(entry, node_root, archive_root))
    receipt = {
        "schema_version": 1,
        "node": node_root.name,
        "manifest": str(Path(args.manifest).expanduser().resolve()),
        "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
    }
    path = receipt_path(node_root)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"receipt={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
