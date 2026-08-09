#!/usr/bin/env python3
"""Inventory canonical and legacy storage without changing a Spark node."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "layout" / "spark_layout.json"
POLICY_PATH = REPO_ROOT / "layout" / "model_storage_policy.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def path_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.exists():
        return "file"
    return "missing"


def tree_stats(path: Path) -> dict[str, Any]:
    total = 0
    files = 0
    inodes: set[tuple[int, int]] = set()
    if path.is_file():
        info = path.stat(follow_symlinks=False)
        return {
            "bytes_on_disk": info.st_blocks * 512,
            "files": 1,
            "unique_bytes_on_disk": info.st_blocks * 512,
            "unique_files": 1,
        }
    if not path.is_dir():
        return {
            "bytes_on_disk": 0,
            "files": 0,
            "unique_bytes_on_disk": 0,
            "unique_files": 0,
        }
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
            files += 1
            total += info.st_blocks * 512
            inode = (info.st_dev, info.st_ino)
            if inode not in inodes:
                inodes.add(inode)
    unique_total = 0
    unique_files = 0
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
            if (info.st_dev, info.st_ino) in inodes:
                unique_total += info.st_blocks * 512
                unique_files += 1
                inodes.remove((info.st_dev, info.st_ino))
    return {
        "bytes_on_disk": total,
        "files": files,
        "unique_bytes_on_disk": unique_total,
        "unique_files": unique_files,
    }


def child_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir():
        return []
    rows = []
    for item in sorted(path.iterdir()):
        row = {"name": item.name, "kind": path_kind(item)}
        row.update(tree_stats(item))
        rows.append(row)
    return rows


def mount_state(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"is_mount": os.path.ismount(path)}
    findmnt_path = shutil.which("findmnt")
    if findmnt_path is None:
        return result
    findmnt = subprocess.run(
        [findmnt_path, "-T", str(path), "-n", "-o", "SOURCE,FSTYPE,TARGET"],
        check=False,
        capture_output=True,
        text=True,
    )
    if findmnt.returncode == 0 and findmnt.stdout.strip():
        line = findmnt.stdout.strip()
        result["findmnt"] = line
        target = line.split()[-1]
        result["is_mount"] = Path(target).resolve() == path.resolve()
    return result


def root_row(node_root: Path, name: str) -> dict[str, Any]:
    path = node_root / name
    row = {
        "path": str(path),
        "kind": path_kind(path),
        "target": os.readlink(path) if path.is_symlink() else None,
    }
    row.update(tree_stats(path))
    row["mount"] = mount_state(path)
    row["children"] = child_rows(path)
    return row


def inventory(node_root: Path) -> dict[str, Any]:
    contract = load_json(CONTRACT_PATH)
    policy = load_json(POLICY_PATH)
    canonical = set(contract["roots"].values())
    legacy = {
        "models",
        "sparkpipe_artifacts",
        "sparkpipe_runtime",
        "sparkpipe_state",
        "ds4_waterfall",
        "ds4_repair",
        "ds4_on_spark_releases",
        "vllm-logs",
        "vllm-lazy-logs",
    }
    rows: dict[str, Any] = {
        "schema_version": 1,
        "node": node_root.name,
        "node_root": str(node_root),
        "canonical": {name: root_row(node_root, name) for name in sorted(canonical)},
        "legacy": {name: root_row(node_root, name) for name in sorted(legacy)},
        "policy_models": sorted(policy["policies"]),
        "unclassified_top_level": [],
    }
    if node_root.is_dir():
        rows["unclassified_top_level"] = sorted(
            item.name
            for item in node_root.iterdir()
            if item.name not in canonical and item.name not in legacy
        )
    return rows


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f}{unit}"
        amount /= 1024
    return f"{amount:.1f}TiB"


def print_summary(report: dict[str, Any]) -> None:
    print(f"node={report['node']} root={report['node_root']}")
    for section in ("canonical", "legacy"):
        print(f"[{section}]")
        for name, row in report[section].items():
            print(
                f"{name}: {row['kind']} {human_bytes(row['unique_bytes_on_disk'])} "
                f"files={row['files']} mount={row['mount']['is_mount']}"
            )
    print("[unclassified top-level]")
    print(",".join(report["unclassified_top_level"]) or "none")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-root", default=str(Path.home()))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = inventory(Path(args.node_root).expanduser().resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
