import tempfile
import unittest
from pathlib import Path

from scripts import build_small_model_throughput_addendum as addendum
from scripts.run_small_model_qualification_batch import write_json


def record(model_id: str, status: str = "passed", mean_tok_s: float | None = 8.0, median_tok_s: float | None = 7.0) -> dict:
    aggregate = {"prompt_count": 4, "pass_count": 4, "pass_rate": 1.0, "p95_latency_ms": 100.0}
    if mean_tok_s is not None:
        aggregate["mean_tok_s"] = mean_tok_s
    if median_tok_s is not None:
        aggregate["median_tok_s"] = median_tok_s
    return {
        "format": "small-model-qualification-v1",
        "model_id": model_id,
        "status": status,
        "serve_backend": "llama.cpp",
        "aggregate_metrics": aggregate,
        "cost_proxy_estimate": {"score": 2.0, "basis": "unit"},
        "per_prompt_results": [{"latency_ms": 10.0}, {"latency_ms": 30.0}],
    }


class SmallModelThroughputAddendumTest(unittest.TestCase):
    def test_derives_tok_s_for_passed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = root / "record.json"
            write_json(rec, record("fast", mean_tok_s=12.0, median_tok_s=11.0))
            built = addendum.build_addendum([rec], root, "unit")
            self.assertEqual(built["format"], "small-model-throughput-addendum-v1")
            self.assertEqual(built["passed_record_count"], 1)
            self.assertEqual(built["derived_passed_record_count"], 1)
            self.assertEqual(built["records"][0]["mean_tok_s"], 12.0)
            self.assertEqual(built["records"][0]["p50_latency_ms"], 20.0)
            self.assertFalse(addendum.validate_addendum(built))

    def test_documents_missing_throughput_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = root / "record.json"
            write_json(rec, record("missing", mean_tok_s=None))
            built = addendum.build_addendum([rec], root, "unit")
            self.assertEqual(built["derived_passed_record_count"], 0)
            self.assertEqual(built["cannot_derive_passed_record_count"], 1)
            self.assertEqual(built["records"][0]["cannot_derive_reason"], "missing_mean_tok_s")
            self.assertIn("no passed records have derived tok/s", addendum.validate_addendum(built))

    def test_rankings_are_non_empty_when_derived_records_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "slow.json", record("slow", mean_tok_s=2.0, median_tok_s=2.0))
            write_json(root / "fast.json", record("fast", mean_tok_s=20.0, median_tok_s=19.0))
            built = addendum.build_addendum([root], root, "unit")
            self.assertEqual(built["top_by_mean_tok_s"][0]["model_id"], "fast")
            self.assertEqual(built["top_by_cost_proxy"][0]["model_id"], "fast")
            self.assertTrue(built["coverage"]["passed_records_accounted_for"])

    def test_failed_records_do_not_block_passed_record_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "passed.json", record("passed"))
            write_json(root / "failed.json", record("failed", status="failed", mean_tok_s=None, median_tok_s=None))
            built = addendum.build_addendum([root], root, "unit")
            self.assertEqual(built["record_count"], 2)
            self.assertEqual(built["passed_record_count"], 1)
            self.assertEqual(built["derived_passed_record_count"], 1)
            self.assertFalse(addendum.validate_addendum(built))


if __name__ == "__main__":
    unittest.main()
