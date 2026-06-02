from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any

ARCHIVE_CATALOG_FORMAT = "ds4-xor-archive-catalog-v1"
ARCHIVE_MANIFEST_FORMAT = "ds4-xor-archive-object-v1"
ARCHIVE_VOLUME_FORMAT = "ds4-xor-archive-volume-v1"
DEFAULT_SHARD_BYTES = 64 * 1024 * 1024
DEFAULT_EXTENT_PAYLOAD_BYTES = 0


@dataclass(frozen=True)
class ArchiveVolume:
    volume_id: str
    root: Path

    @staticmethod
    def parse(value: str) -> "ArchiveVolume":
        if "=" not in value:
            raise ValueError("volume must be formatted as id=/absolute/path")
        volume_id, root = value.split("=", 1)
        return ArchiveVolume(_safe_name(volume_id), Path(root))


class XorArchiveStore:
    def __init__(
        self,
        metadata_root: str | Path,
        volumes: list[ArchiveVolume] | tuple[ArchiveVolume, ...],
        *,
        extent_payload_bytes: int = DEFAULT_EXTENT_PAYLOAD_BYTES,
        fsync: bool = True,
        io_workers: int = 6,
        native_helper: str | Path | None = "auto",
    ) -> None:
        self.metadata_root = Path(metadata_root)
        self.volumes = tuple(volumes)
        self.fsync = bool(fsync)
        self.io_workers = max(1, int(io_workers))
        self.native_helper = _resolve_native_helper(native_helper)
        if len(self.volumes) not in {4, 6}:
            raise ValueError("XOR archive requires exactly four or six volumes")
        self.shard_count = len(self.volumes)
        self.data_shards = self.shard_count - 1
        self.extent_payload_bytes = int(extent_payload_bytes) if int(extent_payload_bytes) > 0 else self.data_shards * DEFAULT_SHARD_BYTES
        if len({volume.volume_id for volume in self.volumes}) != len(self.volumes):
            raise ValueError("archive volume ids must be unique")
        self.volume_by_id = {volume.volume_id: volume for volume in self.volumes}
        self.catalog_path = self.metadata_root / "catalog.json"

    def storage_class_name(self) -> str:
        return f"archive_{self.data_shards}p1_xor"

    def storage_class(self) -> dict[str, Any]:
        return {
            "name": self.storage_class_name(),
            "data_shards": self.data_shards,
            "parity_shards": 1,
            "layout": "same_offset_rotating_parity",
        }

    def init(self) -> dict[str, Any]:
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        for index, volume in enumerate(self.volumes):
            (self._archive_root(volume) / "data").mkdir(parents=True, exist_ok=True)
            (self._archive_root(volume) / "manifests").mkdir(parents=True, exist_ok=True)
            _atomic_write_json(
                self._archive_root(volume) / "volume.json",
                {
                    "format": ARCHIVE_VOLUME_FORMAT,
                    "volume_id": volume.volume_id,
                    "root": str(volume.root),
                    "ordinal": index,
                    "created_unix_s": time.time(),
                },
            )
        catalog = {
            "format": ARCHIVE_CATALOG_FORMAT,
            "storage_class": self.storage_class(),
            "extent_payload_bytes": self.extent_payload_bytes,
            "next_offset": 0,
            "extent_count": 0,
            "volumes": [volume.volume_id for volume in self.volumes],
            "objects": {},
            "created_unix_s": time.time(),
        }
        _atomic_write_json(self.catalog_path, catalog)
        return catalog

    def put_bytes(self, namespace: str, key: str, data: bytes, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile() as handle:
            handle.write(data)
            handle.flush()
            return self.put_path(namespace, key, handle.name, metadata=metadata)

    def put_path(self, namespace: str, key: str, path: str | Path, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        catalog = self._read_catalog()
        object_key = _object_key(namespace, key)
        if object_key in catalog["objects"]:
            raise ValueError(f"archive object already exists: {object_key}")
        object_id = f"obj_{hashlib.sha256(object_key.encode('utf-8')).hexdigest()[:24]}"
        if self.native_helper is not None:
            return self._put_path_native(catalog, object_id, namespace, key, path, metadata=metadata)
        extents: list[dict[str, Any]] = []
        total_bytes = 0
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            while True:
                chunk = handle.read(self.extent_payload_bytes)
                if not chunk:
                    break
                digest.update(chunk)
                extent = self._append_extent(catalog, object_id, len(extents), chunk)
                extents.append(extent)
                total_bytes += len(chunk)
        if self.fsync:
            self._fsync_data_files()
        manifest = {
            "format": ARCHIVE_MANIFEST_FORMAT,
            "object_id": object_id,
            "namespace": namespace,
            "key": key,
            "storage_class": self.storage_class_name(),
            "bytes": total_bytes,
            "sha256": digest.hexdigest(),
            "created_unix_s": time.time(),
            "metadata": metadata or {},
            "extents": extents,
        }
        self._write_manifest_replicas(manifest)
        catalog["objects"][object_key] = manifest
        catalog["updated_unix_s"] = time.time()
        _atomic_write_json(self.catalog_path, catalog)
        return manifest

    def _put_path_native(
        self,
        catalog: dict[str, Any],
        object_id: str,
        namespace: str,
        key: str,
        path: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        for volume in self.volumes:
            (self._archive_root(volume) / "data").mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.metadata_root, suffix=".native-plan", delete=False) as handle:
            plan_path = Path(handle.name)
        try:
            self._run_native_put(path, plan_path, int(catalog["next_offset"]), int(catalog["extent_count"]))
            extents, total_bytes, object_hash64 = self._parse_native_plan(plan_path)
        finally:
            plan_path.unlink(missing_ok=True)
        if self.fsync:
            self._fsync_data_files()
        manifest = {
            "format": ARCHIVE_MANIFEST_FORMAT,
            "object_id": object_id,
            "namespace": namespace,
            "key": key,
            "storage_class": self.storage_class_name(),
            "bytes": total_bytes,
            "checksum": {"algorithm": "none", "value": object_hash64},
            "created_unix_s": time.time(),
            "metadata": metadata or {},
            "extents": extents,
            "native_data_plane": str(self.native_helper),
        }
        if extents:
            catalog["next_offset"] = max(int(extent["offset"]) + int(extent["shard_len"]) for extent in extents)
            catalog["extent_count"] = max(int(extent["extent_index"]) + 1 for extent in extents)
        catalog["objects"][_object_key(namespace, key)] = manifest
        catalog["updated_unix_s"] = time.time()
        self._write_manifest_replicas(manifest)
        _atomic_write_json(self.catalog_path, catalog)
        return manifest

    def _run_native_put(self, input_path: str | Path, plan_path: Path, start_offset: int, start_extent: int) -> None:
        assert self.native_helper is not None
        cmd = [
            str(self.native_helper),
            "put",
            str(input_path),
            str(plan_path),
            str(start_offset),
            str(start_extent),
            str(self.extent_payload_bytes),
            *[str(self._data_path(volume.volume_id)) for volume in self.volumes],
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "native archive helper failed").strip()
            raise RuntimeError(detail)

    def _parse_native_plan(self, plan_path: Path) -> tuple[list[dict[str, Any]], int, str]:
        extents: list[dict[str, Any]] = []
        total_bytes = 0
        object_hash64 = ""
        with plan_path.open("r", encoding="utf-8") as handle:
            header = handle.readline().strip()
            header_parts = header.split("\t")
            if header == "ds4-xor-plan-v1":
                plan_shard_count = 6
            elif len(header_parts) == 3 and header_parts[0] == "ds4-xor-plan-v2":
                plan_shard_count = int(header_parts[1])
            else:
                raise ValueError(f"unsupported native archive plan: {header!r}")
            if plan_shard_count != self.shard_count:
                raise ValueError(f"native plan shard count {plan_shard_count} does not match archive volume count {self.shard_count}")
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if not parts:
                    continue
                if parts[0] == "O":
                    total_bytes = int(parts[1])
                    object_hash64 = parts[2]
                elif parts[0] == "E":
                    extents.append(self._parse_native_extent(parts))
        if total_bytes != sum(int(extent["logical_len"]) for extent in extents):
            raise ValueError("native archive plan byte total mismatch")
        return extents, total_bytes, object_hash64

    def _parse_native_extent(self, parts: list[str]) -> dict[str, Any]:
        if len(parts) != 7 + self.shard_count:
            raise ValueError(f"malformed native extent plan line: {parts!r}")
        extent_index = int(parts[1])
        object_extent_index = int(parts[2])
        offset = int(parts[3])
        shard_len = int(parts[4])
        logical_len = int(parts[5])
        parity_slot = int(parts[6])
        shard_hashes = parts[7 : 7 + self.shard_count]
        data_slots = [slot for slot in range(self.shard_count) if slot != parity_slot]
        shards: list[dict[str, str]] = []
        for slot, volume in enumerate(self.volumes):
            role = "parity0" if slot == parity_slot else f"data{data_slots.index(slot)}"
            shards.append({"volume_id": volume.volume_id, "role": role, "xxh64": shard_hashes[slot]})
        return {
            "extent_index": extent_index,
            "object_extent_index": object_extent_index,
            "offset": offset,
            "shard_len": shard_len,
            "logical_len": logical_len,
            "parity_volume_id": self.volumes[parity_slot].volume_id,
            "shards": shards,
        }

    def get_bytes(self, namespace: str, key: str) -> bytes:
        return b"".join(self.iter_bytes(namespace, key))

    def iter_bytes(self, namespace: str, key: str) -> Iterator[bytes]:
        manifest = self.manifest(namespace, key)
        yield from self._iter_manifest_bytes(manifest)

    def stage(self, namespace: str, key: str, destination: str | Path) -> Path:
        manifest = self.manifest(namespace, key)
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if self.native_helper is not None and _manifest_uses_native_hash(manifest):
            return self._stage_native(manifest, destination_path)
        with tempfile.NamedTemporaryFile(dir=destination_path.parent, delete=False) as handle:
            tmp = Path(handle.name)
            for chunk in self._iter_manifest_bytes(manifest):
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(destination_path)
        return destination_path

    def _stage_native(self, manifest: dict[str, Any], destination_path: Path) -> Path:
        assert self.native_helper is not None
        output_fd, output_name = tempfile.mkstemp(dir=destination_path.parent)
        os.close(output_fd)
        tmp_output = Path(output_name)
        with tempfile.NamedTemporaryFile(dir=self.metadata_root, suffix=".native-plan", delete=False) as plan_handle:
            plan_path = Path(plan_handle.name)
        try:
            self._write_native_plan(manifest, plan_path)
            cmd = [
                str(self.native_helper),
                "get",
                str(tmp_output),
                str(plan_path),
                *[str(self._data_path(volume.volume_id)) for volume in self.volumes],
            ]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "native archive restore failed").strip()
                raise RuntimeError(detail)
            tmp_output.replace(destination_path)
            return destination_path
        finally:
            plan_path.unlink(missing_ok=True)
            if tmp_output.exists() and tmp_output != destination_path:
                tmp_output.unlink(missing_ok=True)

    def _write_native_plan(self, manifest: dict[str, Any], plan_path: Path) -> None:
        with plan_path.open("w", encoding="utf-8") as handle:
            handle.write(f"ds4-xor-plan-v2\t{self.shard_count}\t{self.data_shards}\n")
            for extent in manifest["extents"]:
                parity_slot = [index for index, shard in enumerate(extent["shards"]) if shard["role"] == "parity0"][0]
                shard_hashes = [str(shard.get("xxh64", shard.get("crc64"))) for shard in extent["shards"]]
                handle.write(
                    "E\t{extent}\t{object_extent}\t{offset}\t{shard_len}\t{logical_len}\t{parity}\t{crc}\n".format(
                        extent=extent["extent_index"],
                        object_extent=extent["object_extent_index"],
                        offset=extent["offset"],
                        shard_len=extent["shard_len"],
                        logical_len=extent["logical_len"],
                        parity=parity_slot,
                        crc="\t".join(shard_hashes),
                    )
                )
            checksum = manifest.get("checksum", {})
            handle.write(f"O\t{manifest['bytes']}\t{checksum.get('value', '0000000000000000')}\n")

    def _iter_manifest_bytes(self, manifest: dict[str, Any]) -> Iterator[bytes]:
        remaining = int(manifest["bytes"])
        for extent in manifest["extents"]:
            data = self._read_extent(extent)
            take = min(remaining, len(data))
            yield data[:take]
            remaining -= take

    def verify(self, namespace: str, key: str) -> dict[str, Any]:
        manifest = self.manifest(namespace, key)
        extent_results = [self._verify_extent(extent) for extent in manifest["extents"]]
        bad = [item for item in extent_results if item["state"] != "healthy"]
        unrecoverable = [item for item in extent_results if item["state"] == "unrecoverable"]
        return {
            "format": "ds4-xor-archive-verify-v1",
            "object_id": manifest["object_id"],
            "namespace": namespace,
            "key": key,
            "state": "unrecoverable" if unrecoverable else ("degraded" if bad else "healthy"),
            "healthy": not bad,
            "extent_count": len(extent_results),
            "bad_extent_count": len(bad),
            "extents": extent_results,
        }

    def repair(self, namespace: str, key: str) -> dict[str, Any]:
        manifest = self.manifest(namespace, key)
        repaired: list[dict[str, Any]] = []
        for extent in manifest["extents"]:
            result = self._verify_extent(extent)
            if result["state"] == "healthy":
                continue
            if result["state"] == "unrecoverable":
                raise ValueError(f"extent {extent['extent_index']} has more than one bad shard")
            bad_index = int(result["bad_shards"][0])
            shards = self._read_shards(extent, allow_bad=True)
            repaired_shard = _xor_many([data for index, data in enumerate(shards) if index != bad_index and data is not None])
            shard_info = extent["shards"][bad_index]
            self._write_shard(str(shard_info["volume_id"]), int(extent["offset"]), repaired_shard)
            repaired.append({"extent_index": extent["extent_index"], "shard_index": bad_index, "volume_id": shard_info["volume_id"]})
        return {"format": "ds4-xor-archive-repair-v1", "object_id": manifest["object_id"], "repaired": repaired, "verify": self.verify(namespace, key)}

    def manifest(self, namespace: str, key: str) -> dict[str, Any]:
        catalog = self._read_catalog()
        object_key = _object_key(namespace, key)
        try:
            return catalog["objects"][object_key]
        except KeyError as exc:
            raise ValueError(f"archive object not found: {object_key}") from exc

    def list_objects(self) -> list[dict[str, Any]]:
        catalog = self._read_catalog()
        return [dict(value) for value in catalog["objects"].values()]

    def status(self) -> dict[str, Any]:
        catalog = self._read_catalog()
        return {
            "format": "ds4-xor-archive-status-v1",
            "storage_class": catalog["storage_class"],
            "volume_count": len(self.volumes),
            "volumes": [{"volume_id": volume.volume_id, "root": str(volume.root), "online": self._archive_root(volume).exists()} for volume in self.volumes],
            "object_count": len(catalog["objects"]),
            "next_offset": catalog["next_offset"],
        }

    def rebuild_catalog(self) -> dict[str, Any]:
        manifests: dict[str, dict[str, Any]] = {}
        next_offset = 0
        extent_count = 0
        for volume in self.volumes:
            manifest_dir = self._archive_root(volume) / "manifests"
            if not manifest_dir.exists():
                continue
            for path in manifest_dir.glob("*.json"):
                with path.open("r", encoding="utf-8") as handle:
                    manifest = json.load(handle)
                if manifest.get("format") != ARCHIVE_MANIFEST_FORMAT:
                    continue
                manifests[_object_key(str(manifest["namespace"]), str(manifest["key"]))] = manifest
                for extent in manifest.get("extents", []):
                    next_offset = max(next_offset, int(extent["offset"]) + int(extent["shard_len"]))
                    extent_count = max(extent_count, int(extent["extent_index"]) + 1)
        catalog = {
            "format": ARCHIVE_CATALOG_FORMAT,
            "storage_class": self.storage_class(),
            "extent_payload_bytes": self.extent_payload_bytes,
            "next_offset": next_offset,
            "extent_count": extent_count,
            "volumes": [volume.volume_id for volume in self.volumes],
            "objects": manifests,
            "rebuilt_unix_s": time.time(),
        }
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.catalog_path, catalog)
        return catalog

    def _append_extent(self, catalog: dict[str, Any], object_id: str, object_extent_index: int, data: bytes) -> dict[str, Any]:
        extent_index = int(catalog["extent_count"])
        offset = int(catalog["next_offset"])
        shard_len = int(math.ceil(len(data) / float(self.data_shards)))
        padded_len = shard_len * self.data_shards
        padded = data if len(data) == padded_len else data + b"\0" * (padded_len - len(data))
        padded_view = memoryview(padded)
        data_shards = [padded_view[index * shard_len : (index + 1) * shard_len] for index in range(self.data_shards)]
        parity_shard = _xor_many(data_shards)
        parity_slot = extent_index % self.shard_count
        data_slots = [slot for slot in range(self.shard_count) if slot != parity_slot]
        slot_payloads: dict[int, tuple[str, bytes]] = {parity_slot: ("parity0", parity_shard)}
        for data_index, slot in enumerate(data_slots):
            slot_payloads[slot] = (f"data{data_index}", data_shards[data_index])
        writes: list[tuple[str, Any]] = []
        roles: list[tuple[str, str]] = []
        for slot in range(self.shard_count):
            role, payload = slot_payloads[slot]
            volume_id = self.volumes[slot].volume_id
            writes.append((volume_id, payload))
            roles.append((volume_id, role))
        checksums = self._write_extent_shards(offset, writes)
        shards = [{"volume_id": volume_id, "role": role, "sha256": checksums[index]} for index, (volume_id, role) in enumerate(roles)]
        catalog["next_offset"] = offset + shard_len
        catalog["extent_count"] = extent_index + 1
        return {
            "extent_index": extent_index,
            "object_extent_index": object_extent_index,
            "offset": offset,
            "shard_len": shard_len,
            "logical_len": len(data),
            "parity_volume_id": self.volumes[parity_slot].volume_id,
            "shards": shards,
        }

    def _read_extent(self, extent: dict[str, Any]) -> bytes:
        data_indexes = _data_shard_indexes(extent)
        data_shards = self._read_shard_indexes(extent, data_indexes, allow_bad=True)
        if all(data is not None for data in data_shards):
            return b"".join(data for data in data_shards if data is not None)[: int(extent["logical_len"])]
        shards = self._read_shards(extent, allow_bad=True)
        bad = [index for index, data in enumerate(shards) if data is None]
        if len(bad) > 1:
            raise ValueError(f"extent {extent['extent_index']} has more than one bad shard")
        if bad:
            shards[bad[0]] = _xor_many([data for data in shards if data is not None])
        data_by_role = {str(shard["role"]): shards[index] for index, shard in enumerate(extent["shards"]) if str(shard["role"]).startswith("data")}
        return b"".join(data_by_role[f"data{index}"] for index in range(self.data_shards))[: int(extent["logical_len"])]

    def _verify_extent(self, extent: dict[str, Any]) -> dict[str, Any]:
        shards = self._read_shards(extent, allow_bad=True)
        bad = [index for index, data in enumerate(shards) if data is None]
        return {
            "extent_index": extent["extent_index"],
            "state": "healthy" if not bad else ("degraded" if len(bad) == 1 else "unrecoverable"),
            "bad_shards": bad,
            "offset": extent["offset"],
            "shard_len": extent["shard_len"],
            "parity_volume_id": extent["parity_volume_id"],
        }

    def _read_shards(self, extent: dict[str, Any], *, allow_bad: bool = False) -> list[bytes | None]:
        return self._read_shard_indexes(extent, list(range(len(extent["shards"]))), allow_bad=allow_bad)

    def _read_shard_indexes(self, extent: dict[str, Any], indexes: list[int], *, allow_bad: bool = False) -> list[bytes | None]:
        def read_one(index: int) -> bytes | None:
            shard = extent["shards"][index]
            try:
                data = self._read_shard(str(shard["volume_id"]), int(extent["offset"]), int(extent["shard_len"]))
                if not _shard_checksum_matches(data, shard):
                    raise ValueError("checksum mismatch")
                return data
            except Exception:
                if not allow_bad:
                    raise
                return None

        if self.io_workers == 1:
            return [read_one(index) for index in indexes]
        with ThreadPoolExecutor(max_workers=min(self.io_workers, len(indexes))) as pool:
            return list(pool.map(read_one, indexes))

    def _write_extent_shards(self, offset: int, writes: list[tuple[str, Any]]) -> list[str]:
        def write_one(item: tuple[str, Any]) -> str:
            volume_id, payload = item
            checksum = _sha256_bytes(payload)
            self._write_shard(volume_id, offset, payload)
            return checksum

        if self.io_workers == 1:
            checksums: list[str] = []
            for item in writes:
                checksums.append(write_one(item))
            return checksums
        with ThreadPoolExecutor(max_workers=min(self.io_workers, len(writes))) as pool:
            return list(pool.map(write_one, writes))

    def _write_manifest_replicas(self, manifest: dict[str, Any]) -> None:
        for volume in self.volumes:
            _atomic_write_json(self._archive_root(volume) / "manifests" / f"{manifest['object_id']}.json", manifest)

    def _write_shard(self, volume_id: str, offset: int, data: Any) -> None:
        path = self._data_path(volume_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "r+b" if path.exists() else "w+b"
        with path.open(mode) as handle:
            handle.seek(offset)
            handle.write(data)
            handle.flush()

    def _fsync_data_files(self) -> None:
        for volume in self.volumes:
            path = self._data_path(volume.volume_id)
            if not path.exists():
                continue
            with path.open("r+b") as handle:
                os.fsync(handle.fileno())

    def _read_shard(self, volume_id: str, offset: int, length: int) -> bytes:
        with self._data_path(volume_id).open("rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
        if len(data) != length:
            raise ValueError(f"short shard read from {volume_id}: wanted {length}, got {len(data)}")
        return data

    def _data_path(self, volume_id: str) -> Path:
        volume = self.volume_by_id[volume_id]
        return self._archive_root(volume) / "data" / f"{self.storage_class_name()}.bin"

    def _archive_root(self, volume: ArchiveVolume) -> Path:
        return volume.root / ".ds4_archive"

    def _read_catalog(self) -> dict[str, Any]:
        with self.catalog_path.open("r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        if catalog.get("format") != ARCHIVE_CATALOG_FORMAT:
            raise ValueError(f"unsupported archive catalog format: {catalog.get('format')!r}")
        catalog_volumes = [str(volume_id) for volume_id in catalog.get("volumes", [])]
        if set(catalog_volumes) != set(self.volume_by_id):
            raise ValueError("archive volume set differs from catalog; refusing to decode parity layout")
        if catalog_volumes != [volume.volume_id for volume in self.volumes]:
            self.volumes = tuple(self.volume_by_id[volume_id] for volume_id in catalog_volumes)
        return catalog


def _resolve_native_helper(native_helper: str | Path | None) -> Path | None:
    if native_helper is None:
        return None
    value = str(native_helper)
    if value == "auto":
        env_value = os.environ.get("DS4_ARCHIVE_XOR")
        if env_value:
            return Path(env_value)
        found = shutil.which("ds4_archive_xor")
        return Path(found) if found else None
    return Path(value)


def _shard_checksum_matches(data: Any, shard: dict[str, Any]) -> bool:
    if "sha256" in shard:
        return _sha256_bytes(data) == shard["sha256"]
    if "xxh64" in shard:
        return _xxh64_hex(data) == str(shard["xxh64"]).lower()
    if "crc64" in shard:
        return _crc64_hex(data) == str(shard["crc64"]).lower()
    raise ValueError("archive shard has no supported checksum")


def _manifest_uses_native_hash(manifest: dict[str, Any]) -> bool:
    extents = manifest.get("extents", [])
    return bool(extents) and all("xxh64" in shard or "crc64" in shard for extent in extents for shard in extent.get("shards", []))


def _sha256_bytes(data: Any) -> str:
    return hashlib.sha256(data).hexdigest()


def _rotl64(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (64 - shift))) & 0xFFFFFFFFFFFFFFFF


def _xxh64_round(acc: int, value: int) -> int:
    acc = (acc + (value * 0xC2B2AE3D27D4EB4F)) & 0xFFFFFFFFFFFFFFFF
    acc = _rotl64(acc, 31)
    return (acc * 0x9E3779B185EBCA87) & 0xFFFFFFFFFFFFFFFF


def _xxh64_merge(acc: int, value: int) -> int:
    acc ^= _xxh64_round(0, value)
    return ((acc * 0x9E3779B185EBCA87) + 0x85EBCA77C2B2AE63) & 0xFFFFFFFFFFFFFFFF


def _xxh64_hex(data: Any) -> str:
    view = memoryview(data).cast("B")
    length = len(view)
    offset = 0
    if length >= 32:
        limit = length - 32
        v1 = (0x9E3779B185EBCA87 + 0xC2B2AE3D27D4EB4F) & 0xFFFFFFFFFFFFFFFF
        v2 = 0xC2B2AE3D27D4EB4F
        v3 = 0
        v4 = (-0x9E3779B185EBCA87) & 0xFFFFFFFFFFFFFFFF
        while offset <= limit:
            v1 = _xxh64_round(v1, int.from_bytes(view[offset : offset + 8], "little")); offset += 8
            v2 = _xxh64_round(v2, int.from_bytes(view[offset : offset + 8], "little")); offset += 8
            v3 = _xxh64_round(v3, int.from_bytes(view[offset : offset + 8], "little")); offset += 8
            v4 = _xxh64_round(v4, int.from_bytes(view[offset : offset + 8], "little")); offset += 8
        h = (_rotl64(v1, 1) + _rotl64(v2, 7) + _rotl64(v3, 12) + _rotl64(v4, 18)) & 0xFFFFFFFFFFFFFFFF
        h = _xxh64_merge(h, v1)
        h = _xxh64_merge(h, v2)
        h = _xxh64_merge(h, v3)
        h = _xxh64_merge(h, v4)
    else:
        h = 0x27D4EB2F165667C5
    h = (h + length) & 0xFFFFFFFFFFFFFFFF
    while offset + 8 <= length:
        h ^= _xxh64_round(0, int.from_bytes(view[offset : offset + 8], "little"))
        h = ((_rotl64(h, 27) * 0x9E3779B185EBCA87) + 0x85EBCA77C2B2AE63) & 0xFFFFFFFFFFFFFFFF
        offset += 8
    if offset + 4 <= length:
        h ^= (int.from_bytes(view[offset : offset + 4], "little") * 0x9E3779B185EBCA87) & 0xFFFFFFFFFFFFFFFF
        h = ((_rotl64(h, 23) * 0xC2B2AE3D27D4EB4F) + 0x165667B19E3779F9) & 0xFFFFFFFFFFFFFFFF
        offset += 4
    while offset < length:
        h ^= (view[offset] * 0x27D4EB2F165667C5) & 0xFFFFFFFFFFFFFFFF
        h = (_rotl64(h, 11) * 0x9E3779B185EBCA87) & 0xFFFFFFFFFFFFFFFF
        offset += 1
    h ^= h >> 33
    h = (h * 0xC2B2AE3D27D4EB4F) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> 29
    h = (h * 0x165667B19E3779F9) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> 32
    return f"{h:016x}"


_CRC64_TABLE: list[int] | None = None


def _crc64_hex(data: Any) -> str:
    global _CRC64_TABLE
    if _CRC64_TABLE is None:
        _CRC64_TABLE = _build_crc64_table()
    crc = 0
    for byte in memoryview(data).cast("B"):
        crc = _CRC64_TABLE[((crc >> 56) ^ byte) & 0xFF] ^ ((crc << 8) & 0xFFFFFFFFFFFFFFFF)
    return f"{crc:016x}"


def _build_crc64_table() -> list[int]:
    poly = 0x42F0E1EBA9EA3693
    table: list[int] = []
    for index in range(256):
        crc = index << 56
        for _ in range(8):
            crc = ((crc << 1) ^ poly) if (crc & 0x8000000000000000) else (crc << 1)
            crc &= 0xFFFFFFFFFFFFFFFF
        table.append(crc)
    return table


def _xor_many(chunks: list[Any]) -> bytes:
    if not chunks:
        raise ValueError("cannot XOR an empty shard set")
    length = len(chunks[0])
    out = bytearray(length)
    step = 1024 * 1024
    views = [memoryview(chunk) for chunk in chunks]
    for chunk in chunks:
        if len(chunk) != length:
            raise ValueError("XOR shards must have equal length")
    for offset in range(0, length, step):
        size = min(step, length - offset)
        value = 0
        for view in views:
            value ^= int.from_bytes(view[offset : offset + size], "little")
        out[offset : offset + size] = value.to_bytes(size, "little")
    return bytes(out)


def _object_key(namespace: str, key: str) -> str:
    namespace = namespace.strip("/")
    key = key.strip("/")
    if not namespace or not key:
        raise ValueError("namespace and key must be non-empty")
    return f"{namespace}/{key}"


def _data_shard_indexes(extent: dict[str, Any]) -> list[int]:
    pairs: list[tuple[int, int]] = []
    for index, shard in enumerate(extent["shards"]):
        role = str(shard["role"])
        if role.startswith("data"):
            pairs.append((int(role[4:]), index))
    return [index for _, index in sorted(pairs)]


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    if not safe:
        raise ValueError("safe name is empty")
    return safe[:160]


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write_bytes(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        tmp = Path(handle.name)
    tmp.replace(path)
