from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Mapping

PIPELINE_SERVICE_FORMAT = "ds4-pipeline-service-v1"


@dataclass(frozen=True)
class PipelineStage:
    service_id: str
    profile_id: str
    stage_index: int
    stage_count: int
    node_id: str
    layer_start: int
    layer_end: int

    @property
    def layer_count(self) -> int:
        return self.layer_end - self.layer_start

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "profile_id": self.profile_id,
            "stage_index": self.stage_index,
            "stage_count": self.stage_count,
            "node_id": self.node_id,
            "layer_start": self.layer_start,
            "layer_end": self.layer_end,
            "layer_count": self.layer_count,
        }


@dataclass(frozen=True)
class PipelineService:
    service_id: str
    profile_id: str
    model_id: str
    entry_node_id: str
    node_ids: tuple[str, ...]
    api_base_url: str
    compute_domain: str
    pipeline_parallel_size: int
    tensor_parallel_size: int
    total_layers: int
    layer_partition: tuple[int, ...]
    layer_partition_source: str
    dtype: str
    max_batch_size: int
    kv_cache: dict[str, Any]
    scheduler: dict[str, Any]
    telemetry: dict[str, Any]

    @staticmethod
    def from_json(data: dict[str, Any], *, known_node_ids: set[str]) -> "PipelineService":
        required = ["service_id", "profile_id", "model_id", "entry_node_id", "node_ids", "api_base_url", "total_layers"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"pipeline service missing fields: {missing}")
        node_ids = tuple(str(node_id) for node_id in data["node_ids"])
        if not node_ids:
            raise ValueError("pipeline service node_ids must be non-empty")
        unknown = [node_id for node_id in node_ids if node_id not in known_node_ids]
        if unknown:
            raise ValueError(f"pipeline service references unknown nodes: {unknown}")
        entry_node_id = str(data["entry_node_id"])
        if entry_node_id not in node_ids:
            raise ValueError("pipeline service entry_node_id must be one of node_ids")
        pipeline_parallel_size = int(data.get("pipeline_parallel_size", len(node_ids)))
        if pipeline_parallel_size != len(node_ids):
            raise ValueError("pipeline_parallel_size must match node_ids length")
        tensor_parallel_size = int(data.get("tensor_parallel_size", 1))
        total_layers = int(data["total_layers"])
        if tensor_parallel_size < 1 or pipeline_parallel_size < 1 or total_layers < 1:
            raise ValueError("pipeline, tensor, and layer counts must be positive")
        layer_partition, source = load_layer_partition_with_source(
            data,
            node_ids=node_ids,
            total_layers=total_layers,
            stage_count=pipeline_parallel_size,
        )
        if len(layer_partition) != pipeline_parallel_size:
            raise ValueError("layer_partition length must match pipeline_parallel_size")
        if sum(layer_partition) != total_layers:
            raise ValueError("layer_partition must sum to total_layers")
        if any(count < 1 for count in layer_partition):
            raise ValueError("each pipeline stage must own at least one layer")
        max_batch_size = int(data.get("max_batch_size", data.get("max_num_seqs", 1)))
        if max_batch_size < 1:
            raise ValueError("pipeline service max_batch_size must be positive")
        service_id = str(data["service_id"])
        return PipelineService(
            service_id=service_id,
            profile_id=str(data["profile_id"]),
            model_id=str(data["model_id"]),
            entry_node_id=entry_node_id,
            node_ids=node_ids,
            api_base_url=str(data["api_base_url"]).rstrip("/"),
            compute_domain=str(data.get("compute_domain") or service_id),
            pipeline_parallel_size=pipeline_parallel_size,
            tensor_parallel_size=tensor_parallel_size,
            total_layers=total_layers,
            layer_partition=layer_partition,
            layer_partition_source=source,
            dtype=str(data.get("dtype", data.get("precision", "unknown"))),
            max_batch_size=max_batch_size,
            kv_cache=dict(data.get("kv_cache", {})),
            scheduler=dict(data.get("scheduler", {})),
            telemetry=dict(data.get("telemetry", {})),
        )

    @property
    def shard_count(self) -> int:
        return len(self.node_ids)

    def stage_for_node(self, node_id: str) -> PipelineStage:
        try:
            index = self.node_ids.index(node_id)
        except ValueError as exc:
            raise ValueError(f"node {node_id!r} is not in pipeline service {self.service_id!r}") from exc
        return self.stages()[index]

    def stage_for_index(self, stage_index: int) -> PipelineStage:
        stages = self.stages()
        if stage_index < 0 or stage_index >= len(stages):
            raise ValueError(f"stage_index {stage_index} is outside service {self.service_id!r}")
        return stages[stage_index]

    def stages(self) -> tuple[PipelineStage, ...]:
        stages: list[PipelineStage] = []
        cursor = 0
        for index, (node_id, layer_count) in enumerate(zip(self.node_ids, self.layer_partition, strict=True)):
            stage = PipelineStage(
                service_id=self.service_id,
                profile_id=self.profile_id,
                stage_index=index,
                stage_count=self.pipeline_parallel_size,
                node_id=node_id,
                layer_start=cursor,
                layer_end=cursor + layer_count,
            )
            stages.append(stage)
            cursor += layer_count
        return tuple(stages)

    def estimate_kv_shard_bytes(self, total_bytes: int) -> int:
        if total_bytes <= 0:
            return 0
        mode = str(self.kv_cache.get("sharding", "pipeline_layers"))
        if mode == "replicated":
            return int(total_bytes)
        return int(ceil(int(total_bytes) / max(1, self.shard_count)))

    def cache_shards(self, *, request_id: str, kv_key: str, total_bytes: int) -> list[dict[str, Any]]:
        if not kv_key or total_bytes <= 0:
            return []
        shard_bytes = self.estimate_kv_shard_bytes(total_bytes)
        return [
            {
                "profile_id": self.profile_id,
                "service_id": self.service_id,
                "node_id": stage.node_id,
                "stage_index": stage.stage_index,
                "stage_count": stage.stage_count,
                "kv_key": kv_key,
                "request_id": request_id,
                "bytes": shard_bytes,
                "layer_start": stage.layer_start,
                "layer_end": stage.layer_end,
            }
            for stage in self.stages()
        ]

    def external_cache_shards(self, *, namespace: str, kv_key: str, total_bytes: int, storage_root: str | None = None) -> list[dict[str, Any]]:
        if not kv_key:
            raise ValueError("kv_key is required")
        shard_bytes = self.estimate_kv_shard_bytes(total_bytes)
        safe_key = _safe_storage_component(kv_key)
        safe_namespace = _safe_storage_component(namespace or "default")
        shards: list[dict[str, Any]] = []
        for stage in self.stages():
            storage_uri = None
            if storage_root:
                root = _format_stage_path(storage_root.rstrip("/"), stage=stage)
                storage_uri = f"{root}/{safe_namespace}/{self.service_id}/{safe_key}/stage-{stage.stage_index:02d}"
            shards.append(
                {
                    "namespace": namespace or "default",
                    "kv_key": kv_key,
                    "profile_id": self.profile_id,
                    "service_id": self.service_id,
                    "node_id": stage.node_id,
                    "stage_index": stage.stage_index,
                    "stage_count": stage.stage_count,
                    "bytes": shard_bytes,
                    "layer_start": stage.layer_start,
                    "layer_end": stage.layer_end,
                    "storage_uri": storage_uri,
                }
            )
        return shards

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "format": PIPELINE_SERVICE_FORMAT,
            "service_id": self.service_id,
            "profile_id": self.profile_id,
            "model_id": self.model_id,
            "entry_node_id": self.entry_node_id,
            "node_ids": list(self.node_ids),
            "api_base_url": self.api_base_url,
            "compute_domain": self.compute_domain,
            "pipeline_parallel_size": self.pipeline_parallel_size,
            "tensor_parallel_size": self.tensor_parallel_size,
            "total_layers": self.total_layers,
            "layer_partition": list(self.layer_partition),
            "layer_partition_source": self.layer_partition_source,
            "dtype": self.dtype,
            "max_batch_size": self.max_batch_size,
            "kv_cache": self.kv_cache,
            "scheduler": self.scheduler,
            "telemetry": self.telemetry,
            "stages": [stage.to_public_dict() for stage in self.stages()],
        }


