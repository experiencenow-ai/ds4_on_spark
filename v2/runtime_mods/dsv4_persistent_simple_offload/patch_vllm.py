#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    pkg = _vllm_package_dir()
    target_dir = pkg / "v1" / "simple_kv_offload"
    shutil.copy2(here / "persistent_disk.py", target_dir / "persistent_disk.py")
    _patch_metadata(target_dir / "metadata.py")
    _patch_manager(target_dir / "manager.py")
    _patch_worker(target_dir / "worker.py")
    print(f"DS4 persistent SimpleCPUOffload patch installed in {pkg}")
    return 0


def _vllm_package_dir() -> Path:
    override = os.getenv("DS4_VLLM_PACKAGE_DIR")
    if override:
        return Path(override).resolve()
    module = importlib.import_module("vllm")
    return Path(module.__file__).resolve().parent


def _patch_metadata(path: Path) -> None:
    text = _read_for_patch(path)
    text = _replace_once(
        text,
        "    load_cpu_blocks: list[int] = field(default_factory=list)\n",
        "    load_cpu_blocks: list[int] = field(default_factory=list)\n"
        "    load_block_hashes: list[str] = field(default_factory=list)\n",
        "metadata load_block_hashes",
    )
    text = _replace_once(
        text,
        "    store_cpu_blocks: list[int] = field(default_factory=list)\n",
        "    store_cpu_blocks: list[int] = field(default_factory=list)\n"
        "    store_block_hashes: list[str] = field(default_factory=list)\n",
        "metadata store_block_hashes",
    )
    _write_if_changed(path, text)


