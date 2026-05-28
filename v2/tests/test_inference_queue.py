from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue
from ds4_infer.schemas import InferenceRequest, make_result

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
QWEN = "qwen3_6_27b_fp8_efficient_v1"


def req(request_id: str, *, priority: int | None = None, kv_key: str | None = None, kv_bytes: int = 0, output_tokens: int = 64) -> InferenceRequest:
    raw = {
        "format": "ds4-inference-request-v1",
        "request_id": request_id,
        "capability": "efficient",
        "chat": True,
        "immediate": False,
        "job_class": "summary",
        "max_output_tokens": output_tokens,
        "thinking_budget_tokens": 0,
        "temperature": 0,
        "input": {"messages": [{"role": "user", "content": f"reply {request_id}"}], "prompt": f"reply {request_id}"},
        "output_contract": {"format": "text"},
        "model_pin": {"profile_id": QWEN},
        "metadata": {"kv_cache_key": kv_key, "kv_bytes_estimate": kv_bytes},
    }
    if priority is not None:
        raw["priority"] = priority
    return InferenceRequest.from_json(raw)


class BatchRunner:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.calls: list[tuple[str | None, list[str], int]] = []
        self.fail = fail or set()

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        self.calls.append((node_id, [r.request_id for r in requests], concurrency))
        out = {}
        for request in requests:
            out[request.request_id] = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=request.request_id, status="failed" if request.request_id in self.fail else "completed")
        return out


class TransportFlakyBatchRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, list[str]]] = []

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        self.calls.append((node_id, [r.request_id for r in requests]))
        out = {}
        for request in requests:
            status = "transport_failed" if len(self.calls) == 1 else "completed"
            out[request.request_id] = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=request.request_id, status=status)
            if status == "transport_failed":
                out[request.request_id]["transport"] = {"error": f"{node_id} transient transport failure"}
        return out


