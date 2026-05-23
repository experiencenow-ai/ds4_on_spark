#!/usr/bin/env python3
"""Shared helpers for narrow vLLM patch scripts."""

from __future__ import annotations

import difflib
import glob
import shutil
from pathlib import Path
from typing import Any


def replace_once(text: str, old: str, new: str, label: str, *, error_type: type[Exception] = RuntimeError) -> tuple[str, bool]:
	if new in text:
		return text, False
	if old not in text:
		raise error_type(f"missing expected block: {label}")
	return text.replace(old, new, 1), True


def replace_count(text: str, old: str, new: str, count: int, label: str, *, error_type: type[Exception] = RuntimeError) -> tuple[str, bool]:
	if text.count(new) == count:
		return text, False
	found = text.count(old)
	if found != count:
		raise error_type(f"expected {count} blocks for {label}, found {found}")
	return text.replace(old, new, count), True


def write_patch_file(path: Path, original: str, patched: str, *, backup_suffix: str, write: bool) -> dict[str, Any]:
	changed = original != patched
	if changed and write:
		backup = path.with_name(path.name + backup_suffix)
		if not backup.exists():
			shutil.copy2(path, backup)
		path.write_text(patched, encoding="utf-8")
	diff = ""
	if changed:
		diff = "".join(
			difflib.unified_diff(
				original.splitlines(True),
				patched.splitlines(True),
				fromfile=str(path),
				tofile=str(path),
			)
		)
	return {"path": str(path), "changed": changed, "diff": diff}


def locate_vllm_package_dir(runtime_root: Path | None, package_dir: Path | None, *, error_type: type[Exception] = RuntimeError) -> Path:
	if package_dir is not None:
		if not package_dir.exists():
			raise error_type(f"vLLM package dir not found: {package_dir}")
		return package_dir
	if runtime_root is None:
		raise error_type("either --runtime-root or --vllm-package-dir is required")
	matches = sorted(glob.glob(str(runtime_root / "lib" / "python*" / "site-packages" / "vllm")))
	if len(matches) != 1:
		raise error_type(f"expected one vLLM package dir under {runtime_root}, found {matches}")
	return Path(matches[0])
