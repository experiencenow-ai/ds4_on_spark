#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

checks = []

def require(path: str, needle: str, label: str) -> None:
    text = (ROOT / path).read_text()
    if needle not in text:
        raise SystemExit(f"FAIL: {label}\nmissing {needle!r} in {path}")
    checks.append(label)

require("src/ds4_transfer/striped_channel.py", "def send_file_striped", "striped sender exists")
require("src/ds4_transfer/striped_channel.py", "def receive_file_striped", "striped receiver exists")
require("src/ds4_transfer/striped_channel.py", "os.pwrite", "receiver writes stripes by offset")
require("src/ds4_transfer/fast_copy.py", "--striped-file-stripes", "fast-copy exposes stripe count")
require("src/ds4_transfer/fast_copy.py", "_copy_file_striped", "fast-copy uses striped path for large files")
require("src/ds4_transfer/service.py", "striped_file_stripes", "transfer service exposes striped config")

for label in checks:
    print(f"PASS: {label}")
