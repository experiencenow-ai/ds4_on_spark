from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue, request_batch_key
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


def make_request(request_id: str, *, capability: str = "efficient", immediate: bool = False, output_tokens: int = 128) -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": capability,
            "chat": False,
            "immediate": immediate,
            "job_class": "atom_edit",
            "max_output_tokens": output_tokens,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": {
                "shared_prefix_hash": "prefix-a",
                "target_atom_id": f"atom:{request_id}",
                "source_atom_hash": "h",
                "suffix": "def f():\n    return 1\n",
            },
            "output_contract": {"format": "centaur-atom-edit-v1", "strict_json": True},
        }
    )


class InferenceQueueTests(unittest.TestCase):
    def test_submit_records_individual_request_status_and_batch_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            result = queue.submit_requests(
                requests=[make_request("r0"), make_request("r1")],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            self.assertEqual(result["request_count"], 2)
            self.assertEqual(result["selected_nodes"], {"spark0": 1, "spark1": 1})
            self.assertEqual(queue.status(batch_id="batch-a")["queued_count"], 2)
            self.assertEqual(queue.status(request_id="r0")["state"], "queued")
            self.assertEqual(queue.status(request_id="r0")["selected_node_id"], "spark0")

    def test_worker_completes_only_the_requested_node_and_writes_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request("r0"), make_request("r1")],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            worked = queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", limit=10)
            self.assertEqual(worked["claimed_count"], 1)
            self.assertEqual(worked["completed_count"], 1)
            self.assertEqual(queue.status(request_id="r0")["state"], "completed")
            self.assertEqual(queue.status(request_id="r1")["state"], "queued")
            notice = json.loads((Path(tmp) / "notices" / "r0.json").read_text())
            self.assertEqual(notice["state"], "completed")
            self.assertIn("centaur-atom-edit-v1", notice["result"]["output"]["text"])

    def test_poll_returns_completion_events_after_last_seen_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request("r0")],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            first_poll = queue.poll()
            self.assertEqual([event["event_type"] for event in first_poll["events"]], ["submitted"])
            queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), limit=1)
            second_poll = queue.poll(after_event_id=first_poll["newest_event_id"])
            self.assertEqual([event["event_type"] for event in second_poll["events"]], ["started", "completed"])

    def test_batch_key_separates_output_size_and_prefix(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        small = make_request("small", output_tokens=128)
        large = make_request("large", output_tokens=2048)
        profile = registry.resolve(capability="efficient", chat=False, job_class="atom_edit")
        small_key = request_batch_key(small, profile, topology.assign_profile(profile, immediate=False, current_load={}))
        large_key = request_batch_key(large, profile, topology.assign_profile(profile, immediate=False, current_load={}))
        self.assertNotEqual(small_key, large_key)
        self.assertIn("out_0_256", small_key)
        self.assertIn("out_769_2048", large_key)


if __name__ == "__main__":
    unittest.main()
