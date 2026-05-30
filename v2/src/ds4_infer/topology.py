from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from .pipelines import PipelineService, PipelineStage, load_pipeline_services
from .profiles import ModelProfile

TOPOLOGY_FORMAT = "ds4-spark-topology-v1"


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
        self.model_aliases = _load_model_aliases(self.routing_policy)
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
        nodes = [SparkNode.from_json(item) for item in data.get("nodes", [])]
        return SparkTopology(topology_id=str(data.get("topology_id", "unnamed")), nodes=nodes, routing_policy=data.get("routing_policy"))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "format": TOPOLOGY_FORMAT,
            "topology_id": self.topology_id,
            "nodes": [node.to_public_dict() for node in self.nodes],
            "pipeline_services": [service.to_public_dict() for service in self.pipeline_services.values()],
            "model_aliases": dict(self.model_aliases),
            "routing_policy": self.routing_policy,
        }

    def resolve_model_alias(self, model: str) -> str:
        seen: set[str] = set()
        current = str(model)
        while current in self.model_aliases:
            if current in seen:
                raise ValueError(f"model alias cycle includes {current!r}")
            seen.add(current)
            current = self.model_aliases[current]
        return current

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


def _load_model_aliases(routing_policy: dict[str, Any]) -> dict[str, str]:
    raw = routing_policy.get("model_aliases", {})
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("routing_policy.model_aliases must be an object")
    aliases: dict[str, str] = {}
    for alias, target in raw.items():
        alias_text = str(alias).strip()
        target_text = str(target).strip()
        if not alias_text or not target_text:
            raise ValueError("routing_policy.model_aliases cannot contain empty alias or target")
        aliases[alias_text] = target_text
    return aliases
