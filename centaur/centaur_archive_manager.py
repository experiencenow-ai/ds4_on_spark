"""Small local-file Centaur archive manager with XOR rebuild simulation."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


ARCHIVE_DATA_DRIVE_COUNT = 5
ARCHIVE_PARITY_DRIVE_COUNT = 0
ARCHIVE_STAGING_DRIVE_COUNT = 1
ARCHIVE_DATA_DRIVE_TIB = 16
ARCHIVE_STAGING_DRIVE_TIB = 22
ARCHIVE_STAGING_USABLE_TIB = 6
DEFAULT_CHUNK_SIZE = 1024 * 1024
MANIFEST_FORMAT = "centaur-archive-manager-v1"
STAGE_MANIFEST_FORMAT = "centaur-vram-stage-v1"


class ArchiveError(RuntimeError):
    pass


class ArchiveIntegrityError(ArchiveError):
    pass


@dataclass(frozen=True)
class ArchiveLayout:
    data_drive_count: int = ARCHIVE_DATA_DRIVE_COUNT
    parity_drive_count: int = ARCHIVE_PARITY_DRIVE_COUNT
    staging_drive_count: int = ARCHIVE_STAGING_DRIVE_COUNT
    data_drive_tib: int = ARCHIVE_DATA_DRIVE_TIB
    staging_drive_tib: int = ARCHIVE_STAGING_DRIVE_TIB
    staging_usable_tib: int = ARCHIVE_STAGING_USABLE_TIB
    chunk_size: int = DEFAULT_CHUNK_SIZE

    def validate(self) -> None:
        if self.data_drive_count < 3:
            raise ValueError("data_drive_count must be at least 3")
        if self.parity_drive_count != 0:
            raise ValueError("dedicated parity drives are not used")
        if self.staging_drive_count < 1 or self.chunk_size <= 0:
            raise ValueError("staging_drive_count and chunk_size must be positive")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _name(value: str) -> str:
    return ("".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value.strip()).strip(".-") or "default")


def _xor(chunks: Iterable[bytes], size: int) -> bytes:
    out = bytearray(size)
    for chunk in chunks:
        if len(chunk) != size:
            raise ArchiveIntegrityError("mixed XOR chunk sizes")
        for i, byte in enumerate(chunk):
            out[i] ^= byte
    return bytes(out)


def _tree(path: Path) -> tuple[int, str]:
    if path.is_file():
        data = path.read_bytes()
        return len(data), _sha(data)
    total, digest = 0, hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        data = item.read_bytes()
        total += len(data)
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0" + _sha(data).encode() + b"\0")
    return total, digest.hexdigest()


class CentaurArchiveManager:
    def __init__(self, root: Path | str, layout: ArchiveLayout | None = None) -> None:
        self.root = Path(root)
        self.layout = layout or ArchiveLayout()
        self.layout.validate()
        self.manifest_path = self.root / "archive_manifest.json"
        self.data_root = self.root / "data"
        self.staging_root = self.root / "staging"
        self.bundle_root = self.root / "bundles"

    def initialize(self) -> None:
        for i in range(self.layout.data_drive_count):
            (self.data_root / f"drive{i}").mkdir(parents=True, exist_ok=True)
        for i in range(self.layout.staging_drive_count):
            (self.staging_root / f"drive{i}").mkdir(parents=True, exist_ok=True)
        self.bundle_root.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._save({"format": MANIFEST_FORMAT, "layout": asdict(self.layout), "kv_blobs": {}, "groups": {}, "bundles": {}})

    def put_kv_blob(self, key: str, blob_bytes: bytes, related_group: str, ttl: int | None = None) -> str:
        self.initialize()
        if key.strip() == "" or related_group.strip() == "":
            raise ValueError("key and related_group must be non-empty")
        now = int(time.time())
        blob_id = _sha(key.encode() + b"\0" + related_group.encode() + b"\0" + str(time.time_ns()).encode() + b"\0" + blob_bytes)[:32]
        paths, stripes = self._write_parts(blob_id, related_group, blob_bytes)
        manifest = self._load()
        manifest["kv_blobs"][blob_id] = {
            "blob_id": blob_id,
            "key": key,
            "related_group": related_group,
            "size_bytes": len(blob_bytes),
            "sha256": _sha(blob_bytes),
            "chunk_size": self.layout.chunk_size,
            "stripe_count": stripes,
            "created_at_unix": now,
            "ttl_unix": now + int(ttl) if ttl is not None else None,
            "home_drive_index": int(_sha(related_group.encode())[:8], 16) % self.layout.data_drive_count,
            "part_paths": paths,
        }
        manifest["groups"].setdefault(related_group, []).append(blob_id)
        self._save(manifest)
        return blob_id

    def get_kv_blob(self, blob_id: str) -> bytes:
        row = self._blob(blob_id)
        data = self._read_parts(row)
        if _sha(data) != row["sha256"]:
            raise ArchiveIntegrityError(f"blob hash mismatch: {blob_id}")
        return data

    def get_kv_blob_group(self, group_id: str) -> list[bytes]:
        manifest = self._load()
        ids = sorted(manifest["groups"].get(group_id, []), key=lambda bid: manifest["kv_blobs"][bid]["created_at_unix"])
        return [self.get_kv_blob(bid) for bid in ids]

    def stage_for_vram(self, blob_ids: list[str]) -> Path:
        if len(blob_ids) == 0:
            raise ValueError("blob_ids must be non-empty")
        self.initialize()
        stage = self.staging_root / "drive0" / "vram" / _sha(("\n".join(blob_ids) + str(time.time_ns())).encode())[:24]
        (stage / "kv_blobs").mkdir(parents=True)
        staged = []
        for bid in blob_ids:
            row, data = self._blob(bid), self.get_kv_blob(bid)
            path = stage / "kv_blobs" / f"{bid}.kv"
            path.write_bytes(data)
            staged.append({"blob_id": bid, "key": row["key"], "related_group": row["related_group"], "path": path.relative_to(stage).as_posix(), "size_bytes": len(data), "sha256": _sha(data)})
        (stage / "stage_manifest.json").write_text(json.dumps({"format": STAGE_MANIFEST_FORMAT, "created_at_unix": int(time.time()), "staged": staged}, indent=2, sort_keys=True) + "\n")
        return stage

    def put_bundle(self, bundle_dir: Path | str) -> str:
        self.initialize()
        source = Path(bundle_dir)
        if not source.exists():
            raise FileNotFoundError(str(source))
        size, digest = _tree(source)
        bundle_id = _sha(f"{source}:{digest}:{time.time_ns()}".encode())[:32]
        target = self.bundle_root / bundle_id
        shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
        manifest = self._load()
        manifest["bundles"][bundle_id] = {"bundle_id": bundle_id, "source_path": str(source), "archive_path": str(target.relative_to(self.root)), "size_bytes": size, "sha256": digest, "created_at_unix": int(time.time())}
        self._save(manifest)
        return bundle_id

    def get_bundle(self, bundle_id: str) -> Path:
        row = self._load()["bundles"].get(bundle_id)
        if row is None:
            raise KeyError(f"unknown bundle_id: {bundle_id}")
        path = self.root / row["archive_path"]
        size, digest = _tree(path)
        if size != row["size_bytes"] or digest != row["sha256"]:
            raise ArchiveIntegrityError(f"bundle integrity check failed: {bundle_id}")
        return path

    def gc(self, older_than: int) -> dict[str, Any]:
        now, cutoff, out = int(time.time()), int(older_than), []
        for bid, row in self._load()["kv_blobs"].items():
            if (row.get("ttl_unix") is not None and row["ttl_unix"] <= now) or row["created_at_unix"] < cutoff:
                out.append(bid)
        return {"format": "centaur-archive-gc-plan-v1", "delete_candidates": sorted(out), "dry_run": True}

    def parity_check(self) -> dict[str, Any]:
        missing, bad, checked = {}, [], 0
        for bid, row in self._load()["kv_blobs"].items():
            miss = self._missing(row)
            if miss:
                missing[bid] = miss
            else:
                try:
                    self.get_kv_blob(bid)
                    checked += 1
                except ArchiveIntegrityError:
                    bad.append(bid)
        return {"format": "centaur-archive-parity-check-v1", "checked_blobs": checked, "missing_drive_files": missing, "bad_blobs": bad, "ok": not missing and not bad}

    def parity_rebuild(self, failed_drive_index: int) -> dict[str, Any]:
        self._check_drive(failed_drive_index)
        rebuilt, skipped = [], []
        for bid, row in self._load()["kv_blobs"].items():
            miss = self._missing(row)
            if miss == [failed_drive_index]:
                self._rebuild(row, failed_drive_index)
                rebuilt.append(bid)
            elif failed_drive_index in miss:
                skipped.append(bid)
        return {"format": "centaur-archive-parity-rebuild-v1", "failed_drive_index": failed_drive_index, "rebuilt_blobs": sorted(rebuilt), "skipped_blobs": sorted(skipped), "ok": len(skipped) == 0}

    def tier_metrics(self) -> dict[str, Any]:
        self.initialize()
        usage = [{"drive_index": i, "tier": "data", "bytes": self._bytes(self.data_root / f"drive{i}")} for i in range(self.layout.data_drive_count)]
        usage += [{"drive_index": i, "tier": "staging", "bytes": self._bytes(self.staging_root / f"drive{i}")} for i in range(self.layout.staging_drive_count)]
        return {"format": "centaur-archive-tier-metrics-v1", "layout": asdict(self.layout), "usage_per_drive": usage, "parity_age_seconds": None}

    def drive_part_path(self, blob_id: str, drive_index: int) -> Path:
        self._check_drive(drive_index)
        return self.root / self._blob(blob_id)["part_paths"][drive_index]

    def _load(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            self.initialize()
        manifest = json.loads(self.manifest_path.read_text())
        if manifest.get("format") != MANIFEST_FORMAT:
            raise ArchiveError("unexpected manifest format")
        return manifest

    def _save(self, manifest: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def _blob(self, blob_id: str) -> dict[str, Any]:
        row = self._load()["kv_blobs"].get(blob_id)
        if row is None:
            raise KeyError(f"unknown blob_id: {blob_id}")
        return row

    def _part_paths(self, blob_id: str, group: str) -> list[Path]:
        return [self.data_root / f"drive{i}" / "kv" / _name(group) / f"{blob_id}.part" for i in range(self.layout.data_drive_count)]

    def _write_parts(self, blob_id: str, group: str, data: bytes) -> tuple[list[str], int]:
        n, cs = self.layout.data_drive_count, self.layout.chunk_size
        stripe_bytes, stripes = cs * (n - 1), max(1, (len(data) + (cs * (n - 1)) - 1) // (cs * (n - 1)))
        parts = [bytearray() for _ in range(n)]
        for s in range(stripes):
            stripe = data[s * stripe_bytes:(s + 1) * stripe_bytes]
            chunks = [stripe[i * cs:(i + 1) * cs].ljust(cs, b"\0") for i in range(n - 1)]
            parity, data_iter = _xor(chunks, cs), iter(chunks)
            for i in range(n):
                parts[i].extend(parity if i == s % n else next(data_iter))
        paths = self._part_paths(blob_id, group)
        for path, body in zip(paths, parts):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return [str(path.relative_to(self.root)) for path in paths], stripes

    def _read_parts(self, row: dict[str, Any]) -> bytes:
        n, cs, missing = self.layout.data_drive_count, row["chunk_size"], self._missing(row)
        if len(missing) > 1:
            raise ArchiveIntegrityError(f"too many missing drive files: {missing}")
        raw: list[bytes | None] = [None] * n
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = {i: pool.submit((self.root / path).read_bytes) for i, path in enumerate(row["part_paths"]) if i not in missing}
            for i, future in futures.items():
                raw[i] = future.result()
        out = bytearray()
        for s in range(row["stripe_count"]):
            chunks = [None if raw[i] is None else raw[i][s * cs:(s + 1) * cs] for i in range(n)]
            if missing:
                chunks[missing[0]] = _xor((c for c in chunks if c is not None), cs)
            for i, chunk in enumerate(chunks):
                if i != s % n:
                    out.extend(chunk or b"")
        return bytes(out[:row["size_bytes"]])

    def _rebuild(self, row: dict[str, Any], drive_index: int) -> None:
        n, cs, rebuilt = self.layout.data_drive_count, row["chunk_size"], bytearray()
        for s in range(row["stripe_count"]):
            chunks = []
            for i in range(n):
                if i != drive_index:
                    raw = (self.root / row["part_paths"][i]).read_bytes()
                    chunks.append(raw[s * cs:(s + 1) * cs])
            rebuilt.extend(_xor(chunks, cs))
        path = self.root / row["part_paths"][drive_index]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rebuilt)
        self.get_kv_blob(row["blob_id"])

    def _missing(self, row: dict[str, Any]) -> list[int]:
        expected = row["chunk_size"] * row["stripe_count"]
        return [i for i, rel in enumerate(row["part_paths"]) if not (self.root / rel).exists() or (self.root / rel).stat().st_size != expected]

    def _check_drive(self, drive_index: int) -> None:
        if drive_index < 0 or drive_index >= self.layout.data_drive_count:
            raise ValueError(f"drive index out of range: {drive_index}")

    def _bytes(self, path: Path) -> int:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0
