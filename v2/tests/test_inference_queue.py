from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue, request_batch_key
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest, make_result
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
                "shared_prefix": "repo skeleton\noutput contract\n",
                "shared_prefix_hash": "prefix-a",
                "skeleton_hash": "prefix-a",
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

    def test_cancel_queued_request_prevents_worker_claim_and_writes_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request("r0"), make_request("r1")],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            cancelled = queue.cancel(request_id="r0", reason="operator test")
            self.assertEqual(cancelled["state"], "cancelled")
            self.assertEqual(cancelled["cancelled_request_ids"], ["r0"])
            self.assertEqual(queue.status(request_id="r0")["state"], "cancelled")
            self.assertEqual(queue.status(batch_id="batch-a")["cancelled_count"], 1)
            self.assertEqual(queue.status(batch_id="batch-a")["queued_count"], 1)
            notice = json.loads((Path(tmp) / "notices" / "r0.json").read_text())
            self.assertEqual(notice["state"], "cancelled")
            self.assertEqual(notice["result"]["reason"], "operator test")

            worked = queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), limit=10)
            self.assertEqual(worked["claimed_count"], 1)
            self.assertEqual(queue.status(request_id="r1")["state"], "completed")
            self.assertEqual(queue.status(batch_id="batch-a")["state"], "completed_with_cancelled")

    def test_cancel_batch_only_cancels_queued_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request("r0"), make_request("r1")],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", limit=1)
            cancelled = queue.cancel(batch_id="batch-a", reason="stop remaining")
            self.assertEqual(cancelled["cancelled_request_ids"], ["r1"])
            self.assertEqual(cancelled["skipped_state_counts"], {"completed": 1})
            self.assertEqual(queue.status(request_id="r0")["state"], "completed")
            self.assertEqual(queue.status(request_id="r1")["state"], "cancelled")
            batch_status = queue.status(batch_id="batch-a")
            self.assertEqual(batch_status["state"], "completed_with_cancelled")
            self.assertEqual(batch_status["completed_count"], 1)
            self.assertEqual(batch_status["cancelled_count"], 1)

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

    def test_prefix_warm_groups_shared_prefix_on_same_lane(self) -> None:
        class WarmRunner:
            def __init__(self) -> None:
                self.calls: list[tuple[InferenceRequest, str | None]] = []

            def run_one_on_node(self, request: InferenceRequest, profile, node_id: str | None) -> dict:
                self.calls.append((request, node_id))
                return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text="warm")

        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            requests = [make_request(f"r{i}") for i in range(5)]
            queue.submit_requests(
                requests=requests,
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            runner = WarmRunner()
            report = queue.warm_prefixes(registry=ProfileRegistry.load(PROFILES), runner=runner, node_id="spark0", min_group_size=2)
            self.assertEqual(report["warmed_count"], 1)
            self.assertEqual(report["groups"][0]["node_id"], "spark0")
            self.assertEqual(report["groups"][0]["skeleton_hash"], "prefix-a")
            self.assertEqual(runner.calls[0][1], "spark0")
            self.assertEqual(runner.calls[0][0].max_output_tokens, 1)
            self.assertEqual(runner.calls[0][0].input["shared_prefix"], "repo skeleton\noutput contract\n")
            self.assertNotIn("target_atom_id", runner.calls[0][0].input)
            status = queue.prefix_warm_status(skeleton_hash="prefix-a", node_id="spark0")
            self.assertEqual(status["statuses"][0]["state"], "warm")

    def test_prefix_warm_skips_already_warm_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request(f"r{i}") for i in range(5)],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            first = queue.warm_prefixes(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", min_group_size=2)
            second = queue.warm_prefixes(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", min_group_size=2)
            self.assertEqual(first["warmed_count"], 1)
            self.assertEqual(second["warmed_count"], 0)
            self.assertEqual(second["skipped_count"], 1)


if __name__ == "__main__":
    unittest.main()
