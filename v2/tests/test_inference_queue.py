from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import CPU_QUEUE_TIMEOUT_KEY, InferenceQueue, request_batch_key
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology
from ds4_infer.worker import BatchWorker
from ds4_tools.cpu_batch import CpuServiceError

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


class DelayedRunner:
    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays

    def run_one(self, request, profile):
        time.sleep(self.delays.get(request.request_id, 0.0))
        return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=f"delayed {request.request_id}")


class BatchCapableDelayedRunner:
    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays
        self.one_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    def run_one_on_node(self, request, profile, node_id):
        self.one_calls.append(request.request_id)
        time.sleep(self.delays.get(request.request_id, 0.0))
        return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=f"delayed {request.request_id}")

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        self.batch_calls.append([request.request_id for request in requests])
        return {request.request_id: make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=f"batched {request.request_id}") for request in requests}


class CpuSpyService:
    def __init__(self) -> None:
        self.payload: dict | None = None

    def run_batch(self, payload: dict) -> dict:
        self.payload = payload
        return {"results": [{"ok": True, "response": {"ok": True}} for _ in payload["items"]]}


def wait_for_notice(root: Path, request_id: str, timeout_s: float = 1.0) -> bool:
    deadline = time.time() + timeout_s
    path = root / "notices" / f"{request_id}.json"
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


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

    def test_worker_can_limit_work_to_batch_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[make_request("a0")], registry=registry, batch_id="batch-a")
            queue.submit_requests(requests=[make_request("b0")], registry=registry, batch_id="batch-b")
            worked = queue.work(registry=registry, runner=FakeRunner(), batch_id="batch-b", limit=10)
            self.assertEqual(worked["claimed_count"], 1)
            self.assertEqual(queue.status(request_id="a0")["state"], "queued")
            self.assertEqual(queue.status(request_id="b0")["state"], "completed")

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

    def test_concurrent_worker_emits_fast_notices_before_slow_request_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = InferenceQueue(root)
            queue.submit_requests(
                requests=[make_request("fast0"), make_request("fast1"), make_request("slow")],
                registry=ProfileRegistry.load(PROFILES),
                batch_id="batch-a",
            )
            first_poll = queue.poll()
            worked: dict[str, object] = {}
            thread = threading.Thread(
                target=lambda: worked.update(
                    queue.work(
                        registry=ProfileRegistry.load(PROFILES),
                        runner=DelayedRunner({"fast0": 0.05, "fast1": 0.05, "slow": 1.0}),
                        limit=3,
                        concurrency=3,
                        lease_ttl_s=5,
                        heartbeat_interval_s=0.05,
                    )
                )
            )
            thread.start()
            self.assertTrue(wait_for_notice(root, "fast0", timeout_s=0.4))
            self.assertTrue(wait_for_notice(root, "fast1", timeout_s=0.4))
            self.assertFalse((root / "notices" / "slow.json").exists())
            second_poll = queue.poll(after_event_id=first_poll["newest_event_id"])
            self.assertIn("completed", [event["event_type"] for event in second_poll["events"]])
            self.assertTrue(thread.is_alive())
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(worked["claimed_count"], 3)
            self.assertEqual(worked["completed_count"], 3)

    def test_worker_refills_inflight_window_before_slow_tail_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = InferenceQueue(root)
            queue.submit_requests(
                requests=[make_request("a_fast"), make_request("b_slow"), make_request("c_refill"), make_request("d_refill")],
                registry=ProfileRegistry.load(PROFILES),
                batch_id="batch-a",
            )
            worked: dict[str, object] = {}
            thread = threading.Thread(
                target=lambda: worked.update(
                    queue.work(
                        registry=ProfileRegistry.load(PROFILES),
                        runner=DelayedRunner({"a_fast": 0.05, "b_slow": 1.0, "c_refill": 0.05, "d_refill": 0.05}),
                        limit=4,
                        concurrency=2,
                        lease_ttl_s=5,
                        heartbeat_interval_s=0.05,
                    )
                )
            )
            thread.start()
            self.assertTrue(wait_for_notice(root, "a_fast", timeout_s=0.4))
            self.assertTrue(wait_for_notice(root, "c_refill", timeout_s=0.6))
            self.assertTrue(wait_for_notice(root, "d_refill", timeout_s=0.8))
            self.assertFalse((root / "notices" / "b_slow.json").exists())
            self.assertTrue(thread.is_alive())
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(worked["claimed_count"], 4)
            self.assertEqual(worked["completed_count"], 4)

    def test_batch_capable_model_runner_still_refills_and_notices_per_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = InferenceQueue(root)
            queue.submit_requests(
                requests=[make_request("a_fast"), make_request("b_slow"), make_request("c_refill"), make_request("d_refill")],
                registry=ProfileRegistry.load(PROFILES),
                batch_id="batch-a",
            )
            runner = BatchCapableDelayedRunner({"a_fast": 0.05, "b_slow": 1.0, "c_refill": 0.05, "d_refill": 0.05})
            worked: dict[str, object] = {}
            thread = threading.Thread(
                target=lambda: worked.update(
                    queue.work(
                        registry=ProfileRegistry.load(PROFILES),
                        runner=runner,
                        limit=4,
                        concurrency=2,
                        lease_ttl_s=5,
                        heartbeat_interval_s=0.05,
                    )
                )
            )
            thread.start()
            self.assertTrue(wait_for_notice(root, "a_fast", timeout_s=0.4))
            self.assertTrue(wait_for_notice(root, "c_refill", timeout_s=0.6))
            self.assertTrue(wait_for_notice(root, "d_refill", timeout_s=0.8))
            self.assertFalse((root / "notices" / "b_slow.json").exists())
            self.assertTrue(thread.is_alive())
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(worked["claimed_count"], 4)
            self.assertEqual(worked["completed_count"], 4)
            self.assertEqual(runner.batch_calls, [])

    def test_cpu_service_jobs_use_same_durable_queue_and_notices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = InferenceQueue(root)
            submitted = queue.submit_cpu_requests(
                service="text_metrics",
                items=[{"custom_id": "cpu-a", "text": "one two"}, {"custom_id": "cpu-b", "text": "three"}],
                batch_id="cpu-batch",
            )
            self.assertEqual(submitted["selected_services"], {"text_metrics": 2})
            worked = queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), limit=2, concurrency=2)
            self.assertEqual(worked["completed_count"], 2)
            collected = queue.collect(batch_id="cpu-batch")
            self.assertEqual(collected["results"][0]["result"]["format"], "ds4-cpu-service-result-v1")
            self.assertEqual(collected["results"][0]["result"]["output"]["response"]["words"], 2)
            self.assertTrue((root / "notices" / "cpu-a.json").exists())

    def test_cpu_submit_validates_service_and_item_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            with self.assertRaisesRegex(CpuServiceError, "unknown CPU service"):
                queue.submit_cpu_requests(service="missing", items=[{"custom_id": "x"}])
            with patch.dict("os.environ", {"CPU_SERVICE_MAX_ITEMS": "1"}):
                with self.assertRaisesRegex(CpuServiceError, "exceeds CPU_SERVICE_MAX_ITEMS"):
                    queue.submit_cpu_requests(service="text_metrics", items=[{"custom_id": "a"}, {"custom_id": "b"}])

    def test_cpu_queue_timeout_reaches_service_without_leaking_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_cpu_requests(service="text_metrics", items=[{"custom_id": "cpu-a", "text": "one"}], batch_id="cpu-batch", timeout_s=12)
            service = CpuSpyService()
            worker = BatchWorker(queue=queue, registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), cpu_service=service, lease_ttl_s=99)
            worked = worker.run_once(limit=1, concurrency=1)
            self.assertEqual(worked["completed_count"], 1)
            self.assertIsNotNone(service.payload)
            assert service.payload is not None
            self.assertEqual(service.payload["timeout_s"], 12.0)
            self.assertNotIn(CPU_QUEUE_TIMEOUT_KEY, service.payload["items"][0])

    def test_queue_sets_busy_timeout_for_multi_worker_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"DS4_QUEUE_BUSY_TIMEOUT_MS": "1234"}):
                queue = InferenceQueue(tmp)
                with closing(queue._connect()) as conn:
                    row = conn.execute("pragma busy_timeout").fetchone()
            self.assertEqual(int(row[0]), 1234)

    def test_expired_running_lease_requeues_then_fails_after_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request("r0")],
                registry=ProfileRegistry.load(PROFILES),
                batch_id="batch-a",
            )
            first_claim = queue.claim_requests(leased_by="test-worker", lease_ttl_s=1)
            self.assertEqual(len(first_claim), 1)
            reaped = queue.requeue_expired_leases(max_attempts=2, now=time.time() + 2)
            self.assertEqual(reaped["requeued_count"], 1)
            status = queue.status(request_id="r0")
            self.assertEqual(status["state"], "queued")
            self.assertEqual(status["attempt_count"], 1)
            self.assertIsNone(status["lease_id"])
            second_claim = queue.claim_requests(leased_by="test-worker", lease_ttl_s=1)
            self.assertEqual(len(second_claim), 1)
            reaped = queue.requeue_expired_leases(max_attempts=2, now=time.time() + 2)
            self.assertEqual(reaped["failed_count"], 1)
            self.assertEqual(queue.status(request_id="r0")["state"], "failed")
            notice = json.loads((Path(tmp) / "notices" / "r0.json").read_text())
            self.assertEqual(notice["result"]["status"], "lease_expired")

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
