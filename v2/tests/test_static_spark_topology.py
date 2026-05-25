from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.service import run_requests
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


def make_request(request_id: str, *, capability: str, job_class: str, chat: bool = False, immediate: bool = False) -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": capability,
            "chat": chat,
            "immediate": immediate,
            "job_class": job_class,
            "max_output_tokens": 128,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": {"target_atom_id": f"atom:{request_id}", "source_atom_hash": "h"},
            "output_contract": {"format": "centaur-atom-edit-v1", "strict_json": True},
        }
    )


class StaticSparkTopologyTests(unittest.TestCase):
    def test_capacity_reflects_static_allocation(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()
        self.assertEqual(capacity["qwen3_6_27b_fp8_efficient_v1"], 4)
        self.assertEqual(capacity["qwen3_6_35b_a3b_fp8_fastest_v1"], 4)
        self.assertEqual(capacity["dsv4_vllm_mtp_smartest_v1"], 1)
        self.assertEqual(capacity["dsv4_antirez_smart_v1"], 1)

    def test_qwen_requests_spread_across_qwen_lanes_only(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="efficient", chat=False, job_class="atom_edit")
        load: dict[str, int] = {}
        nodes: list[str] = []
        for _ in range(4):
            assignment = topology.assign_profile(profile, immediate=False, current_load=load)
            load[assignment.node_id] = load.get(assignment.node_id, 0) + 1
            nodes.append(assignment.node_id)
        self.assertEqual(sorted(nodes), ["spark0", "spark1", "spark2", "spark3"])

    def test_immediate_efficient_request_stays_on_qwen_lanes(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="efficient", chat=False, job_class="atom_edit")
        assignment = topology.assign_profile(profile, immediate=True, current_load={})
        self.assertIn(assignment.node_id, {"spark0", "spark1", "spark2", "spark3"})
        self.assertEqual(assignment.reason, "resident_profile")

    def test_vllm_chat_routes_to_dsv4_static_lanes(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="smartest", chat=True, job_class="tool_chat")
        assignment = topology.assign_profile(profile, immediate=False, current_load={})
        self.assertEqual(assignment.node_id, "spark5")
        self.assertEqual(assignment.node_ids, ("spark4", "spark5"))
        self.assertEqual(assignment.reason, "resident_profile_group")

    def test_run_manifest_records_topology_assignments(self) -> None:
        requests = [
            make_request("r0", capability="efficient", job_class="atom_edit"),
            make_request("r1", capability="smartest", job_class="tool_chat", chat=True),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            manifest = run_requests(
                requests=requests,
                registry=ProfileRegistry.load(PROFILES),
                runner=FakeRunner(),
                out_dir=tmp,
                topology=SparkTopology.load(TOPOLOGY),
            )
            self.assertEqual(manifest["topology_id"], "static_sparks_2026_05_25_v3")
            self.assertEqual(manifest["selected_nodes"]["spark0"], 1)
            self.assertEqual(manifest["selected_nodes"]["spark5"], 1)
            responses = [json.loads(line) for line in (Path(tmp) / "responses.jsonl").read_text().splitlines()]
            self.assertEqual(responses[0]["selected_node"]["node_id"], "spark0")
            self.assertEqual(responses[1]["selected_node"]["node_id"], "spark5")
            self.assertEqual(responses[1]["selected_node"]["node_ids"], ["spark4", "spark5"])

    def test_immediate_smart_request_uses_antirez_support_lane(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="smart", chat=False, job_class="atom_edit")
        assignment = topology.assign_profile(profile, immediate=True, current_load={})
        self.assertEqual(assignment.node_id, "spark6")
        self.assertEqual(assignment.reason, "resident_profile_immediate")


if __name__ == "__main__":
    unittest.main()
