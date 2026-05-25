from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ds4_chat.cli import QueueChatModel
from ds4_infer.schemas import InferenceRequest

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


def stale_chat_request() -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": "stale-chat",
            "capability": "efficient",
            "chat": True,
            "immediate": True,
            "job_class": "summary",
            "max_output_tokens": 16,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": {"messages": [{"role": "user", "content": "stale"}], "prompt": "stale"},
            "output_contract": {"format": "text"},
        }
    )


class QueueChatBatchScopeTests(unittest.TestCase):
    def test_queue_chat_model_works_only_current_chat_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model = QueueChatModel(
                queue_dir=str(Path(temp_dir) / "queue"),
                profiles_dir=str(PROFILES),
                topology=str(TOPOLOGY),
                model_alias="qwen",
                runner="fake",
                timeout_s=30,
                max_tokens=16,
                temperature=0.0,
            )
            model.queue.submit_requests(requests=[stale_chat_request()], registry=model.registry, topology=model.topology, batch_id="stale")
            message = model.next_message([{"role": "user", "content": "fresh"}])
            stale_status = model.queue.status(request_id="stale-chat")
        self.assertEqual(message["role"], "assistant")
        self.assertIn("fake response", message["content"])
        self.assertEqual(stale_status["state"], "queued")


if __name__ == "__main__":
    unittest.main()