def load_pipeline_services(routing_policy: Mapping[str, Any], *, known_node_ids: set[str]) -> dict[str, PipelineService]:
    raw = routing_policy.get("pipeline_services", {})
    if raw in (None, {}):
        return {}
    items: list[dict[str, Any]]
    if isinstance(raw, dict):
        items = []
        for key, value in raw.items():
            if not isinstance(value, dict):
                raise ValueError("routing_policy.pipeline_services values must be objects")
            data = dict(value)
            data.setdefault("service_id", str(key))
            items.append(data)
    elif isinstance(raw, list):
        items = [dict(value) for value in raw]
    else:
        raise ValueError("routing_policy.pipeline_services must be an object or list")
    services: dict[str, PipelineService] = {}
    profile_seen: dict[str, str] = {}
    for item in items:
        service = PipelineService.from_json(item, known_node_ids=known_node_ids)
        if service.service_id in services:
            raise ValueError(f"duplicate pipeline service_id: {service.service_id}")
        previous = profile_seen.get(service.profile_id)
        if previous is not None:
            raise ValueError(f"profile {service.profile_id!r} is assigned to multiple pipeline services: {previous}, {service.service_id}")
        services[service.service_id] = service
        profile_seen[service.profile_id] = service.service_id
    return services


def _format_stage_path(template: str, *, stage: PipelineStage) -> str:
    return template.format(
        node_id=stage.node_id,
        service_id=stage.service_id,
        profile_id=stage.profile_id,
        stage_index=stage.stage_index,
        stage_count=stage.stage_count,
    )


