from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

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

    def to_public_dict(self) -> dict[str, Any]:
        node_ids = self.node_ids or (self.node_id,)
        return {
            "profile_id": self.profile_id,
            "node_id": self.node_id,
            "node_ids": list(node_ids),
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
            "routing_policy": self.routing_policy,
        }

    def nodes_for_profile(self, profile: ModelProfile) -> list[SparkNode]:
        return [node for node in self.nodes if node.supports_profile(profile.profile_id)]

    def assign_profile(self, profile: ModelProfile, *, immediate: bool, current_load: dict[str, int] | None = None) -> SparkAssignment:
        current_load = current_load or {}
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
        grouped_profiles = set(self.profile_node_groups)
        for profile_id, node_ids in self.profile_node_groups.items():
            capacity[profile_id] = min(self._by_id[node_id].default_capacity for node_id in node_ids)
        for node in self.nodes:
            for profile_id in node.resident_profiles:
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
