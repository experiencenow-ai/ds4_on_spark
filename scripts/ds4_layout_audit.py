#!/usr/bin/env python3
"""Audit one Spark node against the repository-owned storage layout contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "layout" / "spark_layout.json"


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def path_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.exists():
        return "file"
    return "missing"


def bytes_on_disk(path: Path) -> int:
    total = 0
    if path.is_file():
        return path.stat().st_blocks * 512
    if not path.is_dir():
        return 0
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
        for name in files:
            item = Path(root) / name
            try:
                info = item.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_blocks * 512
    return total


def file_count(path: Path) -> int:
    if path.is_file():
        return 1
    if not path.is_dir():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def git_state(path: Path) -> dict[str, Any]:
    probe = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return {"is_git": False}
    result = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "is_git": True,
        "head": head.stdout.strip(),
        "dirty": bool(result.stdout.strip()),
    }


def direct_children(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir():
        return []
    rows = []
    for item in sorted(path.iterdir()):
        rows.append(
            {
                "name": item.name,
                "kind": path_kind(item),
                "bytes_on_disk": bytes_on_disk(item),
                "files": file_count(item),
            }
        )
    return rows


def validate_dataset_names(path: Path, pattern: str) -> dict[str, Any]:
    if not path.is_dir():
        return {"unknown": [], "invalid": []}
    matcher = re.compile(pattern)
    unknown = []
    invalid = []
    for item in sorted(path.iterdir()):
        if item.name.startswith("."):
            continue
        if not item.is_dir():
            unknown.append(item.name)
        elif not matcher.fullmatch(item.name):
            invalid.append(item.name)
    return {"unknown": unknown, "invalid": invalid}


def audit(node_root: Path) -> dict[str, Any]:
    contract = load_contract()
    node = node_root.name
    roots = contract["roots"]
    report: dict[str, Any] = {
        "schema_version": contract["schema_version"],
        "node": node,
        "node_root": str(node_root),
        "paths": {},
        "legacy": {},
        "datasets": {},
        "repo": {},
    }
    for role, relative in roots.items():
        path = node_root / relative
        report["paths"][role] = {
            "path": str(path),
            "kind": path_kind(path),
            "target": os.readlink(path) if path.is_symlink() else None,
            "bytes_on_disk": bytes_on_disk(path),
            "files": file_count(path),
            "children": direct_children(path),
        }
    for legacy, canonical in contract["legacy_aliases"].items():
        path = node_root / legacy
        report["legacy"][legacy] = {
            "canonical": canonical,
            "path": str(path),
            "kind": path_kind(path),
            "target": os.readlink(path) if path.is_symlink() else None,
            "bytes_on_disk": bytes_on_disk(path),
            "files": file_count(path),
        }
    report["datasets"]["sparkdata"] = validate_dataset_names(
        node_root / roots["sparkdata"], contract["sparkdata_name_pattern"]
    )
    report["datasets"]["srcdata"] = validate_dataset_names(
        node_root / roots["srcdata"], contract["model_name_pattern"]
    )
    repo = node_root / roots["repo"]
    report["repo"] = git_state(repo)
    report["ok"] = (
        report["paths"]["repo"]["kind"] in {"directory", "symlink"}
        and report["paths"]["sparkdata"]["kind"] == "directory"
        and report["paths"]["srcdata"]["kind"] == "directory"
        and report["datasets"]["sparkdata"]["unknown"] == []
        and report["datasets"]["sparkdata"]["invalid"] == []
        and report["datasets"]["srcdata"]["unknown"] == []
        and report["datasets"]["srcdata"]["invalid"] == []
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-root", default=str(Path.home()))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit(Path(args.node_root).expanduser().resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"node={report['node']} ok={report['ok']} schema={report['schema_version']}")
        for role, data in report["paths"].items():
            print(f"{role}: {data['kind']} files={data['files']} bytes={data['bytes_on_disk']} path={data['path']}")
        for legacy, data in report["legacy"].items():
            print(f"legacy:{legacy}: {data['kind']} files={data['files']} bytes={data['bytes_on_disk']} target={data['target']}")
        if report["datasets"]["sparkdata"]["invalid"]:
            print("invalid sparkdata: " + ",".join(report["datasets"]["sparkdata"]["invalid"]))
        if report["datasets"]["srcdata"]["invalid"]:
            print("invalid srcdata: " + ",".join(report["datasets"]["srcdata"]["invalid"]))
        if report["repo"]:
            print("repo=" + json.dumps(report["repo"], sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
