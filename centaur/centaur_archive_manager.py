"""DAS-backed Centaur archive manager skeleton with local XOR simulation.

The first implementation deliberately targets local files.  It gives Centaur a
real API and testable parity semantics before touching the operator's DAS.
"""

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
    """Base error raised by the Centaur archive manager."""


class ArchiveIntegrityError(ArchiveError):
    """Raised when a blob cannot pass hash/parity integrity checks."""


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
            raise ValueError("data_drive_count must be at least 3 for XOR parity")
        if self.parity_drive_count != 0:
            raise ValueError("dedicated parity drives are not used in this layout")
        if self.staging_drive_count < 1:
            raise ValueError("staging_drive_count must be at least 1")
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

    @property
    def data_lanes_per_stripe(self) -> int:
        return self.data_drive_count - 1


@dataclass(frozen=True)
class KvBlobRecord:
    blob_id: str
    key: str
    related_group: str
    size_bytes: int
    sha256: str
    chunk_size: int
    stripe_count: int
    created_at_unix: int
    ttl_unix: int | None
    home_drive_index: int
    part_paths: list[str]


@dataclass(frozen=True)
class BundleRecord:
    bundle_id: str
    source_path: str
    archive_path: str
    size_bytes: int
    sha256: str
    created_at_unix: int


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in value.strip())
    return cleaned.strip(".-") or "default"


def _xor_chunks(chunks: Iterable[bytes], chunk_size: int) -> bytes:
    out = bytearray(chunk_size)
    for chunk in chunks:
        if len(chunk) != chunk_size:
            raise ArchiveIntegrityError("cannot XOR chunks with mixed sizes")
        for i, value in enumerate(chunk):
            out[i] ^= value
    return bytes(out)