def balanced_layer_partition(total_layers: int, stage_count: int, *, tail_extra_layer_equivalent: float = 0.0) -> tuple[int, ...]:
    if total_layers < 1:
        raise ValueError("total_layers must be positive")
    if stage_count < 1:
        raise ValueError("stage_count must be positive")
    if stage_count > total_layers:
        raise ValueError("stage_count cannot exceed total_layers")
    if stage_count == 1:
        return (total_layers,)
    best: tuple[float, float, float, tuple[int, ...]] | None = None
    max_tail = total_layers - (stage_count - 1)
    for tail_layers in range(1, max_tail + 1):
        remaining = total_layers - tail_layers
        if remaining < stage_count - 1:
            continue
        base, extra = divmod(remaining, stage_count - 1)
        prefix = tuple(base + 1 if index < extra else base for index in range(stage_count - 1))
        parts = prefix + (tail_layers,)
        costs = [float(count) for count in parts]
        costs[-1] += max(0.0, float(tail_extra_layer_equivalent))
        average = sum(costs) / stage_count
        score = (max(costs) / average, max(costs) - min(costs), abs(costs[-1] - average), parts)
        if best is None or score < best:
            best = score
    assert best is not None
    return best[3]


def qwen36_27b_bf16_layer_partition(stage_count: int) -> tuple[int, ...]:
    return balanced_layer_partition(64, stage_count, tail_extra_layer_equivalent=3.33)


def even_layer_partition(total_layers: int, stage_count: int) -> tuple[int, ...]:
    if stage_count < 1 or total_layers < 1 or stage_count > total_layers:
        raise ValueError("invalid layer/stage count")
    base, extra = divmod(total_layers, stage_count)
    return tuple(base + 1 if index < extra else base for index in range(stage_count))


def load_layer_partition_with_source(data: Mapping[str, Any], *, node_ids: tuple[str, ...], total_layers: int, stage_count: int) -> tuple[tuple[int, ...], str]:
    by_node = data.get("layer_partition_by_node")
    if by_node is not None:
        if not isinstance(by_node, Mapping):
            raise ValueError("layer_partition_by_node must be an object mapping node_id to layer count")
        missing = [node_id for node_id in node_ids if node_id not in by_node]
        extra = [str(node_id) for node_id in by_node if str(node_id) not in set(node_ids)]
        if missing:
            raise ValueError(f"layer_partition_by_node missing nodes: {missing}")
        if extra:
            raise ValueError(f"layer_partition_by_node references nodes outside node_ids: {extra}")
        return tuple(int(by_node[node_id]) for node_id in node_ids), "by_node"
    raw = data.get("layer_partition")
    if raw is None:
        return even_layer_partition(total_layers, stage_count), "even"
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in {"auto", "even", "layers/n", "layers_per_n"}:
            return even_layer_partition(total_layers, stage_count), "even"
        if key in {"qwen3.6-27b-bf16", "qwen36_27b_bf16", "qwen27_bf16"}:
            return qwen36_27b_bf16_layer_partition(stage_count), key
        raise ValueError(f"unknown layer_partition preset: {raw}")
    if not isinstance(raw, list):
        raise ValueError("layer_partition must be a list, object-by-node override, or known preset string")
    return tuple(int(item) for item in raw), "explicit"


def _load_layer_partition(data: Mapping[str, Any], *, total_layers: int, stage_count: int) -> tuple[int, ...]:
    nodes = tuple(str(item) for item in data.get("node_ids", [f"stage{index}" for index in range(stage_count)]))
    partition, _source = load_layer_partition_with_source(data, node_ids=nodes, total_layers=total_layers, stage_count=stage_count)
    return partition


def _safe_storage_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value))[:160] or "_"


PipelineProfile = PipelineService