def _patch_manager(path: Path) -> None:
    text = _read_for_patch(path)
    text = _replace_once(
        text,
        "from vllm.v1.simple_kv_offload.metadata import (\n"
        "    SimpleCPUOffloadMetadata,\n"
        "    SimpleCPUOffloadWorkerMetadata,\n"
        ")\n",
        "from vllm.v1.simple_kv_offload.metadata import (\n"
        "    SimpleCPUOffloadMetadata,\n"
        "    SimpleCPUOffloadWorkerMetadata,\n"
        ")\n"
        "from vllm.v1.simple_kv_offload.persistent_disk import PersistentSimpleOffloadStore\n",
        "manager persistent import",
    )
    text = _replace_once(
        text,
        "@dataclass\n"
        "class TransferMeta:\n"
        "    gpu_block_ids: list[int]\n"
        "    cpu_block_ids: list[int]\n",
        "@dataclass\n"
        "class TransferMeta:\n"
        "    gpu_block_ids: list[int]\n"
        "    cpu_block_ids: list[int]\n"
        "    block_hashes: list[str] = field(default_factory=list)\n",
        "manager TransferMeta block_hashes",
    )
    text = _replace_once(
        text,
        "        self.cpu_block_pool: BlockPool = self.cpu_coordinator.block_pool\n\n"
        "        # GPU block pool reference",
        "        self.cpu_block_pool: BlockPool = self.cpu_coordinator.block_pool\n"
        "        self._persistent_store = PersistentSimpleOffloadStore.from_env(\n"
        "            role=\"scheduler\",\n"
        "            vllm_config=vllm_config,\n"
        "            num_cpu_blocks=self.num_cpu_blocks,\n"
        "        )\n"
        "        if self._persistent_store is not None:\n"
        "            restored = 0\n"
        "            for entry in self._persistent_store.load_scheduler_entries(self.num_cpu_blocks):\n"
        "                cpu_block = self.cpu_block_pool.blocks[entry.cpu_block_id]\n"
        "                cpu_block._block_hash = entry.block_hash  # type: ignore[assignment]\n"
        "                self.cpu_block_pool.cached_block_hash_to_block.insert(entry.block_hash, cpu_block)\n"
        "                restored += 1\n"
        "            logger.info(\"SimpleCPUOffloadScheduler: restored %d persistent CPU blocks\", restored)\n\n"
        "        # GPU block pool reference",
        "manager scheduler restore",
    )
    text = _replace_once(
        text,
        "        gpu_block_ids: list[int] = []\n"
        "        cpu_block_ids: list[int] = []\n"
        "        cpu_blocks_to_touch: list[KVCacheBlock] = []\n",
        "        gpu_block_ids: list[int] = []\n"
        "        cpu_block_ids: list[int] = []\n"
        "        cpu_block_hashes: list[str] = []\n"
        "        cpu_blocks_to_touch: list[KVCacheBlock] = []\n",
        "manager load hash list init",
    )
    text = _replace_once(
        text,
        "                gpu_block_ids.append(group_gpu_ids[gpu_ext_start + i])\n"
        "                cpu_block_ids.append(cpu_blk.block_id)\n"
        "                cpu_blocks_to_touch.append(cpu_blk)\n",
        "                gpu_block_ids.append(group_gpu_ids[gpu_ext_start + i])\n"
        "                cpu_block_ids.append(cpu_blk.block_id)\n"
        "                assert cpu_blk.block_hash is not None\n"
        "                cpu_block_hashes.append(cpu_blk.block_hash.hex())\n"
        "                cpu_blocks_to_touch.append(cpu_blk)\n",
        "manager load hash append",
    )
    text = _replace_once(
        text,
        "        self._reqs_to_load[req_id] = LoadRequestState(\n"
        "            request=request, transfer_meta=TransferMeta(gpu_block_ids, cpu_block_ids)\n"
        "        )\n",
        "        self._reqs_to_load[req_id] = LoadRequestState(\n"
        "            request=request,\n"
        "            transfer_meta=TransferMeta(gpu_block_ids, cpu_block_ids, cpu_block_hashes),\n"
        "        )\n",
        "manager load TransferMeta hashes",
    )
    text = _replace_once(
        text,
        "        cpu_hit_blocks, hit_length = self.cpu_coordinator.find_longest_cache_hit(\n"
        "            hashes_to_load, max_hit_len\n"
        "        )\n"
        "        assert hit_length == num_external_tokens, (\n"
        "            f\"Expected {num_external_tokens} hit tokens, got {hit_length}\"\n"
        "        )\n",
        "        lookup_hashes_to_load = hashes_to_load\n"
        "        if self._persistent_store is not None:\n"
        "            guard_tokens = max(\n"
        "                self.block_size,\n"
        "                getattr(self.cpu_coordinator, \"lcm_block_size\", self.block_size),\n"
        "            )\n"
        "            guard_blocks = max(1, guard_tokens // self.block_size)\n"
        "            lookup_hashes_to_load = request.block_hashes[\n"
        "                skipped : skipped + num_blocks_to_load + guard_blocks\n"
        "            ]\n"
        "            max_hit_len = len(lookup_hashes_to_load) * self.block_size\n"
        "        cpu_hit_blocks, hit_length = self.cpu_coordinator.find_longest_cache_hit(\n"
        "            lookup_hashes_to_load, max_hit_len\n"
        "        )\n"
        "        if self._persistent_store is not None and hit_length < num_external_tokens:\n"
        "            guard_tokens = max(\n"
        "                self.block_size,\n"
        "                getattr(self.cpu_coordinator, \"lcm_block_size\", self.block_size),\n"
        "            )\n"
        "            guard_blocks = max(1, guard_tokens // self.block_size)\n"
        "            while skipped >= guard_blocks and hit_length < num_external_tokens:\n"
        "                candidate_skipped = skipped - guard_blocks\n"
        "                candidate_hashes = request.block_hashes[\n"
        "                    candidate_skipped : candidate_skipped + num_blocks_to_load + guard_blocks\n"
        "                ]\n"
        "                candidate_blocks, candidate_hit_length = (\n"
        "                    self.cpu_coordinator.find_longest_cache_hit(\n"
        "                        candidate_hashes, max_hit_len\n"
        "                    )\n"
        "                )\n"
        "                if candidate_hit_length <= hit_length:\n"
        "                    break\n"
        "                logger.info(\n"
        "                    \"DS4 persistent SimpleCPUOffload load offset adjusted: request=%s tokens=%d previous_tokens=%d\",\n"
        "                    req_id,\n"
        "                    candidate_hit_length,\n"
        "                    hit_length,\n"
        "                )\n"
        "                skipped = candidate_skipped\n"
        "                num_computed_tokens = skipped * self.block_size\n"
        "                hashes_to_load = candidate_hashes[:num_blocks_to_load]\n"
        "                cpu_hit_blocks = candidate_blocks\n"
        "                hit_length = candidate_hit_length\n"
        "        assert hit_length == num_external_tokens, (\n"
        "            f\"Expected {num_external_tokens} hit tokens, got {hit_length}\"\n"
        "        )\n",
        "manager persistent load offset guard",
    )
    text = _replace_once(
        text,
        "        if hit_length > 0:\n"
        "            return hit_length, True\n",
        "        if hit_length > 0:\n"
        "            if self._persistent_store is not None:\n"
        "                raw_hit_length = hit_length\n"
        "                guard_tokens = max(\n"
        "                    self.block_size,\n"
        "                    getattr(self.cpu_coordinator, \"lcm_block_size\", self.block_size),\n"
        "                )\n"
        "                # HMA grouped/sliding KV needs one aligned lookahead block\n"
        "                # during post-allocation validation. Advertise one LCM less\n"
        "                # than the raw hit, then validate with that lookahead.\n"
        "                hit_length = max(0, hit_length - guard_tokens)\n"
        "                if hit_length == 0:\n"
        "                    return 0, False\n"
        "                logger.info(\n"
        "                    \"DS4 persistent SimpleCPUOffload scheduler hit: request=%s tokens=%d raw_tokens=%d guard_tokens=%d\",\n"
        "                    request.request_id,\n"
        "                    hit_length,\n"
        "                    raw_hit_length,\n"
        "                    guard_tokens,\n"
        "                )\n"
        "            return hit_length, True\n",
        "manager persistent hit log",
    )
    text = _replace_once(
        text,
        "        store_gpu, store_cpu, store_req_ids = self.prepare_store_specs(scheduler_output)\n"
        "        if store_gpu:\n",
        "        store_gpu, store_cpu, store_req_ids = self.prepare_store_specs(scheduler_output)\n"
        "        store_hashes = self._cpu_block_hashes(store_cpu)\n"
        "        if store_gpu:\n",
        "manager store_hashes init",
    )
    text = _replace_once(
        text,
        "            self._store_event_to_blocks[store_event] = TransferMeta(\n"
        "                store_gpu, store_cpu\n"
        "            )\n",
        "            self._store_event_to_blocks[store_event] = TransferMeta(\n"
        "                store_gpu, store_cpu, store_hashes\n"
        "            )\n",
        "manager store TransferMeta hashes",
    )
    text = _replace_once(
        text,
        "        load_cpu: list[int] = []\n"
        "        load_req_ids: list[str] = []\n",
        "        load_cpu: list[int] = []\n"
        "        load_hashes: list[str] = []\n"
        "        load_req_ids: list[str] = []\n",
        "manager load_hashes init",
    )
    text = _replace_once(
        text,
        "            load_gpu.extend(load_state.transfer_meta.gpu_block_ids)\n"
        "            load_cpu.extend(load_state.transfer_meta.cpu_block_ids)\n"
        "            load_req_ids.append(req_id)\n",
        "            load_gpu.extend(load_state.transfer_meta.gpu_block_ids)\n"
        "            load_cpu.extend(load_state.transfer_meta.cpu_block_ids)\n"
        "            load_hashes.extend(load_state.transfer_meta.block_hashes)\n"
        "            load_req_ids.append(req_id)\n",
        "manager load_hashes extend",
    )
    text = _replace_once(
        text,
        "            load_event=load_event,\n"
        "            load_gpu_blocks=load_gpu,\n"
        "            load_cpu_blocks=load_cpu,\n"
        "            load_event_to_reqs=self._load_event_to_reqs,\n"
        "            store_event=store_event,\n"
        "            store_gpu_blocks=store_gpu,\n"
        "            store_cpu_blocks=store_cpu,\n",
        "            load_event=load_event,\n"
        "            load_gpu_blocks=load_gpu,\n"
        "            load_cpu_blocks=load_cpu,\n"
        "            load_block_hashes=load_hashes,\n"
        "            load_event_to_reqs=self._load_event_to_reqs,\n"
        "            store_event=store_event,\n"
        "            store_gpu_blocks=store_gpu,\n"
        "            store_cpu_blocks=store_cpu,\n"
        "            store_block_hashes=store_hashes,\n",
        "manager metadata hashes",
    )
    text = _replace_once(
        text,
        "        self._process_store_completion(transfer.gpu_block_ids, transfer.cpu_block_ids)\n"
        "        logger.debug(\n",
        "        self._process_store_completion(transfer.gpu_block_ids, transfer.cpu_block_ids)\n"
        "        if self._persistent_store is not None:\n"
        "            self._persistent_store.save_scheduler_blocks(transfer.cpu_block_ids, transfer.block_hashes)\n"
        "        logger.debug(\n",
        "manager scheduler persist index",
    )
    text = _replace_once(
        text,
        "    def update_connector_output(self, connector_output: KVConnectorOutput) -> None:\n",
        "    def _cpu_block_hashes(self, cpu_block_ids: list[int]) -> list[str]:\n"
        "        hashes: list[str] = []\n"
        "        for cpu_block_id in cpu_block_ids:\n"
        "            bhash = self.cpu_block_pool.blocks[cpu_block_id].block_hash\n"
        "            assert bhash is not None\n"
        "            hashes.append(bhash.hex())\n"
        "        return hashes\n\n"
        "    def update_connector_output(self, connector_output: KVConnectorOutput) -> None:\n",
        "manager cpu hash helper",
    )
    _write_if_changed(path, text)


