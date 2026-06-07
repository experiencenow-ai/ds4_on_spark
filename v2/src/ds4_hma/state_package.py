from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import tempfile
import time
from typing import Any

HMA_PACKAGE_FORMAT = "ds4-dsv4-hma-state-package-v1"
HMA_STORE_INDEX_FORMAT = "ds4-dsv4-hma-store-index-v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def token_hash(token_ids: list[int] | tuple[int, ...]) -> str:
    body = json.dumps([int(token) for token in token_ids], separators=(",", ":")).encode("utf-8")
    return sha256_bytes(body)


@dataclass(frozen=True)
class HmaStatePart:
    part_id: str
    kind: str
    relative_path: str
    sha256: str
    bytes: int
    layer_name: str | None = None
    group_index: int | None = None
    dtype: str | None = None
    shape: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "kind": self.kind,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "layer_name": self.layer_name,
            "group_index": self.group_index,
            "dtype": self.dtype,
            "shape": list(self.shape),
            "metadata": self.metadata,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "HmaStatePart":
        return HmaStatePart(
            part_id=str(data["part_id"]),
            kind=str(data["kind"]),
            relative_path=str(data["relative_path"]),
            sha256=str(data["sha256"]),
            bytes=int(data["bytes"]),
            layer_name=str(data["layer_name"]) if data.get("layer_name") is not None else None,
            group_index=int(data["group_index"]) if data.get("group_index") is not None else None,
            dtype=str(data["dtype"]) if data.get("dtype") is not None else None,
            shape=tuple(int(item) for item in data.get("shape", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class HmaStatePackage:
    package_id: str
    model_id: str
    tokenizer_hash: str
    token_hash: str
    prompt_hash: str
    token_ids: tuple[int, ...]
    token_count: int
    block_size: int
    hma_layout: str
    state_parts: tuple[HmaStatePart, ...]
    created_unix_s: float
    layer_partition_fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": HMA_PACKAGE_FORMAT,
            "package_id": self.package_id,
            "model_id": self.model_id,
            "tokenizer_hash": self.tokenizer_hash,
            "token_hash": self.token_hash,
            "prompt_hash": self.prompt_hash,
            "token_ids": list(self.token_ids),
            "token_count": self.token_count,
            "block_size": self.block_size,
            "hma_layout": self.hma_layout,
            "created_unix_s": self.created_unix_s,
            "layer_partition_fingerprint": self.layer_partition_fingerprint,
            "metadata": self.metadata,
            "state_parts": [part.to_json() for part in self.state_parts],
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "HmaStatePackage":
        if data.get("format") != HMA_PACKAGE_FORMAT:
            raise ValueError(f"unsupported HMA package format: {data.get('format')!r}")
        return HmaStatePackage(
            package_id=str(data["package_id"]),
            model_id=str(data["model_id"]),
            tokenizer_hash=str(data["tokenizer_hash"]),
            token_hash=str(data["token_hash"]),
            prompt_hash=str(data["prompt_hash"]),
            token_ids=tuple(int(token) for token in data.get("token_ids", [])),
            token_count=int(data["token_count"]),
            block_size=int(data["block_size"]),
            hma_layout=str(data["hma_layout"]),
            created_unix_s=float(data["created_unix_s"]),
            layer_partition_fingerprint=str(data["layer_partition_fingerprint"]) if data.get("layer_partition_fingerprint") is not None else None,
            metadata=dict(data.get("metadata", {})),
            state_parts=tuple(HmaStatePart.from_json(part) for part in data.get("state_parts", [])),
        )


class HmaPersistentStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.packages_dir = self.root / "packages"
        self.parts_dir = self.root / "parts"
        self.index_path = self.root / "index.json"
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.parts_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_index({"format": HMA_STORE_INDEX_FORMAT, "packages_by_token_hash": {}})

    def write_part(
        self,
        package_id: str,
        part_id: str,
        data: bytes,
        *,
        kind: str = "opaque_bytes",
        suffix: str = ".bin",
        layer_name: str | None = None,
        group_index: int | None = None,
        dtype: str | None = None,
        shape: tuple[int, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> HmaStatePart:
        safe_package = _safe_name(package_id)
        safe_part = _safe_name(part_id)
        part_dir = self.parts_dir / safe_package
        part_dir.mkdir(parents=True, exist_ok=True)
        relative_path = f"parts/{safe_package}/{safe_part}{suffix}"
        path = self.root / relative_path
        _atomic_write_bytes(path, data)
        return HmaStatePart(
            part_id=part_id,
            kind=kind,
            relative_path=relative_path,
            sha256=sha256_bytes(data),
            bytes=len(data),
            layer_name=layer_name,
            group_index=group_index,
            dtype=dtype,
            shape=shape,
            metadata=metadata or {},
        )

    def write_package(self, package: HmaStatePackage) -> Path:
        package_path = self.package_path(package.package_id)
        _atomic_write_json(package_path, package.to_json())
        index = self._read_index()
        index.setdefault("packages_by_token_hash", {})[package.token_hash] = package.package_id
        if package.layer_partition_fingerprint:
            index.setdefault("packages_by_token_and_partition", {})[_token_partition_key(package.token_hash, package.layer_partition_fingerprint)] = package.package_id
        self._write_index(index)
        return package_path

    def create_manifest_package(
        self,
        *,
        model_id: str,
        tokenizer_hash: str,
        token_ids: list[int] | tuple[int, ...],
        block_size: int,
        hma_layout: str,
        state_parts: list[HmaStatePart] | tuple[HmaStatePart, ...],
        layer_partition_fingerprint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HmaStatePackage:
        thash = token_hash(token_ids)
        package_id_suffix = _token_partition_key(thash, layer_partition_fingerprint)[:24] if layer_partition_fingerprint else thash[:24]
        package_id = f"hma_{package_id_suffix}"
        return HmaStatePackage(
            package_id=package_id,
            model_id=model_id,
            tokenizer_hash=tokenizer_hash,
            token_hash=thash,
            prompt_hash=thash,
            token_ids=tuple(int(token) for token in token_ids),
            token_count=len(token_ids),
            block_size=block_size,
            hma_layout=hma_layout,
            state_parts=tuple(state_parts),
            created_unix_s=time.time(),
            layer_partition_fingerprint=layer_partition_fingerprint,
            metadata=metadata or {},
        )

    def package_path(self, package_id: str) -> Path:
        return self.packages_dir / f"{_safe_name(package_id)}.json"

    def lookup_by_token_ids(self, token_ids: list[int] | tuple[int, ...], *, layer_partition_fingerprint: str | None = None) -> HmaStatePackage | None:
        index = self._read_index()
        thash = token_hash(token_ids)
        if layer_partition_fingerprint:
            package_id = index.get("packages_by_token_and_partition", {}).get(_token_partition_key(thash, layer_partition_fingerprint))
        else:
            package_id = index.get("packages_by_token_hash", {}).get(thash)
        if not package_id:
            return None
        path = self.package_path(str(package_id))
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            package = HmaStatePackage.from_json(json.load(handle))
        if package.token_hash != thash:
            raise ValueError(f"HMA package token hash mismatch: {package.package_id}")
        if layer_partition_fingerprint and package.layer_partition_fingerprint != layer_partition_fingerprint:
            return None
        self.validate_package(package)
        return package

    def validate_package(self, package: HmaStatePackage) -> None:
        for part in package.state_parts:
            path = _store_path(self.root, part.relative_path)
            if not path.exists():
                raise ValueError(f"missing HMA state part: {part.relative_path}")
            data = path.read_bytes()
            if sha256_bytes(data) != part.sha256:
                raise ValueError(f"HMA state part checksum mismatch: {part.relative_path}")

    def _read_index(self) -> dict[str, Any]:
        with self.index_path.open("r", encoding="utf-8") as handle:
            index = json.load(handle)
        if index.get("format") != HMA_STORE_INDEX_FORMAT:
            raise ValueError(f"unsupported HMA store index format: {index.get('format')!r}")
        return index

    def _write_index(self, index: dict[str, Any]) -> None:
        _atomic_write_json(self.index_path, index)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        tmp = Path(handle.name)
    tmp.replace(path)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write_bytes(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)[:160]


def _token_partition_key(thash: str, layer_partition_fingerprint: str | None) -> str:
    material = {
        "token_hash": thash,
        "layer_partition_fingerprint": layer_partition_fingerprint or "",
    }
    return sha256_text(json.dumps(material, sort_keys=True, separators=(",", ":")))


def _store_path(root: Path, relative_path: str) -> Path:
    path = (root / relative_path).resolve()
    root_path = root.resolve()
    if root_path != path and root_path not in path.parents:
        raise ValueError(f"HMA state part escapes store root: {relative_path}")
    return path
