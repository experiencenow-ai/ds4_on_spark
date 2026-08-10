#!/usr/bin/env python3
"""Stage and verify one immutable rank-local dataset in a canonical root."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "layout" / "spark_layout.json"
MANIFEST_NAME = ".sparkpipe-dataset.json"


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def require_real_directory_tree(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    chain = [absolute]
    chain.extend(absolute.parents)
    for item in reversed(chain):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"directory component is not real: {item}")


def relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"invalid relative path: {value}")
    return path


def collect_files(source: Path, includes: list[str]) -> list[tuple[Path, Path]]:
    selected = [relative_path(value) for value in includes]
    if source.is_file():
        if selected:
            raise ValueError("--include is invalid when source is a file")
        return [(source, Path(source.name))]
    require_real_directory_tree(source)
    roots = selected or [Path(".")]
    files: dict[str, tuple[Path, Path]] = {}
    for relative in roots:
        item = source / relative
        if item.is_symlink() or not item.exists():
            raise ValueError(f"missing or symlinked source item: {item}")
        candidates = [item] if item.is_file() else sorted(item.rglob("*"))
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(f"symlink in source dataset: {candidate}")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise ValueError(f"non-regular source item: {candidate}")
            output = candidate.relative_to(source)
            if output.name == MANIFEST_NAME:
                raise ValueError(f"source contains reserved manifest: {candidate}")
            files[output.as_posix()] = (candidate, output)
    if not files:
        raise ValueError("source selection contains no files")
    return [files[name] for name in sorted(files)]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_file(source: Path, destination: Path) -> dict[str, Any]:
    before = source.stat()
    source_digest = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        source_digest = sha256_file(source)
        shutil.copy2(source, destination, follow_symlinks=False)
    digest = sha256_file(destination)
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise ValueError(f"source changed while staging: {source}")
    if source_digest is not None and digest != source_digest:
        raise ValueError(f"cross-filesystem copy digest mismatch: {source}")
    return {"bytes": before.st_size, "sha256": digest}


def verify_dataset(destination: Path) -> dict[str, Any]:
    require_real_directory_tree(destination)
    manifest_path = destination / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in manifest["files"]}
    actual = {
        item.relative_to(destination).as_posix()
        for item in destination.rglob("*")
        if item.is_file() and item.name != MANIFEST_NAME
    }
    if actual != set(expected):
        raise ValueError("dataset file set does not match manifest")
    for name, entry in expected.items():
        path = destination / relative_path(name)
        if path.is_symlink() or path.stat().st_size != entry["bytes"]:
            raise ValueError(f"dataset size mismatch: {name}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"dataset digest mismatch: {name}")
    return {
        "bytes": sum(item["bytes"] for item in expected.values()),
        "dataset": manifest["dataset"],
        "files": len(expected),
        "ok": True,
    }


def stage_dataset(node_root: Path, root_name: str, dataset: str, source: Path, includes: list[str]) -> dict[str, Any]:
    contract = load_contract()
    pattern = contract["sparkdata_name_pattern"] if root_name == "sparkdata" else contract["model_name_pattern"]
    if re.fullmatch(pattern, dataset) is None:
        raise ValueError(f"invalid {root_name} dataset name: {dataset}")
    canonical = node_root / contract["roots"][root_name]
    require_real_directory_tree(node_root)
    require_real_directory_tree(canonical)
    if source.is_symlink() or not source.exists():
        raise ValueError(f"missing or symlinked source: {source}")
    destination = canonical / dataset
    temporary = canonical / f".{dataset}.stage-{os.getpid()}"
    if destination.exists() or destination.is_symlink() or temporary.exists():
        raise ValueError(f"destination already exists: {destination}")
    temporary.mkdir()
    try:
        entries = []
        for input_path, relative in collect_files(source, includes):
            entry = stage_file(input_path, temporary / relative)
            entry["path"] = relative.as_posix()
            entries.append(entry)
        manifest = {
            "dataset": dataset,
            "files": entries,
            "format": "sparkpipe-rank-dataset-v1",
            "node": node_root.name,
            "role": root_name,
            "source": str(source),
        }
        (temporary / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return verify_dataset(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-root", default=str(Path.home()))
    parser.add_argument("--root", choices=("srcdata", "sparkdata"), required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--source")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    node_root = Path(os.path.abspath(Path(args.node_root).expanduser()))
    destination = node_root / load_contract()["roots"][args.root] / args.dataset
    try:
        if args.verify:
            if args.source is not None or args.apply:
                raise ValueError("--verify cannot be combined with --source or --apply")
            result = verify_dataset(destination)
        else:
            if not args.apply or args.source is None:
                raise ValueError("staging requires --source and --apply")
            result = stage_dataset(
                node_root, args.root, args.dataset,
                Path(os.path.abspath(Path(args.source).expanduser())), args.include
            )
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
