from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer import sparkrunner_adapter

ROOT = Path(__file__).resolve().parents[1]


class SparkRunnerQueueAdapterTests(unittest.TestCase):
    def test_adapter_runs_sparkrunner_contract_through_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requests = root / "requests.jsonl"
            responses = root / "responses.jsonl"
            requests.write_text(json.dumps({"custom_id": "c:1", "prompt": "return ok", "max_tokens": 8}) + "\n", encoding="utf-8")
            rc = sparkrunner_adapter.main(
                [
                    "--input", str(requests),
                    "--output", str(responses),
                    "--queue-dir", str(root / "queue"),
                    "--profiles-dir", str(ROOT / "profiles" / "models"),
                    "--topology", str(ROOT / "profiles" / "topology" / "static_sparks.json"),
                    "--model", "qwen",
                    "--runner", "fake",
                    "--timeout-s", "30",
                ]
            )
            self.assertEqual(rc, 0)
            rows = [json.loads(line) for line in responses.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["custom_id"], "c:1")
        self.assertEqual(rows[0]["model"], "qwen")
        self.assertIn("fake response", rows[0]["text"])

    def test_adapter_can_emit_raw_inference_results_for_direct_diamond_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            requests = root / "requests.jsonl"
            responses = root / "responses.jsonl"
            requests.write_text(json.dumps({"custom_id": "diamond", "prompt": "source", "job_class": "atom_edit"}) + "\n", encoding="utf-8")
            sparkrunner_adapter.main(
                [
                    "--input", str(requests),
                    "--output", str(responses),
                    "--queue-dir", str(root / "queue"),
                    "--profiles-dir", str(ROOT / "profiles" / "models"),
                    "--topology", str(ROOT / "profiles" / "topology" / "static_sparks.json"),
                    "--model", "qwen",
                    "--runner", "fake",
                    "--response-format", "inference",
                ]
            )
            row = json.loads(responses.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["format"], "ds4-inference-result-v1")
        self.assertEqual(row["status"], "completed")


if __name__ == "__main__":
    unittest.main()
