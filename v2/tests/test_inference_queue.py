from __future__ import annotations

from contextlib import closing
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ds4_infer import cli
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import CPU_QUEUE_TIMEOUT_KEY, InferenceQueue, request_batch_key
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.service import load_requests_jsonl
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


def make_prefixed_request(request_id: str, prefix_id: str) -> InferenceRequest:
    raw = json.loads(json.dumps(make_request(request_id).raw))
    raw["input"]["shared_prefix"] = f"repo skeleton {prefix_id}\noutput contract\n"
    raw["input"]["shared_prefix_hash"] = prefix_id
    raw["input"]["skeleton_hash"] = prefix_id
    return InferenceRequest.from_json(raw)


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
        if requests:
            time.sleep(max(self.delays.get(request.request_id, 0.0) for request in requests))
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


def _submit_ids(queue: InferenceQueue, request_ids: list[str]) -> None:
    queue.submit_requests(requests=[make_request(request_id) for request_id in request_ids], registry=ProfileRegistry.load(PROFILES), batch_id="batch-a")


def _node_profile_ids(node_id: str) -> tuple[str, ...]:
    topology = SparkTopology.load(TOPOLOGY)
    for node in topology.nodes:
        if node.node_id == node_id:
            return tuple(node.resident_profiles)
    raise AssertionError(f"missing test node {node_id}")


def _work_thread(queue: InferenceQueue, runner, *, limit: int, concurrency: int) -> tuple[threading.Thread, dict[str, object]]:
    worked: dict[str, object] = {}
    thread = threading.Thread(
        target=lambda: worked.update(
            queue.work(
                registry=ProfileRegistry.load(PROFILES),
                runner=runner,
                limit=limit,
                concurrency=concurrency,
                lease_ttl_s=5,
                heartbeat_interval_s=0.05,
            )
        )
    )
    thread.start()
    return thread, worked


def _assert_done(case: unittest.TestCase, thread: threading.Thread, worked: dict[str, object], count: int) -> None:
    case.assertTrue(thread.is_alive())
    thread.join(timeout=2.0)
    case.assertFalse(thread.is_alive())
    case.assertEqual(worked["claimed_count"], count)
    case.assertEqual(worked["completed_count"], count)


def _assert_refill(case: unittest.TestCase, root: Path, queue: InferenceQueue, runner) -> dict[str, object]:
    _submit_ids(queue, ["a_fast", "b_slow", "c_refill", "d_refill"])
    thread, worked = _work_thread(queue, runner, limit=4, concurrency=2)
    for request_id, timeout_s in (("a_fast", 0.4), ("c_refill", 0.6), ("d_refill", 0.8)):
        case.assertTrue(wait_for_notice(root, request_id, timeout_s=timeout_s))
    case.assertFalse((root / "notices" / "b_slow.json").exists())
    _assert_done(case, thread, worked, 4)
    return worked


