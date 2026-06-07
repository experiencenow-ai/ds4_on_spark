#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


DEFAULT_PREFETCH_TOKEN_FILES = (Path("/private/tmp/ds4_jit_kv_token"), Path("/tmp/ds4_jit_kv_token"))
DEFAULT_PREFETCH_TOKEN_FILE = DEFAULT_PREFETCH_TOKEN_FILES[0]


def prefetch_token_candidates(raw_path: str) -> list[Path]:
    paths = [Path(raw_path).expanduser()] if raw_path else []
    for path in DEFAULT_PREFETCH_TOKEN_FILES:
        if path not in paths:
            paths.append(path)
    return paths


def load_prefetch_token(raw_path: str) -> str:
    for path in prefetch_token_candidates(raw_path):
        if path.exists():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    return ""
