from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

from .pipelines import (
    PipelineService,
    PipelineStage,
    even_layer_partition,
    layer_partition_by_node,
    layer_partition_from_preset,
    load_pipeline_services,
)
from .profiles import ModelProfile

TOPOLOGY_FORMAT = "ds4-spark-topology-v1"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class SparkNode:
    node_id: str
    roles: tuple[str, ...]
    resident_profiles: tuple[str, ...]
    default_capacity: int
    immediate_reserved: bool
    dynamic_load: bool

    @staticmethod
    def from_json(data: dict[str, Any]) -> "SparkNode":
        required = ["node_id", "roles", "resident_profiles", "default_capacity", "immediate_reserved", "dynamic_load"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"spark node missing fields: {missing}")
        capacity = int(data["default_capacity"])
        if capacity < 1:
            raise ValueError("spark node default_capacity must be positive")
        return SparkNode(
            node_id=str(data["node_id"]),
            roles=tuple(str(role) for role in data["roles"]),
            resident_profiles=tuple(str(profile_id) for profile_id in data["resident_profiles"]),
            default_capacity=capacity,
            immediate_reserved=bool(data["immediate_reserved"]),
            dynamic_load=bool(data["dynamic_load"]),
        )

    def supports_profile(self, profile_id: str) -> bool:
        return profile_id in self.resident_profiles

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "roles": list(self.roles),
            "resident_profiles": list(self.resident_profiles),
            "default_capacity": self.default_capacity,
            "immediate_reserved": self.immediate_reserved,
            "dynamic_load": self.dynamic_load,
        }


@dataclass(frozen=True)
class SparkAssignment:
    profile_id: str
    node_id: str
    resident: bool
    dynamic_load: bool
    reason: str
    node_ids: tuple[str, ...] = ()
    service_id: str | None = None
    api_base_url: str | None = None
    compute_domain: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        node_ids = self.node_ids or (self.node_id,)
        return {
            "profile_id": self.profile_id,
            "node_id": self.node_id,
            "node_ids": list(node_ids),
            "service_id": self.service_id,
            "api_base_url": self.api_base_url,
            "compute_domain": self.compute_domain,
            "resident": self.resident,
            "dynamic_load": self.dynamic_load,
            "reason": self.reason,
        }


