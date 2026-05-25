from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from ds4_infer import sparkrunner_adapter
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]


class DelayedRunner:
    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays

    def run_one_on_node(self, request, profile, node_id):
        time.sleep(self.delays.get(request.request_id, 0.0))
        return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=f"delayed {request.request_id}")


def wait_for_rows(path: Path, count: int, timeout_s: float = 1.0) -> list[dict]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists():
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(rows) >= count:
                return rows
        time.sleep(0.01)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, *records: dict) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def _adapter_args(root: Path, requests: Path, responses: Path, *extra: str, queue_dir: Path | None = None) -> list[str]:
    return [
        "--input", str(requests),
        "--output", str(responses),
        "--queue-dir", str(queue_dir or root / "queue"),
        "--profiles-dir", str(ROOT / "profiles" / "models"),
        "--topology", str(ROOT / "profiles" / "topology" / "static_sparks.json"),
        *extra,
    ]


class SparkRunnerQueueAdapterTests(unittest.TestCase):
    def test_adapter_runs_sparkrunner_contract_through_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requests = root / "requests.jsonl"
            responses = root / "responses.jsonl"
            _write_jsonl(requests, {"custom_id": "c:1", "prompt": "return ok", "max_tokens": 8})
            rc = sparkrunner_adapter.main(_adapter_args(root, requests, responses, "--model", "qwen", "--runner", "fake", "--timeout-s", "30"))
            self.assertEqual(rc, 0)
            rows = [json.loads(line) for line in responses.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["custom_id"], "c:1")
        self.assertEqual(rows[0]["model"], "qwen")
        self.assertIn("fake response", rows[0]["text"])

    def test_adapter_works_only_its_submitted_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            queue_dir = root / "queue"
            queue = InferenceQueue(queue_dir)
            registry = ProfileRegistry.load(ROOT / "profiles" / "models")
            topology = SparkTopology.load(ROOT / "profiles" / "topology" / "static_sparks.json")
            queue.submit_requests(requests=[_stale_request("aaa-stale")], registry=registry, topology=topology, batch_id="stale")
            requests = root / "requests.jsonl"
            responses = root / "responses.jsonl"
            _write_jsonl(requests, {"custom_id": "fresh", "prompt": "return ok", "max_tokens": 8})
            rc = sparkrunner_adapter.main(
                _adapter_args(root, requests, responses, "--model", "qwen", "--runner", "fake", "--work-limit", "1", "--timeout-s", "30", queue_dir=queue_dir)
            )
            rows = [json.loads(line) for line in responses.read_text(encoding="utf-8").splitlines()]
            stale_status = queue.status(request_id="aaa-stale")
        self.assertEqual(rc, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["custom_id"], "fresh")
        self.assertEqual(stale_status["state"], "queued")

    def test_adapter_can_emit_raw_inference_results_for_direct_diamond_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requests = root / "requests.jsonl"
            responses = root / "responses.jsonl"
            _write_jsonl(requests, {"custom_id": "diamond", "prompt": "source", "job_class": "atom_edit"})
            sparkrunner_adapter.main(
                _adapter_args(root, requests, responses, "--model", "qwen", "--runner", "fake", "--response-format", "inference")
            )
            row = json.loads(responses.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["format"], "ds4-inference-result-v1")
        self.assertEqual(row["status"], "completed")

    def test_adapter_appends_each_response_as_soon_as_it_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requests = root / "requests.jsonl"
            responses = root / "responses.jsonl"
            _write_jsonl(requests, {"custom_id": "slow", "prompt": "slow"}, {"custom_id": "fast", "prompt": "fast"})
            result: dict[str, int] = {}
            args = _adapter_args(root, requests, responses, "--model", "ds4v", "--runner", "fake", "--work-limit", "2", "--concurrency", "2", "--timeout-s", "10")
            with mock.patch.object(sparkrunner_adapter, "make_runner", return_value=DelayedRunner({"slow": 1.5, "fast": 0.05})):
                thread = threading.Thread(target=lambda: result.update({"rc": sparkrunner_adapter.main(args)}))
                thread.start()
                try:
                    rows = wait_for_rows(responses, 1, timeout_s=1.0)
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["custom_id"], "fast")
                    self.assertTrue(thread.is_alive())
                finally:
                    thread.join(timeout=3.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result["rc"], 0)
            rows = [json.loads(line) for line in responses.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["custom_id"] for row in rows], ["fast", "slow"])


def _stale_request(request_id: str) -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": "efficient",
            "chat": False,
            "immediate": False,
            "job_class": "atom_edit",
            "max_output_tokens": 8,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": {"suffix": "stale"},
            "output_contract": {"format": "text"},
        }
    )


if __name__ == "__main__":
    unittest.main()
