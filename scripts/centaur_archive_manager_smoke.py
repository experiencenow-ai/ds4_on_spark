#!/usr/bin/env python3
"""Run a local Centaur archive-manager XOR parity smoke test."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from centaur.centaur_archive_manager import ArchiveLayout, CentaurArchiveManager


def run_smoke(root: Path) -> dict[str, object]:
    layout = ArchiveLayout(chunk_size=17)
    manager = CentaurArchiveManager(root, layout)
    payload = b"system-prompt-kv" + bytes(range(64)) + b"memory-pages"
    blob_id = manager.put_kv_blob("longmem/system/0001", payload, related_group="longmem.domain.alpha")
    round_trip = manager.get_kv_blob(blob_id)
    failed_drive_index = 2
    failed_path = manager.drive_part_path(blob_id, failed_drive_index)
    failed_size = failed_path.stat().st_size
    failed_path.unlink()
    before_rebuild = manager.parity_check()
    rebuild = manager.parity_rebuild(failed_drive_index)
    after_rebuild = manager.parity_check()
    staged_dir = manager.stage_for_vram([blob_id])
    staged_file = staged_dir / "kv_blobs" / f"{blob_id}.kv"
    metrics = manager.tier_metrics()
    return {
        "format": "centaur-archive-manager-smoke-v1",
        "root": str(root),
        "blob_id": blob_id,
        "data_drive_count": layout.data_drive_count,
        "staging_drive_count": layout.staging_drive_count,
        "failed_drive_index": failed_drive_index,
        "deleted_simulated_drive_file_bytes": failed_size,
        "round_trip_equal": round_trip == payload,
        "staged_equal": staged_file.read_bytes() == payload,
        "parity_missing_detected": blob_id in before_rebuild["missing_drive_files"],
        "parity_rebuild_ok": rebuild["ok"] is True and blob_id in rebuild["rebuilt_blobs"],
        "parity_check_ok_after_rebuild": after_rebuild["ok"] is True,
        "usage_per_drive": metrics["usage_per_drive"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local Centaur archive-manager smoke evidence.")
    parser.add_argument("--root", type=Path, default=None, help="Optional simulation root. Defaults to a temporary directory.")
    parser.add_argument("--keep", action="store_true", help="Keep the temporary simulation root.")
    args = parser.parse_args()
    if args.root is not None:
        args.root.mkdir(parents=True, exist_ok=True)
        result = run_smoke(args.root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="centaur-archive-smoke-"))
    try:
        result = run_smoke(tmp)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        if not args.keep:
            shutil.rmtree(tmp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
