from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.worker import BatchWorker

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
QWEN = "qwen3_6_27b_fp8_efficient_v1"


def req(request_id: str, *, priority: int | None = None, kv_key: str | None = None, kv_bytes: int = 0, output_tokens: int = 64, input_tokens: int | None = None, thinking_tokens: int = 0) -> InferenceRequest:
    raw = {
        "format": "ds4-inference-request-v1",
        "request_id": request_id,
        "capability": "efficient",
        "chat": True,
        "immediate": False,
        "job_class": "summary",
        "max_output_tokens": output_tokens,
        "thinking_budget_tokens": thinking_tokens,
        "temperature": 0,
        "input": {"messages": [{"role": "user", "content": f"reply {request_id}"}], "prompt": f"reply {request_id}"},
        "output_contract": {"format": "text"},
        "model_pin": {"profile_id": QWEN},
        "metadata": {"kv_cache_key": kv_key, "kv_bytes_estimate": kv_bytes},
    }
    if input_tokens is not None:
        raw["input"]["estimated_prompt_tokens"] = input_tokens
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

    def test_batch_id_reuse_rejects_changed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("a", output_tokens=16)], registry=registry, batch_id="job-a")
            repeated = queue.submit_requests(requests=[req("a", output_tokens=16)], registry=registry, batch_id="job-a")
            self.assertEqual(repeated["request_ids"], ["a"])
            with self.assertRaisesRegex(ValueError, "different request payloads"):
                queue.submit_requests(requests=[req("a", output_tokens=32)], registry=registry, batch_id="job-a")

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

    def test_batch_capable_runner_is_not_split_by_refill_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            for idx in range(12):
                queue.submit_requests(requests=[req(f"cohort-{idx:03d}", priority=1)], registry=registry, batch_id=f"job-{idx:03d}")
            runner = BatchRunner()
            worked = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=(QWEN,), limit=12, concurrency=12, refill_low_watermarks_by_service={"*": 8})
            self.assertEqual(worked["claimed_count"], 12)
            self.assertEqual(worked["batch_dispatch_count"], 1)
            self.assertEqual(worked["batch_dispatch_mode"], "batch")
            self.assertEqual(runner.calls, [("spark0", [f"cohort-{idx:03d}" for idx in range(12)], 12)])

    def test_ready_claim_respects_token_budget_not_just_row_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            requests = [req(f"wide-{idx:03d}", input_tokens=256, output_tokens=128, thinking_tokens=128) for idx in range(8)]
            queue.submit_requests(requests=requests, registry=registry, batch_id="wide")
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id=None, limit=8, leased_by="worker", lease_ttl_s=60)
            claims = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=8, leased_by="worker", lease_ttl_s=60, batch_token_limits_by_service={"*": 1536})
            self.assertEqual([claim.request_id for claim in claims], ["wide-000", "wide-001", "wide-002"])

    def test_ready_claim_always_allows_one_large_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("large", input_tokens=7000, output_tokens=1024)], registry=registry, batch_id="large")
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id=None, limit=1, leased_by="worker", lease_ttl_s=60)
            claims = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=1, leased_by="worker", lease_ttl_s=60, batch_token_limits_by_service={"*": 1024})
            self.assertEqual([claim.request_id for claim in claims], ["large"])

    def test_ready_shape_bucketing_claims_uniform_output_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            requests = []
            for idx in range(256):
                output_tokens = 64 if idx % 2 == 0 else 192
                requests.append(req(f"shape-{idx:03d}", priority=5, output_tokens=output_tokens))
            queue.submit_requests(requests=requests, registry=registry, batch_id="shape-bucket")
            conn = queue._connect()
            try:
                with conn:
                    conn.execute("update requests set selected_service_id='kimi27_pp13', selected_compute_domain='fleet' where batch_id='shape-bucket'")
            finally:
                conn.close()
            prepared = queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id=None, limit=256, leased_by="worker", lease_ttl_s=30, selected_service_id="kimi27_pp13", share_compute_domain=True)
            self.assertEqual(prepared, 256)

            claims = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=128, leased_by="worker", lease_ttl_s=30, selected_service_id="kimi27_pp13", share_compute_domain=True, ready_shape_bucketing=True, ready_shape_lookahead=4)

            self.assertEqual(len(claims), 128)
            self.assertEqual({claim.request.max_output_tokens for claim in claims if claim.request is not None}, {64})
            self.assertEqual([claim.request_id for claim in claims[:4]], ["shape-000", "shape-002", "shape-004", "shape-006"])

    def test_compute_lease_quantum_drains_when_another_service_waits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("DS4_COMPUTE_LEASE_QUANTUM_S")
            os.environ["DS4_COMPUTE_LEASE_QUANTUM_S"] = "0.01"
            try:
                queue = InferenceQueue(tmp)
                registry = ProfileRegistry.load(PROFILES)
                queue.submit_requests(requests=[req("a")], registry=registry, batch_id="a")
                queue.submit_requests(requests=[req("b")], registry=registry, batch_id="b")
                with queue._connect() as conn:
                    conn.execute("update requests set selected_service_id='svc-a', selected_compute_domain='fleet', selected_node_id='spark0' where request_id='a'")
                    conn.execute("update requests set selected_service_id='svc-b', selected_compute_domain='fleet', selected_node_id='spark0' where request_id='b'")
                queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id=None, limit=2, leased_by="worker", lease_ttl_s=30)
                first = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=1, leased_by="worker", lease_ttl_s=30)
                self.assertEqual([claim.request_id for claim in first], ["a"])
                time.sleep(0.02)
                second = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=1, leased_by="worker", lease_ttl_s=30)
                self.assertEqual(second, [])
                queue.finish_request(request_id="a", lease_id=first[0].lease_id, state="completed", result=make_result(request=first[0].request, profile_id=QWEN, model_id="test", backend="fake", text="a"))
                third = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=1, leased_by="worker", lease_ttl_s=30)
                self.assertEqual([claim.request_id for claim in third], ["b"])
            finally:
                if old is None:
                    os.environ.pop("DS4_COMPUTE_LEASE_QUANTUM_S", None)
                else:
                    os.environ["DS4_COMPUTE_LEASE_QUANTUM_S"] = old

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

    def test_partial_ready_batch_waits_for_recent_queued_peer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("a"), req("b")], registry=registry, batch_id="early")
            prepared = queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id=None, limit=2, leased_by="worker", lease_ttl_s=30)
            self.assertEqual(prepared, 2)
            time.sleep(0.03)
            queue.submit_requests(requests=[req("c")], registry=registry, batch_id="late")
            first = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=3, leased_by="worker", lease_ttl_s=30, batch_linger_s=0.02)
            self.assertEqual(first, [])
            prepared = queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id=None, limit=3, leased_by="worker", lease_ttl_s=30)
            self.assertEqual(prepared, 1)
            second = queue.claim_ready_batch(node_id="spark0", batch_id=None, limit=3, leased_by="worker", lease_ttl_s=30, batch_linger_s=0.02)
            self.assertEqual([claim.request_id for claim in second], ["a", "b", "c"])

    def test_heartbeat_allows_claims_that_finished_during_incremental_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            requests = [req("a"), req("b"), req("c")]
            queue.submit_requests(requests=requests, registry=registry, batch_id="job")
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id="job", limit=3, leased_by="worker", lease_ttl_s=30)
            claims = queue.claim_ready_batch(node_id="spark0", batch_id="job", limit=3, leased_by="worker", lease_ttl_s=30)
            result = make_result(request=requests[0], profile_id=QWEN, model_id="model", backend="fake", text="done")
            self.assertTrue(queue.finish_request(request_id="a", lease_id=claims[0].lease_id, state="completed", result=result))
            worker = BatchWorker(queue=queue, registry=registry, runner=BatchRunner(), worker_id="worker")
            worker._heartbeat(claims)
            self.assertEqual(queue.status(request_id="a")["state"], "completed")
            self.assertEqual(queue.status(request_id="b")["state"], "running")
            self.assertEqual(queue.status(request_id="c")["state"], "running")

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
            self.assertEqual(cancelled["running_cancel_requested_ids"], ["run"])
            self.assertEqual(cancelled["running_cancel_requested_count"], 1)
            self.assertEqual(cancelled["skipped_state_counts"], {})
            self.assertTrue(queue.status(request_id="run")["cancel_requested"])
            result = make_result(request=claims[0].request, profile_id=QWEN, model_id="m", backend="fake", text="late")
            queue.finish_request(request_id="run", lease_id=claims[0].lease_id, state="completed", result=result)
            self.assertEqual(queue.status(request_id="run")["state"], "cancelled")

    def test_force_cancel_job_terminal_cancels_running_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("run"), req("wait")], registry=registry, batch_id="job")
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id="job", limit=2, leased_by="worker", lease_ttl_s=30)
            claims = queue.claim_ready_batch(node_id="spark0", batch_id="job", limit=1, leased_by="worker", lease_ttl_s=30)
            cancelled = queue.cancel(job_id="job", reason="operator force", force_running=True)
            self.assertEqual(cancelled["cancelled_request_ids"], ["run", "wait"])
            self.assertEqual(cancelled["running_cancel_requested_ids"], [])
            self.assertEqual(cancelled["running_cancel_requested_count"], 0)
            self.assertEqual(cancelled["skipped_state_counts"], {})
            self.assertEqual(queue.status(request_id="run")["state"], "cancelled")
            self.assertFalse(queue.status(request_id="run")["cancel_requested"])
            self.assertEqual(queue.status(request_id="wait")["state"], "cancelled")
            self.assertEqual(queue.status(job_id="job")["state"], "cancelled")
            self.assertEqual(queue.status()["active_compute_leases"], [])
            result = make_result(request=claims[0].request, profile_id=QWEN, model_id="m", backend="fake", text="late")
            self.assertFalse(queue.finish_request(request_id="run", lease_id=claims[0].lease_id, state="completed", result=result))
            self.assertEqual(queue.status(request_id="run")["state"], "cancelled")

    def test_batch_status_can_skip_write_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("stale")], registry=registry, batch_id="job")
            with sqlite3.connect(Path(tmp) / "queue.sqlite3") as conn:
                conn.execute("update requests set state='completed', result_json='{}', completed_at=?, updated_at=? where request_id='stale'", (time.time(), time.time()))
            self.assertEqual(queue.status(batch_id="job", refresh=False)["state"], "queued")
            self.assertEqual(queue.status(batch_id="job", refresh=True)["state"], "completed")

    def test_usage_summarizes_completed_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            requests = [req("a"), req("b"), req("old")]
            queue.submit_requests(requests=requests, registry=registry, batch_id="job")
            queue.prepare_ready(node_id="spark0", eligible_profile_ids=(QWEN,), batch_id="job", limit=3, leased_by="worker", lease_ttl_s=30)
            claims = queue.claim_ready_batch(node_id="spark0", batch_id="job", limit=3, leased_by="worker", lease_ttl_s=30)
            claims_by_id = {claim.request_id: claim for claim in claims}
            result_a = make_result(request=claims_by_id["a"].request, profile_id=QWEN, model_id="model", backend="fake", text="a")
            result_a["usage"] = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
            result_b = make_result(request=claims_by_id["b"].request, profile_id=QWEN, model_id="model", backend="fake", text="b")
            result_b["usage"] = {"input_tokens": 5, "output_tokens": 15}
            result_old = make_result(request=claims_by_id["old"].request, profile_id=QWEN, model_id="model", backend="fake", text="old")
            result_old["usage"] = {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}
            self.assertTrue(queue.finish_request(request_id="a", lease_id=claims_by_id["a"].lease_id, state="completed", result=result_a))
            self.assertTrue(queue.finish_request(request_id="b", lease_id=claims_by_id["b"].lease_id, state="completed", result=result_b))
            self.assertTrue(queue.finish_request(request_id="old", lease_id=claims_by_id["old"].lease_id, state="completed", result=result_old))
            with sqlite3.connect(Path(tmp) / "queue.sqlite3") as conn:
                conn.execute("update requests set completed_at=990.0, updated_at=990.0 where request_id='a'")
                conn.execute("update requests set completed_at=995.0, updated_at=995.0 where request_id='b'")
                conn.execute("update requests set completed_at=850.0, updated_at=850.0 where request_id='old'")
            usage = queue.usage(window_s=100.0, now=1000.0)
            self.assertEqual(usage["format"],"ds4-inference-queue-v1")
            self.assertEqual(usage["completed_count"],2)
            self.assertEqual(usage["usage_count"],2)
            self.assertEqual(usage["prompt_tokens"],15)
            self.assertEqual(usage["completion_tokens"],35)
            self.assertEqual(usage["total_tokens"],50)
            self.assertEqual(usage["prompt_tok_s"],0.15)
            self.assertEqual(usage["completion_tok_s"],0.35)
            self.assertEqual(usage["total_tok_s"],0.5)

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

    def test_jit_kv_startup_recovery_releases_prefilling_and_prefetch_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[req("stuck")], registry=registry, batch_id="job")
            with queue._connect() as conn:
                conn.execute("update requests set state='prefilling', lease_id='lost', leased_by='old-worker', updated_at=? where request_id='stuck'", (time.time() - 100,))
                queue._refresh_batch(conn, "job")
            shards = [
                {"node_id": "spark0", "stage_index": 0, "stage_count": 2, "state": "prefetch_inflight"},
                {"node_id": "spark1", "stage_index": 1, "stage_count": 2, "state": "prefetch_inflight"},
            ]
            queue.upsert_external_kv_object(namespace="default", kv_key="prefix", service_id="qwen27_bf16_pp8", state="prefetch_inflight", total_bytes=2, shards=shards)

            recovered = queue.recover_jit_kv_startup(stale_s=0)

            self.assertEqual(recovered["wait_released"], 1)
            self.assertEqual(recovered["objects_recovered"], 1)
            self.assertEqual(recovered["shards_recovered"], 2)
            self.assertEqual(queue.status(request_id="stuck")["state"], "queued")
            self.assertEqual(queue.status(batch_id="job")["state"], "queued")
            manifest = queue.external_kv_lookup(namespace="default", kv_key="prefix", service_id="qwen27_bf16_pp8")
            self.assertEqual(manifest["state"], "declared")
            self.assertEqual({shard["state"] for shard in manifest["shards"]}, {"declared"})


if __name__ == "__main__":
    unittest.main()
