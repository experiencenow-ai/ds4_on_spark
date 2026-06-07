from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
from typing import Any

from .state_package import HmaPersistentStore, HmaStatePackage, token_hash

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised only inside a real vLLM runtime.
    from vllm.distributed.kv_transfer.kv_connector.v1.base import KVConnectorBase_V1, SupportsHMA, KVConnectorMetadata
    from vllm.distributed.kv_transfer.kv_connector.v1.base import KVConnectorRole
except Exception:  # pragma: no cover - local unit tests use the shim.
    class KVConnectorMetadata:  # type: ignore[no-redef]
        pass

    class SupportsHMA:  # type: ignore[no-redef]
        pass

    class KVConnectorRole:  # type: ignore[no-redef]
        SCHEDULER = "scheduler"
        WORKER = "worker"

    class KVConnectorBase_V1:  # type: ignore[no-redef]
        def __init__(self, vllm_config: Any, role: Any, kv_cache_config: Any) -> None:
            self._vllm_config = vllm_config
            self._role = role
            self._kv_cache_config = kv_cache_config
            self._kv_transfer_config = getattr(vllm_config, "kv_transfer_config", None)
            self._connector_metadata = None

        def _get_connector_metadata(self) -> Any:
            return self._connector_metadata


@dataclass
class Dsv4HmaRequestMeta:
    request_id: str
    token_ids: list[int]
    block_ids_by_group: tuple[list[int], ...] = ()
    is_store: bool = False
    package_id: str | None = None


@dataclass
class Dsv4HmaConnectorMetadata(KVConnectorMetadata):
    requests: list[Dsv4HmaRequestMeta] = field(default_factory=list)


class DS4HmaPersistentConnector(KVConnectorBase_V1, SupportsHMA):
    """
    Dynamic vLLM connector shell for DSV4/HMA durable KV state.

    This connector intentionally fails closed unless a live vLLM build provides the
    DSV4-specific state extractor/injector hooks. The generic LMCache/standard-KV
    path is not sufficient for DSV4 because the durable package must include the
    model-specific compressed latent/MLA state, sliding-window groups, indexer state,
    compressor state, and the HMA group block mapping.
    """

    @property
    def prefer_cross_layer_blocks(self) -> bool:
        return True

    def __init__(self, vllm_config: Any, role: Any, kv_cache_config: Any) -> None:
        super().__init__(vllm_config=vllm_config, role=role, kv_cache_config=kv_cache_config)
        extra = _extra_config(getattr(self, "_kv_transfer_config", None))
        root = extra.get("ds4_hma_store_root") or os.environ.get("DS4_HMA_STORE_ROOT") or "/tmp/ds4_hma_store"
        self.store = HmaPersistentStore(root)
        self.tokenizer_hash = str(extra.get("ds4_hma_tokenizer_hash") or os.environ.get("DS4_HMA_TOKENIZER_HASH") or "unknown-tokenizer")
        self.hma_layout = str(extra.get("ds4_hma_layout") or "dsv4_hma_mla_sliding_indexer_compressor_v1")
        self.layer_partition_fingerprint = str(extra.get("ds4_hma_layer_partition_fingerprint") or os.environ.get("DS4_HMA_LAYER_PARTITION_FINGERPRINT") or "")
        self.hard_fail = str(extra.get("ds4_hma_hard_fail", "True")).lower() in {"1", "true", "yes", "on"}
        self.required_parts = tuple(str(item) for item in extra.get("ds4_hma_required_parts", []))
        self._requests_need_load: dict[str, Dsv4HmaRequestMeta] = {}
        self._requests_need_store: dict[str, Dsv4HmaRequestMeta] = {}
        self._async_finished: set[str] = set()
        self._load_errors: set[int] = set()
        logger.warning("DS4HmaPersistentConnector is experimental and fail-closed until DSV4/HMA extractor hooks are live-tested.")

    def register_kv_caches(self, kv_caches: dict[str, Any]) -> None:
        self._kv_caches = kv_caches

    def register_cross_layers_kv_cache(self, kv_caches: dict[str, Any]) -> None:
        self._cross_layer_kv_caches = kv_caches

    def build_connector_meta(self, scheduler_output: Any) -> Dsv4HmaConnectorMetadata:
        metadata = Dsv4HmaConnectorMetadata()
        metadata.requests.extend(self._requests_need_load.values())
        metadata.requests.extend(self._requests_need_store.values())
        return metadata

    def build_connector_worker_meta(self, scheduler_output: Any) -> Dsv4HmaConnectorMetadata:
        return self.build_connector_meta(scheduler_output)

    def get_num_new_matched_tokens(self, request: Any, num_computed_tokens: int) -> tuple[int | None, bool]:
        token_ids = _request_token_ids(request)
        if not token_ids:
            return 0, False
        try:
            package = self.store.lookup_by_token_ids(token_ids, layer_partition_fingerprint=self.layer_partition_fingerprint or None)
        except Exception as exc:
            self._fail_or_log(f"failed to load DSV4/HMA package metadata: {exc}")
            return 0, False
        if package is None:
            return 0, False
        request_id = _request_id(request)
        meta = Dsv4HmaRequestMeta(request_id=request_id, token_ids=list(token_ids), is_store=False, package_id=package.package_id)
        self._requests_need_load[request_id] = meta
        return max(0, package.token_count - num_computed_tokens), False

    def update_state_after_alloc(self, request: Any, blocks: Any, num_external_tokens: int) -> None:
        if num_external_tokens <= 0:
            return None
        request_id = _request_id(request)
        meta = self._requests_need_load.get(request_id)
        if meta is None:
            return None
        self._requests_need_load[request_id] = Dsv4HmaRequestMeta(
            request_id=meta.request_id,
            token_ids=meta.token_ids,
            block_ids_by_group=_block_ids_by_group(blocks),
            is_store=False,
            package_id=meta.package_id,
        )
        return None

    def start_load_kv(self, forward_context: Any, **kwargs: Any) -> None:
        metadata = getattr(self, "_connector_metadata", None) or self._get_connector_metadata()
        if not isinstance(metadata, Dsv4HmaConnectorMetadata):
            return None
        for request in metadata.requests:
            if request.is_store:
                continue
            if request.package_id is None:
                continue
            path = self.store.package_path(request.package_id)
            if not path.exists():
                self._record_load_error(request)
                self._fail_or_log(f"missing DSV4/HMA package {request.package_id}")
                continue
            # Live vLLM patch point: load package and inject each DSV4/HMA state part.
            # We do not fall back to generic KV tensor injection because that would
            # silently drop compressor/indexer/sliding-window state.
            self._fail_or_log("DSV4/HMA load hook is not wired into this vLLM build")
        return None

    def wait_for_layer_load(self, layer_name: str) -> None:
        return None

    def save_kv_layer(self, layer_name: str, kv_layer: Any, attn_metadata: Any, **kwargs: Any) -> None:
        # Live vLLM patch point. DSV4/HMA persistence must save more than this
        # layer tensor: it must also save HMA group placement and DSV4-specific
        # compressed/sliding/indexer/compressor state. The request_finished_all_groups
        # hook records the group map; the extractor hook must supply the state parts.
        return None

    def wait_for_save(self) -> None:
        return None

    def request_finished(self, request: Any, block_ids: list[int]) -> tuple[bool, dict[str, Any] | None]:
        return self.request_finished_all_groups(request, (list(block_ids),))

    def request_finished_all_groups(self, request: Any, block_ids: tuple[list[int], ...]) -> tuple[bool, dict[str, Any] | None]:
        token_ids = _request_token_ids(request)
        request_id = _request_id(request)
        package_id = f"hma_{token_hash(token_ids)[:24]}" if token_ids else f"hma_request_{request_id}"
        self._requests_need_store[request_id] = Dsv4HmaRequestMeta(
            request_id=request_id,
            token_ids=list(token_ids),
            block_ids_by_group=tuple(list(group) for group in block_ids),
            is_store=True,
            package_id=package_id,
        )
        params = {
            "ds4_hma_package_id": package_id,
            "ds4_hma_store_root": str(self.store.root),
            "ds4_hma_layout": self.hma_layout,
            "ds4_hma_layer_partition_fingerprint": self.layer_partition_fingerprint,
            "ds4_hma_state": "pending_extractor_hook",
        }
        # Return False until the live extractor actually holds blocks and writes asynchronously.
        return False, params

    def get_finished(self, finished_req_ids: set[str]) -> tuple[set[str] | None, set[str] | None]:
        finished = self._async_finished.intersection(finished_req_ids)
        self._async_finished.difference_update(finished)
        return (finished or None), None

    def get_block_ids_with_load_errors(self) -> set[int]:
        return set(self._load_errors)

    def shutdown(self) -> None:
        return None

    def _record_load_error(self, request: Dsv4HmaRequestMeta) -> None:
        for group in request.block_ids_by_group:
            self._load_errors.update(int(block_id) for block_id in group)

    def _fail_or_log(self, message: str) -> None:
        if self.hard_fail:
            raise RuntimeError(message)
        logger.error(message)


