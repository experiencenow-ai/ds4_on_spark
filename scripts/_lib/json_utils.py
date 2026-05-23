#!/usr/bin/env python3
"""Shared strict JSON helpers for DS4 scripts."""

from __future__ import annotations

import json
import copy
import hashlib
from pathlib import Path
from typing import Any


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any], drop: tuple[str, ...] = ("artifact_sha256", "artifact_hash")) -> str:
	tmp = copy.deepcopy(obj)
	for key in drop:
		tmp.pop(key, None)
	return sha256_obj(tmp)


def load_json(path: Path, root_label: str = "root") -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: {root_label} must be an object")
	return obj
