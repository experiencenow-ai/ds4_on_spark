#!/usr/bin/env python3
"""Coordinator-side KV checkpoint manifest helpers for DS4 pipeline stages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


MANIFEST_VERSION = 1
DEFAULT_MANIFEST = "pipeline_kv_manifest.json"
IDENTITY_FIELDS = (
	"model_id",
	"runtime_id",
	"tokenizer_sha256",
	"quantization_id",
	"rope_config_sha256",
	"kv_format_id",
)


class PipelineKvCacheError(ValueError):
	pass


@dataclass(frozen=True)
class StageShard:
	stage_index: int
	path: str
	sha256: str
	payload_bytes: int


@dataclass(frozen=True)
class CacheLookup:
	kv_cache_hit: bool
	hit_token_count: int
	stage_kv_paths: list[str]
	entry_key: str
	reason: str
	prefill_wall_ms: float


def sha1_rendered_prompt(rendered_prompt: str) -> str:
	return hashlib.sha1(rendered_prompt.encode("utf-8")).hexdigest()


def sha1_token_ids(token_ids: Iterable[int]) -> str:
	h = hashlib.sha1()
	for token_id in token_ids:
		if not isinstance(token_id, int) or token_id < 0 or token_id > 0xFFFFFFFF:
			raise PipelineKvCacheError(f"invalid token id: {token_id!r}")
		h.update(int(token_id).to_bytes(4, "little", signed=False))
	return h.hexdigest()


def sha256_file(path: Path) -> str:
	h = hashlib.sha256()
	with path.open("rb") as f:
		while True:
			chunk = f.read(1024 * 1024)
			if not chunk:
				break
			h.update(chunk)
	return h.hexdigest()


def read_token_ids(text: str) -> list[int]:
	if text.strip() == "":
		return []
	out: list[int] = []
	for raw in text.replace("\n", ",").split(","):
		item = raw.strip()
		if item == "":
			continue
		value = int(item, 10)
		if value < 0:
			raise PipelineKvCacheError("token ids must be non-negative")
		out.append(value)
	return out


def normalize_identity(identity: dict[str, Any] | None) -> dict[str, str]:
	if identity is None:
		return {}
	out: dict[str, str] = {}
	for key, value in identity.items():
		if key not in IDENTITY_FIELDS:
			raise PipelineKvCacheError(f"unsupported identity field: {key}")
		if not isinstance(value, str) or value.strip() == "":
			raise PipelineKvCacheError(f"{key} must be a non-empty string")
		out[key] = value
	return out


def _identity_matches(entry: dict[str, Any], identity: dict[str, str]) -> bool:
	entry_identity = entry.get("identity", {})
	if not isinstance(entry_identity, dict):
		return False
	if not identity:
		return len(entry_identity) == 0
	for key, value in identity.items():
		if entry_identity.get(key) != value:
			return False
	return True


def _tokens_start_with(tokens: list[int], prefix: list[int]) -> bool:
	return len(prefix) <= len(tokens) and tokens[: len(prefix)] == prefix


def _load_json(path: Path) -> dict[str, Any]:
	if not path.exists():
		return {"version": MANIFEST_VERSION, "entries": []}
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise PipelineKvCacheError(f"{path}: manifest root must be an object")
	if obj.get("version") != MANIFEST_VERSION:
		raise PipelineKvCacheError(f"{path}: unsupported manifest version")
	if not isinstance(obj.get("entries"), list):
		raise PipelineKvCacheError(f"{path}: entries must be a list")
	return obj


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as f:
			json.dump(obj, f, indent=2, sort_keys=True)
			f.write("\n")
		os.replace(tmp_name, path)
	except BaseException:
		try:
			os.unlink(tmp_name)
		except FileNotFoundError:
			pass
		raise


def stage_shard_from_file(stage_index: int, path: Path) -> StageShard:
	if stage_index < 0:
		raise PipelineKvCacheError("stage shard index must be non-negative")
	if not path.exists():
		raise PipelineKvCacheError(f"stage shard does not exist: {path}")
	if not path.is_file():
		raise PipelineKvCacheError(f"stage shard is not a file: {path}")
	payload_bytes = path.stat().st_size
	if payload_bytes <= 0:
		raise PipelineKvCacheError(f"stage shard is empty: {path}")
	return StageShard(stage_index=stage_index, path=str(path), sha256=sha256_file(path), payload_bytes=payload_bytes)


class PipelineKvCache:
	def __init__(self, cache_dir: Path, manifest_name: str = DEFAULT_MANIFEST):
		self.cache_dir = cache_dir
		self.manifest_path = cache_dir / manifest_name

	def load_manifest(self) -> dict[str, Any]:
		return _load_json(self.manifest_path)

	def save_manifest(self, manifest: dict[str, Any]) -> None:
		_atomic_write_json(self.manifest_path, manifest)

	def store_entry(
		self,
		rendered_prompt: str,
		token_ids: list[int],
		stage_shards: list[StageShard],
		identity: dict[str, str] | None = None,
		prefill_wall_ms: float = 0.0,
	) -> dict[str, Any]:
		if len(token_ids) == 0:
			raise PipelineKvCacheError("cannot store empty token prefix")
		if len(stage_shards) == 0:
			raise PipelineKvCacheError("cannot store cache entry without stage shards")
		indexes = [s.stage_index for s in stage_shards]
		if len(set(indexes)) != len(indexes):
			raise PipelineKvCacheError("stage shard indexes must be unique")
		if sorted(indexes) != list(range(len(indexes))):
			raise PipelineKvCacheError("stage shard indexes must be contiguous from zero")
		entry = {
			"entry_key": sha1_rendered_prompt(rendered_prompt),
			"rendered_prompt_sha1": sha1_rendered_prompt(rendered_prompt),
			"token_ids_sha1": sha1_token_ids(token_ids),
			"token_ids": list(token_ids),
			"token_count": len(token_ids),
			"identity": normalize_identity(identity),
			"stage_shards": [s.__dict__ for s in sorted(stage_shards, key=lambda shard: shard.stage_index)],
			"prefill_wall_ms": float(prefill_wall_ms),
			"created_at": time.time(),
		}
		manifest = self.load_manifest()
		entries = [item for item in manifest["entries"] if item.get("entry_key") != entry["entry_key"]]
		entries.append(entry)
		manifest["entries"] = sorted(entries, key=lambda item: (int(item.get("token_count", 0)), str(item.get("entry_key", ""))))
		self.save_manifest(manifest)
		return entry

	def lookup(self, rendered_prompt: str, token_ids: list[int], identity: dict[str, str] | None = None) -> CacheLookup:
		manifest = self.load_manifest()
		identity_norm = normalize_identity(identity)
		best: dict[str, Any] | None = None
		for entry in manifest["entries"]:
			if not isinstance(entry, dict):
				continue
			entry_tokens = entry.get("token_ids")
			if not isinstance(entry_tokens, list) or not all(isinstance(v, int) for v in entry_tokens):
				continue
			if not _identity_matches(entry, identity_norm):
				continue
			if not _tokens_start_with(token_ids, entry_tokens):
				continue
			if best is None or len(entry_tokens) > int(best.get("token_count", 0)):
				best = entry
		if best is None:
			return CacheLookup(False, 0, [], "", "miss", 0.0)
		error = self._verify_entry_shards(best)
		if error:
			return CacheLookup(False, 0, [], str(best.get("entry_key", "")), error, 0.0)
		shards = best.get("stage_shards", [])
		paths = [str(item["path"]) for item in shards if isinstance(item, dict)]
		return CacheLookup(
			kv_cache_hit=True,
			hit_token_count=int(best["token_count"]),
			stage_kv_paths=paths,
			entry_key=str(best["entry_key"]),
			reason="hit",
			prefill_wall_ms=float(best.get("prefill_wall_ms", 0.0)),
		)

	def _verify_entry_shards(self, entry: dict[str, Any]) -> str:
		shards = entry.get("stage_shards")
		if not isinstance(shards, list) or len(shards) == 0:
			return "entry has no stage shards"
		for item in shards:
			if not isinstance(item, dict):
				return "stage shard metadata is invalid"
			path = Path(str(item.get("path", "")))
			if not path.exists():
				return f"stage shard missing: {path}"
			want = str(item.get("sha256", ""))
			got = sha256_file(path)
			if got != want:
				return f"stage shard hash mismatch: {path}"
			if int(item.get("payload_bytes", -1)) != path.stat().st_size:
				return f"stage shard size mismatch: {path}"
		return ""


def compare_token_runs(live_token_ids: list[int], restored_token_ids: list[int]) -> dict[str, Any]:
	return {
		"match": live_token_ids == restored_token_ids,
		"live_token_ids": live_token_ids,
		"restored_token_ids": restored_token_ids,
	}


def prefill_speedup_ok(cold_prefill_wall_ms: float, hit_prefill_wall_ms: float, required: float = 5.0) -> bool:
	if cold_prefill_wall_ms <= 0.0 or hit_prefill_wall_ms <= 0.0:
		return False
	return (cold_prefill_wall_ms / hit_prefill_wall_ms) >= required


def build_checkpoint_paths(cache_dir: Path, entry_key: str, stage_count: int) -> list[Path]:
	if stage_count <= 0:
		raise PipelineKvCacheError("stage_count must be positive")
	return [cache_dir / entry_key / f"stage{idx}.kv" for idx in range(stage_count)]


StageSaveFn = Callable[[int, Path], None]
StageRestoreFn = Callable[[int, Path], None]


def save_stage_checkpoints(
	cache: PipelineKvCache,
	rendered_prompt: str,
	token_ids: list[int],
	stage_count: int,
	save_stage: StageSaveFn,
	identity: dict[str, str] | None = None,
	prefill_wall_ms: float = 0.0,
) -> dict[str, Any]:
	entry_key = sha1_rendered_prompt(rendered_prompt)
	paths = build_checkpoint_paths(cache.cache_dir, entry_key, stage_count)
	for stage_index, path in enumerate(paths):
		path.parent.mkdir(parents=True, exist_ok=True)
		save_stage(stage_index, path)
	shards = [stage_shard_from_file(index, path) for index, path in enumerate(paths)]
	return cache.store_entry(rendered_prompt, token_ids, shards, identity=identity, prefill_wall_ms=prefill_wall_ms)


def restore_stage_checkpoints(lookup: CacheLookup, restore_stage: StageRestoreFn) -> None:
	if not lookup.kv_cache_hit:
		raise PipelineKvCacheError(f"cannot restore cache miss: {lookup.reason}")
	for stage_index, raw_path in enumerate(lookup.stage_kv_paths):
		restore_stage(stage_index, Path(raw_path))


def _parse_stage_shards(items: list[str]) -> list[StageShard]:
	shards: list[StageShard] = []
	for raw in items:
		left, sep, right = raw.partition(":")
		if sep != ":":
			raise PipelineKvCacheError("--stage-shard entries must be INDEX:PATH")
		shards.append(stage_shard_from_file(int(left, 10), Path(right)))
	return shards


def _load_identity(path: str | None) -> dict[str, str]:
	if path is None:
		return {}
	obj = json.loads(Path(path).read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise PipelineKvCacheError("identity JSON must be an object")
	return normalize_identity(obj)


def _print_json(obj: dict[str, Any]) -> None:
	print(json.dumps(obj, indent=2, sort_keys=True))


def main() -> int:
	ap = argparse.ArgumentParser()
	sub = ap.add_subparsers(dest="cmd", required=True)
	store = sub.add_parser("store")
	store.add_argument("cache_dir")
	store.add_argument("--rendered-prompt", required=True)
	store.add_argument("--token-ids", required=True)
	store.add_argument("--stage-shard", action="append", default=[])
	store.add_argument("--identity-json")
	store.add_argument("--prefill-wall-ms", type=float, default=0.0)
	lookup = sub.add_parser("lookup")
	lookup.add_argument("cache_dir")
	lookup.add_argument("--rendered-prompt", required=True)
	lookup.add_argument("--token-ids", required=True)
	lookup.add_argument("--identity-json")
	args = ap.parse_args()
	cache = PipelineKvCache(Path(args.cache_dir))
	if args.cmd == "store":
		entry = cache.store_entry(
			args.rendered_prompt,
			read_token_ids(args.token_ids),
			_parse_stage_shards(args.stage_shard),
			identity=_load_identity(args.identity_json),
			prefill_wall_ms=args.prefill_wall_ms,
		)
		_print_json(entry)
		return 0
	if args.cmd == "lookup":
		result = cache.lookup(args.rendered_prompt, read_token_ids(args.token_ids), identity=_load_identity(args.identity_json))
		_print_json(result.__dict__)
		return 0
	raise PipelineKvCacheError(f"unknown command: {args.cmd}")


if __name__ == "__main__":
	raise SystemExit(main())