def _extra_config(kv_transfer_config: Any) -> dict[str, Any]:
    if kv_transfer_config is None:
        return {}
    getter = getattr(kv_transfer_config, "get_from_extra_config", None)
    if callable(getter):
        keys = [
            "ds4_hma_store_root",
            "ds4_hma_tokenizer_hash",
            "ds4_hma_layout",
            "ds4_hma_layer_partition_fingerprint",
            "ds4_hma_hard_fail",
            "ds4_hma_required_parts",
        ]
        out: dict[str, Any] = {}
        for key in keys:
            item = getter(key, None)
            if item is not None:
                out[key] = item
        return out
    value = getattr(kv_transfer_config, "kv_connector_extra_config", None)
    if isinstance(value, dict):
        return dict(value)
    if isinstance(kv_transfer_config, dict):
        return dict(kv_transfer_config.get("kv_connector_extra_config", {}))
    return {}


def _request_token_ids(request: Any) -> tuple[int, ...]:
    token_ids = getattr(request, "prompt_token_ids", None) or getattr(request, "token_ids", None) or []
    return tuple(int(token) for token in token_ids)


def _request_id(request: Any) -> str:
    return str(getattr(request, "request_id", None) or getattr(request, "id", None) or "unknown_request")


def _block_ids_by_group(blocks: Any) -> tuple[list[int], ...]:
    if blocks is None:
        return ()
    if isinstance(blocks, tuple):
        return tuple(_one_block_group(group) for group in blocks)
    if isinstance(blocks, list):
        if blocks and all(isinstance(item, list) for item in blocks):
            return tuple(_one_block_group(group) for group in blocks)
        return (_one_block_group(blocks),)
    for attr in ("block_ids", "blocks", "ids"):
        value = getattr(blocks, attr, None)
        if value is not None:
            return _block_ids_by_group(value)
    return ()


def _one_block_group(value: Any) -> list[int]:
    if isinstance(value, list):
        return [int(item) for item in value]
    if isinstance(value, tuple):
        return [int(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return [int(item) for item in tolist()]
    return [int(value)]