class SparkTopology:
    def __init__(self, *, topology_id: str, nodes: list[SparkNode], routing_policy: dict[str, Any] | None = None) -> None:
        if not nodes:
            raise ValueError("spark topology requires at least one node")
        self.topology_id = topology_id
        self.nodes = list(nodes)
        self.routing_policy = dict(routing_policy or {})
        self._by_id = {node.node_id: node for node in self.nodes}
        if len(self._by_id) != len(self.nodes):
            raise ValueError("duplicate node_id in spark topology")
        self.pipeline_services = load_pipeline_services(self.routing_policy, known_node_ids=set(self._by_id))
        self.profile_pipeline_services = {service.profile_id: service for service in self.pipeline_services.values()}
        self.profile_node_groups = _load_profile_node_groups(self.routing_policy, self._by_id)
        self.profile_group_ingress = _load_profile_group_ingress(self.routing_policy, self.profile_node_groups)

    @staticmethod
    def load(path: str | Path) -> "SparkTopology":
        with Path(path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("format") != TOPOLOGY_FORMAT:
            raise ValueError(f"unsupported topology format: {data.get('format')!r}")
        data = _apply_pipeline_node_override(data)
        nodes = [SparkNode.from_json(item) for item in data.get("nodes", [])]
        return SparkTopology(topology_id=str(data.get("topology_id", "unnamed")), nodes=nodes, routing_policy=data.get("routing_policy"))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "format": TOPOLOGY_FORMAT,
            "topology_id": self.topology_id,
            "nodes": [node.to_public_dict() for node in self.nodes],
            "pipeline_services": [service.to_public_dict() for service in self.pipeline_services.values()],
            "routing_policy": self.routing_policy,
        }

    def nodes_for_profile(self, profile: ModelProfile) -> list[SparkNode]:
        return [node for node in self.nodes if node.supports_profile(profile.profile_id)]

    def pipeline_service_for_profile(self, profile_id: str) -> PipelineService | None:
        return self.profile_pipeline_services.get(profile_id)

    def pipeline_service_by_id(self, service_id: str) -> PipelineService:
        try:
            return self.pipeline_services[service_id]
        except KeyError as exc:
            raise ValueError(f"unknown pipeline service: {service_id}") from exc

    @property
    def pipeline_profiles(self) -> dict[str, PipelineService]:
        return dict(self.profile_pipeline_services)

    def pipeline_profiles_for_node(self, node_id: str) -> tuple[PipelineService, ...]:
        if node_id not in self._by_id:
            raise ValueError(f"unknown spark node: {node_id}")
        return tuple(service for service in self.pipeline_services.values() if service.entry_node_id == node_id)

    def pipeline_stages_for_node(self, node_id: str) -> tuple[PipelineStage, ...]:
        if node_id not in self._by_id:
            raise ValueError(f"unknown spark node: {node_id}")
        stages = []
        for service in self.pipeline_services.values():
            if node_id in service.node_ids:
                stages.append(service.stage_for_node(node_id))
        return tuple(stages)

    def assign_profile(self, profile: ModelProfile, *, immediate: bool, current_load: dict[str, int] | None = None) -> SparkAssignment:
        current_load = current_load or {}
        service = self.pipeline_service_for_profile(profile.profile_id)
        if service is not None:
            return SparkAssignment(
                profile_id=profile.profile_id,
                node_id=service.entry_node_id,
                resident=True,
                dynamic_load=False,
                reason="pipeline_service",
                node_ids=service.node_ids,
                service_id=service.service_id,
                api_base_url=service.api_base_url,
                compute_domain=service.compute_domain,
            )
        grouped_node_ids = self.profile_node_groups.get(profile.profile_id)
        if grouped_node_ids:
            ingress = self.profile_group_ingress.get(profile.profile_id, "+".join(grouped_node_ids))
            return SparkAssignment(
                profile_id=profile.profile_id,
                node_id=ingress,
                resident=True,
                dynamic_load=False,
                reason="resident_profile_group",
                node_ids=grouped_node_ids,
            )
        eligible = self.nodes_for_profile(profile)
        if eligible:
            chosen = self._choose_resident_node(eligible, immediate=immediate, current_load=current_load)
            return SparkAssignment(
                profile_id=profile.profile_id,
                node_id=chosen.node_id,
                resident=True,
                dynamic_load=False,
                reason="resident_profile_immediate" if immediate and chosen.immediate_reserved else "resident_profile",
                node_ids=(chosen.node_id,),
            )
        if bool(self.routing_policy.get("allow_dynamic_load_for_unmatched_profiles", False)):
            experiment = self._experimental_node()
            if experiment is not None:
                return SparkAssignment(
                    profile_id=profile.profile_id,
                    node_id=experiment.node_id,
                    resident=False,
                    dynamic_load=True,
                    reason="dynamic_load_experiment_lane",
                    node_ids=(experiment.node_id,),
                )
        raise ValueError(f"no spark node has resident profile {profile.profile_id!r}")

    def estimate_capacity_by_profile(self) -> dict[str, int]:
        capacity: dict[str, int] = {}
        for service in self.pipeline_services.values():
            capacity[service.profile_id] = service.max_batch_size
        grouped_profiles = set(self.profile_node_groups) - set(capacity)
        for profile_id, node_ids in self.profile_node_groups.items():
            if profile_id in grouped_profiles:
                capacity[profile_id] = min(self._by_id[node_id].default_capacity for node_id in node_ids)
        for node in self.nodes:
            for profile_id in node.resident_profiles:
                if profile_id not in grouped_profiles and profile_id in capacity:
                    continue
                if profile_id not in grouped_profiles:
                    capacity[profile_id] = capacity.get(profile_id, 0) + node.default_capacity
        return dict(sorted(capacity.items()))

    def _choose_resident_node(self, candidates: Iterable[SparkNode], *, immediate: bool, current_load: dict[str, int]) -> SparkNode:
        nodes = list(candidates)
        if immediate:
            reserved = [node for node in nodes if node.immediate_reserved]
            if reserved:
                nodes = reserved
        else:
            production = [node for node in nodes if "production" in node.roles]
            production_with_room = [node for node in production if current_load.get(node.node_id, 0) < node.default_capacity]
            if production_with_room:
                nodes = production_with_room
        return sorted(nodes, key=lambda node: (current_load.get(node.node_id, 0) / node.default_capacity, node.node_id))[0]

    def _experimental_node(self) -> SparkNode | None:
        node_id = self.routing_policy.get("experimental_node_id")
        if node_id:
            node = self._by_id.get(str(node_id))
            if node is not None:
                return node
        dynamic_nodes = [node for node in self.nodes if node.dynamic_load]
        return sorted(dynamic_nodes, key=lambda node: node.node_id)[0] if dynamic_nodes else None


def _load_profile_node_groups(routing_policy: dict[str, Any], nodes_by_id: dict[str, SparkNode]) -> dict[str, tuple[str, ...]]:
    raw_groups = routing_policy.get("profile_node_groups", {})
    if not isinstance(raw_groups, dict):
        raise ValueError("routing_policy.profile_node_groups must be an object")
    groups: dict[str, tuple[str, ...]] = {}
    for profile_id, raw_node_ids in raw_groups.items():
        if not isinstance(raw_node_ids, list) or not raw_node_ids:
            raise ValueError("profile node group must be a non-empty list")
        node_ids = tuple(str(node_id) for node_id in raw_node_ids)
        missing = [node_id for node_id in node_ids if node_id not in nodes_by_id]
        if missing:
            raise ValueError(f"profile node group {profile_id!r} references unknown nodes: {missing}")
        for node_id in node_ids:
            if str(profile_id) not in nodes_by_id[node_id].resident_profiles:
                raise ValueError(f"profile node group {profile_id!r} references node {node_id!r} that does not list the profile")
        groups[str(profile_id)] = node_ids
    return groups


