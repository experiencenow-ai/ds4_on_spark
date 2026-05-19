#!/usr/bin/env python3
"""Patch Ray 2.54 startup for DS4 Spark probes by disabling client/dashboard pre-raylet blockers."""

from __future__ import annotations

import argparse
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-ray-spark-startup-no-client-dashboard"


class PatchError(RuntimeError):
    pass


def _replace(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise PatchError(f"missing expected block: {label}")
    return text.replace(old, new, 1), True


def locate_site_packages(runtime_root: Path | None, site_packages: Path | None) -> Path:
    if site_packages is not None:
        if not site_packages.exists():
            raise PatchError(f"site-packages not found: {site_packages}")
        return site_packages
    if runtime_root is None:
        raise PatchError("either --runtime-root or --site-packages is required")
    matches = sorted(glob.glob(str(runtime_root / "lib" / "python*" / "site-packages")))
    if len(matches) != 1:
        raise PatchError(f"expected one site-packages under {runtime_root}, found {matches}")
    return Path(matches[0])


def patch_scripts_py(text: str) -> str:
    old = """    has_ray_client = get_ray_client_dependency_error() is None
    if has_ray_client and ray_client_server_port is None:
        ray_client_server_port = 10001
"""
    new = """    has_ray_client = get_ray_client_dependency_error() is None
    if has_ray_client and ray_client_server_port is None:
        # DS4 Spark probe: Ray Client startup can block before raylet registration.
        ray_client_server_port = None
"""
    text, _ = _replace(text, old, new, "ray client default")
    return text


def patch_node_py(text: str) -> str:
    old = """        stdout_log_fname, stderr_log_fname = self.get_log_file_names(
            "dashboard", unique=True, create_out=True, create_err=True
        )
"""
    new = """        # DS4 Spark probe: dashboard/API server can block before raylet startup.
        self._webui_url = ""
        return

        stdout_log_fname, stderr_log_fname = self.get_log_file_names(
            "dashboard", unique=True, create_out=True, create_err=True
        )
"""
    text, _ = _replace(text, old, new, "dashboard api server")
    return text


def _write(path: Path, patched: str, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    original = path.read_text(encoding="utf-8")
    changed = original != patched
    if changed and write:
        backup = path.with_name(path.name + backup_suffix)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(patched, encoding="utf-8")
    return {"path": str(path), "changed": changed}


def apply_patch(site_packages: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    scripts = site_packages / "ray" / "scripts" / "scripts.py"
    node = site_packages / "ray" / "_private" / "node.py"
    if not scripts.exists():
        raise PatchError(f"missing target file: {scripts}")
    if not node.exists():
        raise PatchError(f"missing target file: {node}")
    scripts_patched = patch_scripts_py(scripts.read_text(encoding="utf-8"))
    node_patched = patch_node_py(node.read_text(encoding="utf-8"))
    files = {
        "ray_scripts": _write(scripts, scripts_patched, backup_suffix=backup_suffix, write=write),
        "ray_node": _write(node, node_patched, backup_suffix=backup_suffix, write=write),
    }
    return {
        "patch_id": PATCH_ID,
        "site_packages": str(site_packages),
        "write": write,
        "changed": any(item["changed"] for item in files.values()),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root")
    parser.add_argument("--site-packages")
    parser.add_argument("--backup-suffix", default=".ds4_spark_startup_bak")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    site_packages = locate_site_packages(
        Path(args.runtime_root).expanduser() if args.runtime_root else None,
        Path(args.site_packages).expanduser() if args.site_packages else None,
    )
    print(json.dumps(apply_patch(site_packages, backup_suffix=args.backup_suffix, write=not args.check), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