class InferenceQueueTests(unittest.TestCase):
    def test_submit_is_late_bound_and_priority_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            result = queue.submit_requests(requests=[req("a", priority=1), req("b", priority=10)], registry=registry, batch_id="job-a")
            self.assertEqual(result["metadata"]["late_bound_count"], 2)
            self.assertEqual(result["selected_nodes"], {})
            self.assertIsNone(queue.status(request_id="a")["selected_node_id"])
            self.assertEqual(queue.status(request_id="a")["priority"], 1)

    def test_empty_submit_and_priority_mismatch_fail_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            with self.assertRaises(ValueError):
                queue.submit_requests(requests=[], registry=registry, batch_id="empty")
            queue.submit_requests(requests=[req("a", priority=1)], registry=registry, batch_id="job-a")
            with self.assertRaises(ValueError):
                queue.submit_requests(requests=[req("a", priority=2)], registry=registry, batch_id="job-a")

    def test_node_worker_binds_prefills_and_dispatches_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            for idx in range(36):
                queue.submit_requests(requests=[req(f"hwm-{idx:03d}", priority=1)], registry=registry, batch_id=f"job-{idx:03d}")
            runner = BatchRunner()
            worked = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=12, concurrency=12)
            self.assertEqual(worked["prefilled_count"], 12)
            self.assertEqual(worked["claimed_count"], 12)
            self.assertEqual(worked["completed_count"], 12)
            self.assertEqual(worked["batch_dispatch_count"], 1)
            self.assertEqual(worked["batch_dispatch_mode"], "batch")
            self.assertEqual(runner.calls, [("spark0", [f"hwm-{idx:03d}" for idx in range(12)], 12)])
            self.assertEqual(queue.status()["state_counts"], {"completed": 12, "queued": 24})

    def test_partial_batch_waits_for_linger_then_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("a"), req("b"), req("c")], registry=registry, batch_id="job")
            runner = BatchRunner()
            first = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=12, concurrency=12, batch_linger_s=0.2)
            self.assertEqual(first["prefilled_count"], 3)
            self.assertEqual(first["claimed_count"], 0)
            time.sleep(0.22)
            second = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=12, concurrency=12, batch_linger_s=0.2)
            self.assertEqual(second["claimed_count"], 3)
            self.assertEqual(runner.calls, [("spark0", ["a", "b", "c"], 12)])

    def test_priority_takes_slots_but_background_fills_empty_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            for idx in range(16):
                queue.submit_requests(requests=[req(f"bg-{idx:03d}", priority=10)], registry=registry, batch_id=f"bg-{idx:03d}")
            for idx in range(4):
                queue.submit_requests(requests=[req(f"exp-{idx:03d}", priority=1)], registry=registry, batch_id=f"exp-{idx:03d}")
            runner = BatchRunner()
            worked = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=12, concurrency=12)
            self.assertEqual(worked["claimed_count"], 12)
            self.assertEqual(runner.calls[0][1], [f"exp-{idx:03d}" for idx in range(4)] + [f"bg-{idx:03d}" for idx in range(8)])

    def test_kv_capacity_uses_lru_idle_purge_not_completion_eject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("a", kv_key="ka", kv_bytes=60), req("b", kv_key="kb", kv_bytes=60)], registry=registry, batch_id="first")
            runner = BatchRunner()
            queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=2, concurrency=2, kv_capacity_bytes=120)
            con = sqlite3.connect(Path(tmp) / "queue.sqlite3")
            self.assertEqual(con.execute("select count(*) from kv_entries").fetchone()[0], 2)
            queue.submit_requests(requests=[req("c", kv_key="kc", kv_bytes=80)], registry=registry, batch_id="second")
            queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=1, concurrency=1, kv_capacity_bytes=140)
            keys = {row[0] for row in con.execute("select kv_key from kv_entries")}
            self.assertEqual(keys, {"kb", "kc"})
            con.close()

    def test_cancel_job_cancels_queued_and_marks_running_cancel_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("run"), req("wait")], registry=registry, batch_id="job")
            claims = queue.claim_ready_batch(node_id="spark0", batch_id="job", limit=1, leased_by="worker", lease_ttl_s=30)
            self.assertEqual(claims, [])
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id="job", limit=2, leased_by="worker", lease_ttl_s=30)
            claims = queue.claim_ready_batch(node_id="spark0", batch_id="job", limit=1, leased_by="worker", lease_ttl_s=30)
            cancelled = queue.cancel(job_id="job", reason="stop")
            self.assertEqual(cancelled["cancelled_request_ids"], ["wait"])
            self.assertEqual(cancelled["skipped_state_counts"], {"running": 1})
            self.assertTrue(queue.status(request_id="run")["cancel_requested"])
            result = make_result(request=claims[0].request, profile_id=QWEN, model_id="m", backend="fake", text="late")
            queue.finish_request(request_id="run", lease_id=claims[0].lease_id, state="completed", result=result)
            self.assertEqual(queue.status(request_id="run")["state"], "cancelled")

    def test_expired_lease_requeues_then_fails_after_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("a")], registry=registry, batch_id="job")
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id="job", limit=1, leased_by="worker", lease_ttl_s=30)
            first = queue.claim_ready_batch(node_id="spark0", batch_id="job", limit=1, leased_by="worker", lease_ttl_s=1)[0]
            queue.requeue_expired_leases(now=time.time() + 2, max_attempts=2)
            self.assertEqual(queue.status(request_id="a")["state"], "queued")
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id="job", limit=1, leased_by="worker", lease_ttl_s=30)
            second = queue.claim_ready_batch(node_id="spark0", batch_id="job", limit=1, leased_by="worker", lease_ttl_s=1)[0]
            self.assertNotEqual(first.lease_id, second.lease_id)
            queue.requeue_expired_leases(now=time.time() + 2, max_attempts=2)
            self.assertEqual(queue.status(request_id="a")["state"], "failed")

    def test_batch_item_failure_is_per_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("ok"), req("bad")], registry=registry, batch_id="job")
            runner = BatchRunner(fail={"bad"})
            worked = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=2, concurrency=2)
            self.assertEqual(worked["completed_count"], 1)
            self.assertEqual(worked["failed_count"], 1)
            self.assertEqual(queue.status(request_id="ok")["state"], "completed")
            self.assertEqual(queue.status(request_id="bad")["state"], "failed")

    def test_transport_failure_requeues_and_clears_node_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("a")], registry=registry, batch_id="job")
            runner = TransportFlakyBatchRunner()
            first = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=1, concurrency=1, transport_max_attempts=3)
            self.assertEqual(first["retried_count"], 1)
            self.assertEqual(queue.status(request_id="a")["state"], "queued")
            self.assertIsNone(queue.status(request_id="a")["selected_node_id"])
            second = queue.work(registry=registry, runner=runner, node_id="spark1", node_profile_ids=(QWEN,), limit=1, concurrency=1, transport_max_attempts=3)
            self.assertEqual(second["completed_count"], 1)
            self.assertEqual(queue.status(request_id="a")["state"], "completed")
            self.assertEqual(runner.calls, [("spark0", ["a"]), ("spark1", ["a"])])

    def test_transport_failure_fails_after_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("a")], registry=registry, batch_id="job")
            runner = TransportFlakyBatchRunner()
            worked = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=1, concurrency=1, transport_max_attempts=1)
            self.assertEqual(worked["failed_count"], 1)
            self.assertEqual(queue.status(request_id="a")["state"], "failed")
            self.assertIn("spark0 transient transport failure", queue.status(request_id="a")["error"])


if __name__ == "__main__":
    unittest.main()