def pipeline_service_client_base_url(service: PipelineService) -> str:
    raw = service.api_base_url.rstrip("/")
    if not _resolve_loopback_entry_node_enabled():
        return raw
    parsed = urlparse(raw)
    if parsed.hostname not in LOOPBACK_HOSTS:
        return raw
    host = _entry_node_client_host(service.entry_node_id)
    if not host:
        return raw
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth = f"{auth}:{parsed.password}"
        netloc = f"{auth}@{netloc}"
    return urlunparse(parsed._replace(netloc=netloc)).rstrip("/")


def _resolve_loopback_entry_node_enabled() -> bool:
    raw = os.environ.get("DS4_PIPELINE_RESOLVE_LOOPBACK_ENTRY_NODE", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _entry_node_client_host(entry_node_id: str) -> str:
    return os.environ.get("DS4_PIPELINE_ENTRY_HOST_TEMPLATE", "{node}").replace("{node}", entry_node_id).strip()


def _load_profile_group_ingress(routing_policy: dict[str, Any], groups: dict[str, tuple[str, ...]]) -> dict[str, str]:
    raw = routing_policy.get("profile_node_group_ingress", {})
    if not isinstance(raw, dict):
        raise ValueError("routing_policy.profile_node_group_ingress must be an object")
    out: dict[str, str] = {}
    for profile_id, ingress in raw.items():
        profile_key = str(profile_id)
        node_id = str(ingress)
        if profile_key not in groups:
            raise ValueError(f"profile node group ingress references unknown profile group: {profile_key!r}")
        if node_id not in groups[profile_key]:
            raise ValueError(f"profile node group ingress {node_id!r} is not in group {profile_key!r}")
        out[profile_key] = node_id
    return out


def _apply_pipeline_node_override(data: dict[str, Any]) -> dict[str, Any]:
    raw_nodes = os.environ.get("DS4_PIPELINE_NODES", "")
    node_ids = tuple(item.strip() for item in raw_nodes.split(",") if item.strip())
    if not node_ids:
        return data
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("DS4_PIPELINE_NODES contains duplicate node ids")
    rewritten = json.loads(json.dumps(data))
    known = {str(item.get("node_id")) for item in rewritten.get("nodes", []) if isinstance(item, dict)}
    missing = [node_id for node_id in node_ids if node_id not in known]
    if missing:
        raise ValueError(f"DS4_PIPELINE_NODES references unknown nodes: {missing}")
    rewritten["nodes"] = [item for item in rewritten.get("nodes", []) if str(item.get("node_id")) in node_ids]
    routing = dict(rewritten.get("routing_policy", {}))
    services = routing.get("pipeline_services", {})
    if isinstance(services, dict):
        for service_id, service in services.items():
            if not isinstance(service, dict):
                continue
            total_layers = int(service.get("total_layers", 0))
            if total_layers < 1:
                continue
            service["node_ids"] = list(node_ids)
            service["entry_node_id"] = node_ids[0]
            service["pipeline_parallel_size"] = len(node_ids)
            service["layer_partition"] = list(_partition_for_service(str(service_id), service, len(node_ids), total_layers))
            if isinstance(service.get("kv_cache"), dict):
                service["kv_cache"]["expected_entry_fraction_per_node"] = 1.0 / len(node_ids)
            if isinstance(service.get("telemetry"), dict):
                service["telemetry"]["expected_stage_count"] = len(node_ids)
    routing["queue_entry_node_id"] = node_ids[0]
    trim_defaults = routing.get("trim_default_profiles_by_node")
    if isinstance(trim_defaults, dict):
        routing["trim_default_profiles_by_node"] = {node_id: trim_defaults[node_id] for node_id in node_ids if node_id in trim_defaults}
    rewritten["routing_policy"] = routing
    rewritten["topology_id"] = str(rewritten.get("topology_id", "static_sparks")) + f"_n{len(node_ids)}"
    return rewritten


def _partition_for_service(service_id: str, service: dict[str, Any], stage_count: int, total_layers: int) -> tuple[int, ...]:
    if stage_count > total_layers:
        raise ValueError(f"service {service_id} has more pipeline stages than layers")
    node_ids = tuple(str(item) for item in service.get("node_ids", ()))
    by_node_partition = layer_partition_by_node(service.get("layer_partition_by_node"), node_ids=node_ids, label=f"service {service_id} layer_partition_by_node")
    if by_node_partition is not None:
        return by_node_partition
    raw = service.get("layer_partition")
    if isinstance(raw, list) and len(raw) == stage_count:
        return tuple(int(item) for item in raw)
    if isinstance(raw, str):
        partition, _source = layer_partition_from_preset(raw, total_layers=total_layers, stage_count=stage_count)
        return partition
    return even_layer_partition(total_layers, stage_count)
