import tempfile
import unittest
from pathlib import Path

from scripts import run_small_model_qualification_batch as batch


class SmallModelQualificationBatchTest(unittest.TestCase):
    def test_failure_record_for_unsupported_backend(self) -> None:
        model = {"model_id": "hf-test", "model_path": "/models/hf-test", "serve_backend": "unknown", "hardware_node": "spark2"}
        record = batch.qualify_or_fail(model, {"eval_set_id": "unit", "prompts": []}, "spark2", "/opt/llama-cli", 1.0)
        self.assertEqual(record["format"], "small-model-qualification-v1")
        self.assertEqual(record["status"], "failed")
        self.assertIn("unsupported serve_backend", record["failure_reason"])

    def test_summary_has_required_rankings_and_wall_clock(self) -> None:
        records = [
            {
                "model_id": "a",
                "status": "passed",
                "aggregate_metrics": {"pass_rate": 1.0, "mean_tok_s": 2.0},
                "cost_proxy_estimate": {"score": 3.0},
            },
            {
                "model_id": "b",
                "status": "failed",
                "failure_reason": "not wired",
                "aggregate_metrics": {"pass_rate": 0.0, "mean_tok_s": 0.0},
                "cost_proxy_estimate": {"score": 1.0},
            },
        ]
        summary = batch.build_summary(records, {"hardware_node": "spark2", "model_count": 2}, Path("out"), 1.0)
        self.assertEqual(summary["format"], "small-model-qualification-batch-v1")
        self.assertEqual(summary["record_count"], 2)
        self.assertEqual(summary["failure_count"], 1)
        self.assertEqual(summary["top_by_pass_rate"][0]["model_id"], "a")
        self.assertEqual(summary["top_by_cost_proxy"][0]["model_id"], "b")
        self.assertGreater(summary["wall_clock_seconds"], 0.0)

    def test_results_doc_lists_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.md"
            summary = {
                "batch_timestamp": "2026-05-21T12:00:00Z",
                "hardware_node": "spark2",
                "record_count": 1,
                "inventory_model_count": 1,
                "failure_count": 1,
                "wall_clock_seconds": 1.0,
                "top_by_pass_rate": [{"model_id": "a", "pass_rate": 0.0}],
                "top_by_mean_tok_s": [{"model_id": "a", "mean_tok_s": 0.0}],
                "top_by_cost_proxy": [{"model_id": "a", "cost_proxy": 1.0}],
                "failed_models": [{"model_id": "a", "reason": "not wired"}],
            }
            batch.write_results_doc(path, summary)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Failed Models", text)
            self.assertIn("not wired", text)

    def test_model_id_filter_rejects_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inventory = {"models": [{"model_id": "present", "serve_backend": "transformers", "hardware_node": "spark2"}]}
            eval_set = {"eval_set_id": "unit", "prompts": []}
            with self.assertRaises(ValueError):
                batch.run_batch(inventory, eval_set, Path(tmp), "spark2", "/opt/llama-cli", 1.0, model_ids=["missing"])


if __name__ == "__main__":
    unittest.main()