def _tree_sha256(path: Path) -> tuple[int, str]:
    if path.is_file():
        data = path.read_bytes()
        return len(data), _sha256_bytes(data)
    total = 0
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        rel = item.relative_to(path).as_posix()
        data = item.read_bytes()
        total += len(data)
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
        digest.update(b"\0")
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
        self.root.mkdir(parents=True, exist_ok=True)
        for drive_index in range(self.layout.data_drive_count):
            (self.data_root / f"drive{drive_index}").mkdir(parents=True, exist_ok=True)
        for drive_index in range(self.layout.staging_drive_count):
            (self.staging_root / f"drive{drive_index}").mkdir(parents=True, exist_ok=True)
        self.bundle_root.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write_manifest(self._empty_manifest())

    def put_kv_blob(self, key: str, blob_bytes: bytes, related_group: str, ttl: int | None = None) -> str:
        self.initialize()
        if key.strip() == "":
            raise ValueError("key must be non-empty")
        if related_group.strip() == "":
            raise ValueError("related_group must be non-empty")
        created_at = int(time.time())
        blob_id = self._blob_id(key, blob_bytes, related_group, time.time_ns())
        manifest = self._load_manifest()
        if blob_id in manifest["kv_blobs"]:
            raise ArchiveError(f"blob already exists: {blob_id}")
        part_paths, stripe_count = self._write_striped_blob(blob_id, related_group, blob_bytes)
        ttl_unix = (created_at + int(ttl)) if ttl is not None else None
        record = KvBlobRecord(
            blob_id=blob_id,
            key=key,
            related_group=related_group,
            size_bytes=len(blob_bytes),
            sha256=_sha256_bytes(blob_bytes),
            chunk_size=self.layout.chunk_size,
            stripe_count=stripe_count,
            created_at_unix=created_at,
            ttl_unix=ttl_unix,
            home_drive_index=self._home_drive_index(related_group),
            part_paths=part_paths,
        )
        manifest["kv_blobs"][blob_id] = asdict(record)
        manifest["groups"].setdefault(related_group, [])
        manifest["groups"][related_group].append(blob_id)
        self._write_manifest(manifest)
        return blob_id

    def get_kv_blob(self, blob_id: str) -> bytes:
        manifest = self._load_manifest()
        record = self._record(manifest, blob_id)
        data = self._read_striped_blob(record)
        digest = _sha256_bytes(data)
        if digest != record.sha256:
            raise ArchiveIntegrityError(f"blob hash mismatch for {blob_id}: {digest} != {record.sha256}")
        return data

    def get_kv_blob_group(self, group_id: str) -> list[bytes]:
        manifest = self._load_manifest()
        blob_ids = sorted(
            manifest["groups"].get(group_id, []),
            key=lambda item: manifest["kv_blobs"][item]["created_at_unix"],
        )
        return [self.get_kv_blob(blob_id) for blob_id in blob_ids]

    def stage_for_vram(self, blob_ids: list[str]) -> Path:
        self.initialize()
        if len(blob_ids) == 0:
            raise ValueError("blob_ids must be non-empty")
        manifest = self._load_manifest()
        stage_id = _sha256_bytes(("\n".join(blob_ids) + f":{time.time_ns()}").encode("utf-8"))[:24]
        stage_dir = self.staging_root / "drive0" / "vram" / stage_id
        kv_dir = stage_dir / "kv_blobs"
        kv_dir.mkdir(parents=True, exist_ok=False)
        staged: list[dict[str, Any]] = []
        for blob_id in blob_ids:
            record = self._record(manifest, blob_id)
            data = self.get_kv_blob(blob_id)
            target = kv_dir / f"{blob_id}.kv"
            target.write_bytes(data)
            staged.append({
                "blob_id": blob_id,
                "key": record.key,
                "related_group": record.related_group,
                "path": target.relative_to(stage_dir).as_posix(),
                "size_bytes": len(data),
                "sha256": _sha256_bytes(data),
            })
        payload = {
            "format": STAGE_MANIFEST_FORMAT,
            "created_at_unix": int(time.time()),
            "staged": staged,
        }
        (stage_dir / "stage_manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return stage_dir

    def put_bundle(self, bundle_dir: Path | str) -> str:
        self.initialize()
        source = Path(bundle_dir)
        if not source.exists():
            raise FileNotFoundError(str(source))
        size_bytes, digest = _tree_sha256(source)
        created_at = int(time.time())
        bundle_id = _sha256_bytes(f"{source}:{digest}:{time.time_ns()}".encode("utf-8"))[:32]
        target = self.bundle_root / bundle_id
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        manifest = self._load_manifest()
        manifest["bundles"][bundle_id] = asdict(BundleRecord(
            bundle_id=bundle_id,
            source_path=str(source),
            archive_path=str(target.relative_to(self.root)),
            size_bytes=size_bytes,
            sha256=digest,
            created_at_unix=created_at,
        ))
        self._write_manifest(manifest)
        return bundle_id

    def get_bundle(self, bundle_id: str) -> Path:
        manifest = self._load_manifest()
        record = manifest["bundles"].get(bundle_id)
        if record is None:
            raise KeyError(f"unknown bundle_id: {bundle_id}")
        path = self.root / str(record["archive_path"])
        if not path.exists():
            raise FileNotFoundError(str(path))
        size_bytes, digest = _tree_sha256(path)
        if size_bytes != int(record["size_bytes"]) or digest != str(record["sha256"]):
            raise ArchiveIntegrityError(f"bundle integrity check failed: {bundle_id}")
        return path

    def gc(self, older_than: int) -> dict[str, Any]:
        manifest = self._load_manifest()
        expired: list[str] = []
        now = int(time.time())
        threshold = min(now, int(older_than))
        for blob_id, row in list(manifest["kv_blobs"].items()):
            ttl_unix = row.get("ttl_unix")
            created_at = int(row["created_at_unix"])
            if (ttl_unix is not None and int(ttl_unix) <= now) or created_at < threshold:
                expired.append(blob_id)
        return {"format": "centaur-archive-gc-plan-v1", "delete_candidates": sorted(expired), "dry_run": True}

    def parity_check(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        checked = 0
        missing: dict[str, list[int]] = {}
        bad: list[str] = []
        for blob_id, row in manifest["kv_blobs"].items():
            record = self._record_from_row(row)
            missing_drives = self._missing_drives(record)
            if missing_drives:
                missing[blob_id] = missing_drives
                continue
            try:
                self.get_kv_blob(blob_id)
                checked += 1
            except ArchiveIntegrityError:
                bad.append(blob_id)
        return {
            "format": "centaur-archive-parity-check-v1",
            "checked_blobs": checked,
            "missing_drive_files": missing,
            "bad_blobs": bad,
            "ok": len(missing) == 0 and len(bad) == 0,
        }

    def parity_rebuild(self, failed_drive_index: int) -> dict[str, Any]:
        self._validate_drive_index(failed_drive_index)
        manifest = self._load_manifest()
        rebuilt: list[str] = []
        skipped: list[str] = []
        for blob_id, row in manifest["kv_blobs"].items():
            record = self._record_from_row(row)
            missing = self._missing_drives(record)
            if missing == [failed_drive_index]:
                self._rebuild_drive_file(record, failed_drive_index)
                rebuilt.append(blob_id)
            elif failed_drive_index in missing:
                skipped.append(blob_id)
        return {
            "format": "centaur-archive-parity-rebuild-v1",
            "failed_drive_index": failed_drive_index,
            "rebuilt_blobs": sorted(rebuilt),
            "skipped_blobs": sorted(skipped),
            "ok": len(skipped) == 0,
        }

    def tier_metrics(self) -> dict[str, Any]:
        self.initialize()
        usage = []
        for drive_index in range(self.layout.data_drive_count):
            path = self.data_root / f"drive{drive_index}"
            usage.append({"drive_index": drive_index, "tier": "data", "bytes": self._path_bytes(path)})
        for drive_index in range(self.layout.staging_drive_count):
            path = self.staging_root / f"drive{drive_index}"
            usage.append({"drive_index": drive_index, "tier": "staging", "bytes": self._path_bytes(path)})
        return {
            "format": "centaur-archive-tier-metrics-v1",
            "layout": asdict(self.layout),
            "usage_per_drive": usage,
            "parity_age_seconds": None,
        }

    def drive_part_path(self, blob_id: str, drive_index: int) -> Path:
        manifest = self._load_manifest()
        record = self._record(manifest, blob_id)
        self._validate_drive_index(drive_index)
        return self.root / record.part_paths[drive_index]

    def _empty_manifest(self) -> dict[str, Any]:
        return {
            "format": MANIFEST_FORMAT,
            "layout": asdict(self.layout),
            "kv_blobs": {},
            "groups": {},
            "bundles": {},
        }

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            self.initialize()
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if payload.get("format") != MANIFEST_FORMAT:
            raise ArchiveError(f"unexpected manifest format: {payload.get('format')}")
        return payload

    def _write_manifest(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.manifest_path)

    def _blob_id(self, key: str, blob_bytes: bytes, related_group: str, nonce: int) -> str:
        digest = hashlib.sha256()
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(related_group.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(nonce).encode("ascii"))
        digest.update(b"\0")
        digest.update(blob_bytes)
        return digest.hexdigest()[:32]

    def _home_drive_index(self, related_group: str) -> int:
        raw = _sha256_bytes(related_group.encode("utf-8"))[:8]
        return int(raw, 16) % self.layout.data_drive_count

    def _write_striped_blob(self, blob_id: str, related_group: str, blob_bytes: bytes) -> tuple[list[str], int]:
        n = self.layout.data_drive_count
        chunk_size = self.layout.chunk_size
        data_lanes = self.layout.data_lanes_per_stripe
        stripe_payload = chunk_size * data_lanes
        stripe_count = max(1, (len(blob_bytes) + stripe_payload - 1) // stripe_payload)
        group = _safe_name(related_group)
        part_paths = [self.data_root / f"drive{i}" / "kv" / group / f"{blob_id}.part" for i in range(n)]
        handles = []
        try:
            for path in part_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                handles.append(path.open("wb"))
            for stripe_index in range(stripe_count):
                start = stripe_index * stripe_payload
                stripe = blob_bytes[start:start + stripe_payload]
                data_chunks = []
                for lane in range(data_lanes):
                    chunk = stripe[lane * chunk_size:(lane + 1) * chunk_size]
                    data_chunks.append(chunk.ljust(chunk_size, b"\0"))
                parity = _xor_chunks(data_chunks, chunk_size)
                parity_lane = stripe_index % n
                data_iter = iter(data_chunks)
                for drive_index in range(n):
                    chunk = parity if drive_index == parity_lane else next(data_iter)
                    handles[drive_index].write(chunk)
        finally:
            for handle in handles:
                handle.close()
        return [path.relative_to(self.root).as_posix() for path in part_paths], stripe_count

    def _read_striped_blob(self, record: KvBlobRecord) -> bytes:
        chunk_size = record.chunk_size
        chunks_by_drive: list[bytes | None] = [None] * self.layout.data_drive_count
        missing = self._missing_drives(record)
        if len(missing) > 1:
            raise ArchiveIntegrityError(f"too many missing drive files for {record.blob_id}: {missing}")
        with ThreadPoolExecutor(max_workers=self.layout.data_drive_count) as pool:
            futures = {
                drive_index: pool.submit((self.root / rel).read_bytes)
                for drive_index, rel in enumerate(record.part_paths)
                if drive_index not in missing
            }
            for drive_index, future in futures.items():
                chunks_by_drive[drive_index] = future.result()
        output = bytearray()
        for stripe_index in range(record.stripe_count):
            lane_chunks: list[bytes | None] = []
            for drive_index in range(self.layout.data_drive_count):
                raw = chunks_by_drive[drive_index]
                if raw is None:
                    lane_chunks.append(None)
                else:
                    start = stripe_index * chunk_size
                    lane_chunks.append(raw[start:start + chunk_size])
            if missing:
                rebuilt = _xor_chunks((chunk for chunk in lane_chunks if chunk is not None), chunk_size)
                lane_chunks[missing[0]] = rebuilt
            parity_lane = stripe_index % self.layout.data_drive_count
            for drive_index, chunk in enumerate(lane_chunks):
                if drive_index != parity_lane:
                    if chunk is None:
                        raise ArchiveIntegrityError(f"unrecoverable missing chunk for {record.blob_id}")
                    output.extend(chunk)
        return bytes(output[:record.size_bytes])

    def _rebuild_drive_file(self, record: KvBlobRecord, drive_index: int) -> None:
        missing_path = self.root / record.part_paths[drive_index]
        rebuilt = bytearray()
        for stripe_index in range(record.stripe_count):
            chunks = []
            for other_index, rel in enumerate(record.part_paths):
                if other_index == drive_index:
                    continue
                path = self.root / rel
                raw = path.read_bytes()
                start = stripe_index * record.chunk_size
                chunks.append(raw[start:start + record.chunk_size])
            rebuilt.extend(_xor_chunks(chunks, record.chunk_size))
        missing_path.parent.mkdir(parents=True, exist_ok=True)
        missing_path.write_bytes(bytes(rebuilt))
        self.get_kv_blob(record.blob_id)

    def _missing_drives(self, record: KvBlobRecord) -> list[int]:
        missing = []
        for drive_index, rel in enumerate(record.part_paths):
            path = self.root / rel
            expected = record.chunk_size * record.stripe_count
            if not path.exists() or path.stat().st_size != expected:
                missing.append(drive_index)
        return missing

    def _record(self, manifest: dict[str, Any], blob_id: str) -> KvBlobRecord:
        row = manifest["kv_blobs"].get(blob_id)
        if row is None:
            raise KeyError(f"unknown blob_id: {blob_id}")
        return self._record_from_row(row)

    def _record_from_row(self, row: dict[str, Any]) -> KvBlobRecord:
        return KvBlobRecord(
            blob_id=str(row["blob_id"]),
            key=str(row["key"]),
            related_group=str(row["related_group"]),
            size_bytes=int(row["size_bytes"]),
            sha256=str(row["sha256"]),
            chunk_size=int(row["chunk_size"]),
            stripe_count=int(row["stripe_count"]),
            created_at_unix=int(row["created_at_unix"]),
            ttl_unix=int(row["ttl_unix"]) if row.get("ttl_unix") is not None else None,
            home_drive_index=int(row["home_drive_index"]),
            part_paths=[str(item) for item in row["part_paths"]],
        )

    def _validate_drive_index(self, drive_index: int) -> None:
        if drive_index < 0 or drive_index >= self.layout.data_drive_count:
            raise ValueError(f"drive index out of range: {drive_index}")

    def _path_bytes(self, path: Path) -> int:
        if not path.exists():
            return 0
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