class InferenceQueueTests(unittest.TestCase):
    def test_load_requests_resolves_disk_prefix_cache_ref_before_queueing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = "repo skeleton\noutput contract\n"
            digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
            (root / "prefix.txt").write_text(prefix, encoding="utf-8")
            payload = make_request("cached").raw
            payload["input"] = {
                "kv_cache_ref": {
                    "format": "ds4-prefix-cache-ref-v1",
                    "kind": "prefix_text",
                    "path": "prefix.txt",
                    "sha256": "sha256:" + digest,
                    "skeleton_hash": "longmem-baseline-v1",
                },
                "suffix": "def f():\n    return 1\n",
            }
            requests_path = root / "requests.jsonl"
            requests_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            requests = load_requests_jsonl(requests_path)
            self.assertEqual(requests[0].input["shared_prefix"], prefix)
            self.assertEqual(requests[0].input["shared_prefix_hash"], "sha256:" + digest)
            self.assertEqual(requests[0].input["skeleton_hash"], "longmem-baseline-v1")
            self.assertEqual(requests[0].input["kv_cache_resolution"]["kind"], "prefix_text")
            queue = InferenceQueue(root / "queue")
            queue.submit_requests(requests=requests, registry=ProfileRegistry.load(PROFILES), topology=SparkTopology.load(TOPOLOGY), batch_id="batch-a")
            self.assertIn("sha256:" + digest, queue.status(request_id="cached")["batch_key"])

    def test_load_requests_rejects_bad_prefix_cache_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prefix.txt").write_text("prefix", encoding="utf-8")
            payload = make_request("bad-cache").raw
            payload["input"] = {
                "kv_cache_ref": {
                    "format": "ds4-prefix-cache-ref-v1",
                    "kind": "prefix_text",
                    "path": "prefix.txt",
                    "sha256": "0" * 64,
                },
                "suffix": "target",
            }
            requests_path = root / "requests.jsonl"
            requests_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                load_requests_jsonl(requests_path)

    def test_load_requests_rejects_unknown_prefix_cache_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = "prefix"
            digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
            (root / "prefix.txt").write_text(prefix, encoding="utf-8")
            payload = make_request("bad-cache-kind").raw
            payload["input"] = {
                "kv_cache_ref": {
                    "format": "ds4-prefix-cache-ref-v1",
                    "kind": "raw_tensor_kv",
                    "path": "prefix.txt",
                    "sha256": digest,
                },
                "suffix": "target",
            }
            requests_path = root / "requests.jsonl"
            requests_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported kv_cache_ref kind"):
                load_requests_jsonl(requests_path)

    def test_queue_rejects_unresolved_prefix_cache_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = make_request("unresolved-cache").raw
            raw["input"] = {
                "kv_cache_ref": {
                    "format": "ds4-prefix-cache-ref-v1",
                    "kind": "prefix_text",
                    "path": "prefix.txt",
                    "sha256": "0" * 64,
                },
                "suffix": "target",
            }
            queue = InferenceQueue(tmp)
            with self.assertRaisesRegex(ValueError, "resolved before queueing"):
                queue.submit_requests(requests=[InferenceRequest.from_json(raw)], registry=ProfileRegistry.load(PROFILES), batch_id="batch-a")

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
            self.assertEqual(result["selected_nodes"], {})
            self.assertEqual(result["metadata"]["late_bound_count"], 2)
            self.assertEqual(queue.status(batch_id="batch-a")["queued_count"], 2)
            self.assertEqual(queue.status(request_id="r0")["state"], "queued")
            self.assertIsNone(queue.status(request_id="r0")["selected_node_id"])

    def test_submit_existing_batch_id_is_idempotent_for_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            requests = [make_request("r0"), make_request("r1")]
            first = queue.submit_requests(requests=requests, registry=registry, topology=SparkTopology.load(TOPOLOGY), batch_id="retry-batch")
            second = queue.submit_requests(requests=requests, registry=registry, topology=SparkTopology.load(TOPOLOGY), batch_id="retry-batch")
            self.assertEqual(second["batch_id"], first["batch_id"])
            self.assertEqual(second["request_ids"], first["request_ids"])
            self.assertEqual(queue.status(batch_id="retry-batch")["queued_count"], 2)
            with self.assertRaisesRegex(ValueError, "different requests"):
                queue.submit_requests(requests=[make_request("other")], registry=registry, topology=SparkTopology.load(TOPOLOGY), batch_id="retry-batch")
            with self.assertRaisesRegex(ValueError, "different priority"):
                queue.submit_requests(requests=requests, registry=registry, topology=SparkTopology.load(TOPOLOGY), batch_id="retry-batch", priority=1)

    def test_priority_claims_experiment_before_background_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[make_request("background", output_tokens=2048)], registry=registry, batch_id="full500")
            queue.submit_requests(requests=[make_request("experiment", output_tokens=128)], registry=registry, batch_id="experiment", priority=1)
            self.assertEqual(queue.status(request_id="background")["priority"], 10)
            self.assertEqual(queue.status(request_id="experiment")["priority"], 1)
            claim = queue.claim_requests(leased_by="worker", lease_ttl_s=30, limit=4)
            self.assertEqual([item.request_id for item in claim], ["experiment"])
            self.assertTrue(queue.finish_request(request_id="experiment", lease_id=claim[0].lease_id, state="completed", result={"status": "completed"}))
            claim = queue.claim_requests(leased_by="worker", lease_ttl_s=30, limit=4)
            self.assertEqual([item.request_id for item in claim], ["background"])

    def test_request_json_priority_is_used_unless_submit_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            raw = make_request("json-priority").raw
            raw["priority"] = 2
            queue.submit_requests(requests=[InferenceRequest.from_json(raw)], registry=registry, batch_id="json")
            self.assertEqual(queue.status(request_id="json-priority")["priority"], 2)
            raw = make_request("override-priority").raw
            raw["priority"] = 9
            queue.submit_requests(requests=[InferenceRequest.from_json(raw)], registry=registry, batch_id="override", priority=1)
            self.assertEqual(queue.status(request_id="override-priority")["priority"], 1)

    def test_cli_queue_submit_priority_flag_records_auditable_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests_path = root / "requests.jsonl"
            requests_path.write_text(json.dumps(make_request("cli-priority").raw) + "\n", encoding="utf-8")
            queue_dir = root / "queue"
            with redirect_stdout(io.StringIO()):
                rc = cli.main(
                    [
                        "queue-submit",
                        "--queue-dir",
                        str(queue_dir),
                        "--profiles-dir",
                        str(PROFILES),
                        "--topology",
                        str(TOPOLOGY),
                        "--requests",
                        str(requests_path),
                        "--batch-id",
                        "cli-batch",
                        "--priority",
                        "1",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(InferenceQueue(queue_dir).status(request_id="cli-priority")["priority"], 1)

    def test_worker_completes_only_the_requested_node_and_writes_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request("r0"), make_request("r1")],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            worked = queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", node_profile_ids=_node_profile_ids("spark0"), limit=1)
            self.assertEqual(worked["claimed_count"], 1)
            self.assertEqual(worked["completed_count"], 1)
            self.assertEqual(queue.status(request_id="r0")["state"], "completed")
            self.assertEqual(queue.status(request_id="r1")["state"], "queued")
            notice = json.loads((Path(tmp) / "notices" / "r0.json").read_text())
            self.assertEqual(notice["state"], "completed")
            self.assertIn("centaur-atom-edit-v1", notice["result"]["output"]["text"])

    def test_node_worker_claim_respects_max_node_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(
                requests=[make_request("r0"), make_request("r1"), make_request("r2")],
                registry=registry,
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            first = queue.claim_requests(node_id="spark0", include_unassigned=True, eligible_profile_ids=_node_profile_ids("spark0"), max_node_depth=2, limit=3, leased_by="w0", lease_ttl_s=30)
            self.assertEqual([claim.request_id for claim in first], ["r0", "r1"])
            self.assertEqual(queue.status(request_id="r0")["selected_node_id"], "spark0")
            self.assertEqual(queue.status(request_id="r1")["selected_node_id"], "spark0")
            self.assertEqual(queue.claim_requests(node_id="spark0", include_unassigned=True, eligible_profile_ids=_node_profile_ids("spark0"), max_node_depth=2, limit=1, leased_by="w0", lease_ttl_s=30), [])
            self.assertTrue(queue.finish_request(request_id="r0", lease_id=first[0].lease_id, state="completed", result={"status": "completed"}))
            second = queue.claim_requests(node_id="spark0", include_unassigned=True, eligible_profile_ids=_node_profile_ids("spark0"), max_node_depth=2, limit=3, leased_by="w0", lease_ttl_s=30)
            self.assertEqual([claim.request_id for claim in second], ["r2"])

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
            queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", node_profile_ids=_node_profile_ids("spark0"), limit=1)
            cancelled = queue.cancel(batch_id="batch-a", reason="stop remaining")
            self.assertEqual(cancelled["cancelled_request_ids"], ["r1"])
            self.assertEqual(cancelled["skipped_state_counts"], {"completed": 1})
            self.assertEqual(queue.status(request_id="r0")["state"], "completed")
            self.assertEqual(queue.status(request_id="r1")["state"], "cancelled")
            batch_status = queue.status(batch_id="batch-a")
            self.assertEqual(batch_status["state"], "completed_with_cancelled")
            self.assertEqual(batch_status["completed_count"], 1)
            self.assertEqual(batch_status["cancelled_count"], 1)

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
            _submit_ids(queue, ["fast0", "fast1", "slow"])
            first_poll = queue.poll()
            thread, worked = _work_thread(queue, DelayedRunner({"fast0": 0.05, "fast1": 0.05, "slow": 1.0}), limit=3, concurrency=3)
            self.assertTrue(wait_for_notice(root, "fast0", timeout_s=0.4))
            self.assertTrue(wait_for_notice(root, "fast1", timeout_s=0.4))
            self.assertFalse((root / "notices" / "slow.json").exists())
            second_poll = queue.poll(after_event_id=first_poll["newest_event_id"])
            self.assertIn("completed", [event["event_type"] for event in second_poll["events"]])
            _assert_done(self, thread, worked, 3)

    def test_worker_refills_inflight_window_before_slow_tail_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = InferenceQueue(root)
            _assert_refill(self, root, queue, DelayedRunner({"a_fast": 0.05, "b_slow": 1.0, "c_refill": 0.05, "d_refill": 0.05}))

    def test_batch_capable_model_runner_finishes_fast_claims_before_slow_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = InferenceQueue(root)
            runner = BatchCapableDelayedRunner({"a_fast": 0.05, "b_slow": 1.0, "c_refill": 0.05, "d_refill": 0.05})
            _submit_ids(queue, ["a_fast", "b_slow", "c_refill", "d_refill"])
            first_poll = queue.poll()
            thread, worked = _work_thread(queue, runner, limit=4, concurrency=4)
            self.assertTrue(wait_for_notice(root, "a_fast", timeout_s=0.4))
            self.assertTrue(wait_for_notice(root, "c_refill", timeout_s=0.4))
            self.assertTrue(wait_for_notice(root, "d_refill", timeout_s=0.4))
            self.assertFalse((root / "notices" / "b_slow.json").exists())
            second_poll = queue.poll(after_event_id=first_poll["newest_event_id"])
            self.assertIn("completed", [event["event_type"] for event in second_poll["events"]])
            _assert_done(self, thread, worked, 4)
            self.assertEqual(worked["claimed_count"], 4)
            self.assertEqual(worked["completed_count"], 4)
            self.assertEqual(worked["batch_dispatch_count"], 4)
            self.assertEqual(worked["batch_dispatch_mode"], "per_request")
            self.assertEqual(set(runner.one_calls), {"a_fast", "b_slow", "c_refill", "d_refill"})
            self.assertEqual(runner.batch_calls, [])

    def test_batch_capable_model_worker_fills_batch_across_batch_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            requests = [
                make_request("small-a", output_tokens=128),
                make_request("large-a", output_tokens=2048),
                make_prefixed_request("prefixed-a", "prefix-b"),
                make_request("small-b", output_tokens=128),
            ]
            queue.submit_requests(requests=requests, registry=registry, batch_id="batch-a")
            runner = BatchCapableDelayedRunner({})
            worked = queue.work(registry=registry, runner=runner, limit=4, concurrency=4, lease_ttl_s=5, heartbeat_interval_s=0.05)
            self.assertEqual(worked["claimed_count"], 4)
            self.assertEqual(worked["completed_count"], 4)
            self.assertEqual(worked["batch_dispatch_count"], 4)
            self.assertEqual(worked["batch_dispatch_mode"], "per_request")
            self.assertEqual(len(worked["groups"]), 3)
            self.assertEqual(set(runner.one_calls), {"small-a", "large-a", "prefixed-a", "small-b"})
            self.assertEqual(runner.batch_calls, [])

    def test_batch_worker_late_binds_unassigned_model_refill_to_active_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            registry = ProfileRegistry.load(PROFILES)
            queue.submit_requests(requests=[make_request("bound")], registry=registry, topology=SparkTopology.load(TOPOLOGY), batch_id="bound-batch")
            queue.submit_requests(requests=[make_request("loose")], registry=registry, batch_id="loose-batch")
            runner = BatchCapableDelayedRunner({})
            worked = queue.work(registry=registry, runner=runner, node_id="spark0", node_profile_ids=_node_profile_ids("spark0"), limit=2, concurrency=2, lease_ttl_s=5, heartbeat_interval_s=0.05)
            self.assertEqual(worked["claimed_count"], 2)
            self.assertEqual(worked["completed_count"], 2)
            self.assertEqual(queue.status(request_id="loose")["selected_node_id"], "spark0")
            self.assertEqual(set(runner.one_calls), {"bound", "loose"})
            self.assertEqual(runner.batch_calls, [])

    def test_cpu_service_jobs_use_same_durable_queue_and_notices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = InferenceQueue(root)
            submitted = queue.submit_cpu_requests(
                service="text_metrics",
                items=[{"custom_id": "cpu-a", "text": "one two"}, {"custom_id": "cpu-b", "text": "three"}],
                batch_id="cpu-batch",
                priority=1,
            )
            self.assertEqual(submitted["selected_services"], {"text_metrics": 2})
            self.assertEqual(submitted["priority_counts"], {"1": 2})
            self.assertEqual(queue.status(request_id="cpu-a")["priority"], 1)
            worked = queue.work(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), limit=2, concurrency=1)
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

    def test_prefix_warm_groups_shared_prefix_on_same_lane(self) -> None:
        class WarmRunner:
            def __init__(self) -> None:
                self.calls: list[tuple[InferenceRequest, str | None]] = []

            def run_one_on_node(self, request: InferenceRequest, profile, node_id: str | None) -> dict:
                self.calls.append((request, node_id))
                return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text="warm")

        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            requests = [make_request(f"r{i}") for i in range(10)]
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
                requests=[make_request(f"r{i}") for i in range(10)],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            first = queue.warm_prefixes(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", min_group_size=2)
            second = queue.warm_prefixes(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), node_id="spark0", min_group_size=2)
            self.assertEqual(first["warmed_count"], 1)
            self.assertEqual(second["warmed_count"], 0)
            self.assertEqual(second["skipped_count"], 1)

    def test_prefix_warm_limit_advances_past_already_warm_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            requests = [make_prefixed_request(f"r{i}", f"prefix-{i}") for i in range(4)]
            queue.submit_requests(requests=requests, registry=ProfileRegistry.load(PROFILES), batch_id="batch-a")
            first = queue.warm_prefixes(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), min_group_size=1, max_groups=2)
            second = queue.warm_prefixes(registry=ProfileRegistry.load(PROFILES), runner=FakeRunner(), min_group_size=1, max_groups=2)
            self.assertEqual(first["warmed_count"], 2)
            self.assertEqual(first["deferred_count"], 2)
            self.assertEqual(second["skipped_count"], 2)
            self.assertEqual(second["warmed_count"], 2)
            self.assertEqual(second["deferred_count"], 0)

    def test_prefix_warm_can_replicate_group_to_all_resident_nodes(self) -> None:
        class WarmRunner:
            def __init__(self) -> None:
                self.nodes: list[str | None] = []
                self.batch_sizes: list[int] = []

            def run_many_on_node(self, requests: list[InferenceRequest], profile, node_id: str | None, *, concurrency: int = 1) -> dict[str, dict]:
                self.nodes.append(node_id)
                self.batch_sizes.append(len(requests))
                return {request.request_id: make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text="warm") for request in requests}

        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            queue.submit_requests(
                requests=[make_request(f"r{i}") for i in range(10)],
                registry=ProfileRegistry.load(PROFILES),
                topology=SparkTopology.load(TOPOLOGY),
                batch_id="batch-a",
            )
            runner = WarmRunner()
            report = queue.warm_prefixes(
                registry=ProfileRegistry.load(PROFILES),
                runner=runner,
                topology=SparkTopology.load(TOPOLOGY),
                min_group_size=1,
                concurrency=8,
                all_resident_nodes=True,
            )
            self.assertEqual(report["warmed_count"], 5)
            self.assertEqual(sorted(runner.nodes), ["spark0", "spark1", "spark2", "spark3", "spark6"])
            self.assertEqual(runner.batch_sizes, [1, 1, 1, 1, 1])
            self.assertEqual({group["skeleton_hash"] for group in report["groups"]}, {"prefix-a"})


if __name__ == "__main__":
    unittest.main()
