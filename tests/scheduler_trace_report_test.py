import json
import os
import tempfile
import unittest

from sim.scheduler import trace_report


class SchedulerTraceReportTest(unittest.TestCase):
    def test_runtime_trace_report_bundle_writes_files_and_canonicalizes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            in_jsonl = os.path.join(td, "runtime.log.jsonl")
            out_dir = os.path.join(td, "out")

            rows = [
                {"type": "meta", "meta": {"num_experts": 2}},
                {"dt_ms": 0.0, "cls": "batch", "route": {"candidates": [0, 1]}, "mtp": {"accepted": 1, "rejected": 1}},
                {"dt_ms": 1.0, "cls": "batch", "route": {"candidates": [1, 0]}, "mtp": {"accepted": 0, "rejected": 2}},
            ]
            with open(in_jsonl, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")

            bundle = trace_report.build_runtime_trace_report_bundle(
                in_jsonl=in_jsonl,
                out_dir=out_dir,
                time_mode="dt_ms",
                input_format="runtime",
                non_route_policy="error",
                mtp_draft_len=-1,
            )
            self.assertTrue(os.path.isdir(bundle.paths.out_dir))
            self.assertTrue(os.path.isfile(bundle.paths.canonical_trace_jsonl))
            self.assertTrue(os.path.isfile(bundle.paths.report_json))
            self.assertTrue(os.path.isfile(bundle.paths.report_md))

            with open(bundle.paths.canonical_trace_jsonl, "r", encoding="utf-8") as f:
                canon_lines = f.read().splitlines()
            self.assertGreaterEqual(len(canon_lines), 2)
            meta = json.loads(canon_lines[0])
            self.assertEqual(meta.get("type"), "meta")
            payload = meta.get("meta", {})
            self.assertIsInstance(payload, dict)
            self.assertEqual(payload.get("canonicalized_trace"), True)
            self.assertEqual(payload.get("mtp_draft_len"), 2)

            with open(bundle.paths.report_json, "r", encoding="utf-8") as f:
                report = json.loads(f.read())
            evidence = report.get("evidence", {})
            self.assertIsInstance(evidence, dict)
            mtp = evidence.get("mtp", {})
            self.assertIsInstance(mtp, dict)
            self.assertEqual(mtp.get("present"), True)

            with open(bundle.paths.report_md, "r", encoding="utf-8") as f:
                md = f.read()
            self.assertIn("Scheduler Simulator Runtime Trace Report", md)
