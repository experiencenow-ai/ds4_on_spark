#!/usr/bin/env python3
"""Create a reviewed, size-pinned cleanup manifest without changing a node."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ds4_layout_inventory import load_json, mount_state, tree_stats


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "layout" / "spark_layout.json"


def validate_path(path: Path, node_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        relative = path.resolve(strict=False).relative_to(node_root.resolve())
    except ValueError:
        return [f"path is outside node root: {path}"]
    contract = load_json(CONTRACT_PATH)
    canonical = set(contract["roots"].values())
    if not relative.parts or relative.parts[0] in canonical:
        errors.append("canonical root is protected")
    if ".git" in relative.parts or relative.parts[:2] == ("src", "ds4_on_spark"):
        errors.append("Git checkout is protected")
    if path.is_symlink():
        errors.append("symlinks are not cleanup targets")
    if not path.exists():
        errors.append("path does not exist")
    if mount_state(path)["is_mount"]:
        errors.append("mounted path is protected")
    return errors


def make_manifest(node_root: Path, paths: list[str], action: str, reason: str) -> dict[str, Any]:
    entries = []
    errors = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = node_root / path
        path = path.resolve(strict=False)
        path_errors = validate_path(path, node_root)
        if path_errors:
            errors.append({"path": str(path), "errors": path_errors})
            continue
        stats = tree_stats(path)
        bytes_on_disk = stats["unique_bytes_on_disk"]
        files = stats["unique_files"]
        entries.append(
            {
                "path": str(path),
                "action": action,
                "reason": reason,
                "bytes_on_disk": bytes_on_disk,
                "files": files,
            }
        )
    if errors:
        raise ValueError(json.dumps({"refused": errors}, indent=2))
    if not entries:
        raise ValueError("no cleanup entries")
    return {"schema_version": 1, "node": node_root.name, "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-root", default=str(Path.home()))
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--action", choices=("delete", "archive"), default="delete")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    try:
        manifest = make_manifest(
            Path(args.node_root).expanduser().resolve(), args.path, args.action, args.reason
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output == "-":
        print(payload, end="")
    else:
        Path(args.output).expanduser().write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