def _patch_worker(path: Path) -> None:
    text = _read_for_patch(path)
    text = _replace_once(
        text,
        "from vllm.v1.simple_kv_offload.metadata import (\n"
        "    SimpleCPUOffloadMetadata,\n"
        "    SimpleCPUOffloadWorkerMetadata,\n"
        ")\n",
        "from vllm.v1.simple_kv_offload.metadata import (\n"
        "    SimpleCPUOffloadMetadata,\n"
        "    SimpleCPUOffloadWorkerMetadata,\n"
        ")\n"
        "from vllm.v1.simple_kv_offload.persistent_disk import PersistentSimpleOffloadStore\n",
        "worker persistent import",
    )
    text = _replace_once(
        text,
        "        self._completed_store_events: dict[int, int] = {}\n",
        "        self._completed_store_events: dict[int, int] = {}\n"
        "        self._persistent_store: PersistentSimpleOffloadStore | None = None\n"
        "        self._persistent_known: dict[int, str] = {}\n"
        "        self._pending_store_persist: dict[int, tuple[list[int], list[str]]] = {}\n",
        "worker persistent fields",
    )
    text = _replace_once(
        text,
        "        # Initialize copy backend with caches and streams.\n"
        "        self._backend.init(\n"
        "            self.gpu_kv_caches,\n"
        "            self.cpu_kv_caches,\n"
        "            self.device,\n"
        "            self.load_stream,\n"
        "            self.store_stream,\n"
        "        )\n",
        "        # Initialize copy backend with caches and streams.\n"
        "        self._backend.init(\n"
        "            self.gpu_kv_caches,\n"
        "            self.cpu_kv_caches,\n"
        "            self.device,\n"
        "            self.load_stream,\n"
        "            self.store_stream,\n"
        "        )\n"
        "        self._persistent_store = PersistentSimpleOffloadStore.from_env(\n"
        "            role=\"worker\",\n"
        "            vllm_config=self.vllm_config,\n"
        "            num_cpu_blocks=self.num_cpu_blocks,\n"
        "            tensor_names=list(self.cpu_kv_caches.keys()),\n"
        "        )\n"
        "        if self._persistent_store is not None:\n"
        "            self._persistent_known = self._persistent_store.restore_worker_blocks(\n"
        "                self.cpu_kv_caches, self.num_cpu_blocks\n"
        "            )\n"
        "            logger.info(\n"
        "                \"SimpleCPUOffloadWorker: restored %d persistent CPU blocks\",\n"
        "                len(self._persistent_known),\n"
        "            )\n",
        "worker restore after backend",
    )
    text = _replace_once(
        text,
        "        if metadata.load_event >= 0:\n"
        "            self._pending_load_event_indices.add(metadata.load_event)\n"
        "        if metadata.store_event >= 0:\n"
        "            self._pending_store_event_indices.add(metadata.store_event)\n",
        "        if metadata.load_event >= 0:\n"
        "            self._pending_load_event_indices.add(metadata.load_event)\n"
        "            if metadata.load_cpu_blocks and self._persistent_store is not None:\n"
        "                self._persistent_store.validate_loaded_blocks(\n"
        "                    metadata.load_cpu_blocks,\n"
        "                    metadata.load_block_hashes,\n"
        "                    self._persistent_known,\n"
        "                )\n"
        "        if metadata.store_event >= 0:\n"
        "            self._pending_store_event_indices.add(metadata.store_event)\n"
        "            if metadata.store_cpu_blocks:\n"
        "                self._pending_store_persist[metadata.store_event] = (\n"
        "                    list(metadata.store_cpu_blocks),\n"
        "                    list(metadata.store_block_hashes),\n"
        "                )\n",
        "worker bind persistent metadata",
    )
    text = _replace_once(
        text,
        "                self._pending_store_event_indices.discard(j)\n"
        "                self._completed_store_events[j] = 1\n",
        "                self._pending_store_event_indices.discard(j)\n"
        "                persist = self._pending_store_persist.pop(j, None)\n"
        "                if persist is not None and self._persistent_store is not None:\n"
        "                    assert self.cpu_kv_caches is not None\n"
        "                    cpu_ids, hashes = persist\n"
        "                    self._persistent_store.persist_worker_blocks(self.cpu_kv_caches, cpu_ids, hashes)\n"
        "                    for cpu_id, hash_hex in zip(cpu_ids, hashes):\n"
        "                        self._persistent_known[int(cpu_id)] = hash_hex\n"
        "                self._completed_store_events[j] = 1\n",
        "worker persist completed store",
    )
    _write_if_changed(path, text)


def _read_for_patch(path: Path) -> str:
    backup = path.with_suffix(path.suffix + ".ds4bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    return path.read_text()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"patch anchor not found for {label}")
    return text.replace(old, new, 1)


def _write_if_changed(path: Path, text: str) -> None:
    if path.read_text() != text:
        path.write_text(text)


if __name__ == "__main__":
    raise SystemExit(main())
