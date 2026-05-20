#!/usr/bin/env python3
"""Prepare Python development headers for Triton JIT without sudo."""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_PACKAGES = ("python3.12-dev", "libpython3.12-dev")


class HeaderPrepError(RuntimeError):
    pass


def include_path(root: Path, *, python_version: str, arch_triplet: str) -> str:
    include_root = root / "usr" / "include"
    return ":".join(
        str(path)
        for path in (
            include_root,
            include_root / f"python{python_version}",
            include_root / arch_triplet / f"python{python_version}",
        )
    )


def _run(args: list[str], *, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def _extract_package(download_dir: Path, output_dir: Path, package: str) -> None:
    matches = sorted(glob.glob(str(download_dir / f"{package}_*.deb")))
    if not matches:
        raise HeaderPrepError(f"downloaded package not found: {package}")
    _run(["dpkg-deb", "-x", matches[-1], str(output_dir)], cwd=download_dir)


def prepare_headers(
    *,
    output_dir: Path,
    download_dir: Path,
    packages: tuple[str, ...],
    python_version: str,
    arch_triplet: str,
) -> dict[str, Any]:
    if not shutil.which("apt-get"):
        raise HeaderPrepError("apt-get is required")
    if not shutil.which("dpkg-deb"):
        raise HeaderPrepError("dpkg-deb is required")
    download_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(["apt-get", "download", *packages], cwd=download_dir)
    for package in packages:
        _extract_package(download_dir, output_dir, package)
    header = output_dir / "usr" / "include" / f"python{python_version}" / "Python.h"
    pyconfig = output_dir / "usr" / "include" / arch_triplet / f"python{python_version}" / "pyconfig.h"
    if not header.exists():
        raise HeaderPrepError(f"missing extracted header: {header}")
    if not pyconfig.exists():
        raise HeaderPrepError(f"missing extracted pyconfig: {pyconfig}")
    env_path = include_path(output_dir, python_version=python_version, arch_triplet=arch_triplet)
    return {
        "format": "ds4-vllm-python-headers-v1",
        "output_dir": str(output_dir),
        "download_dir": str(download_dir),
        "packages": list(packages),
        "python_h": str(header),
        "pyconfig_h": str(pyconfig),
        "c_include_path": env_path,
        "cpath": env_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="/tmp/ds4-python312-dev")
    parser.add_argument("--download-dir", default="/tmp/ds4-python312-dev-debs")
    parser.add_argument("--python-version", default="3.12")
    parser.add_argument("--arch-triplet", default="aarch64-linux-gnu")
    parser.add_argument("--package", action="append", dest="packages")
    args = parser.parse_args()
    result = prepare_headers(
        output_dir=Path(args.output_dir).expanduser(),
        download_dir=Path(args.download_dir).expanduser(),
        packages=tuple(args.packages) if args.packages else DEFAULT_PACKAGES,
        python_version=args.python_version,
        arch_triplet=args.arch_triplet,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
