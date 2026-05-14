import json
import os
import tempfile
import unittest
from array import array

from sim.scheduler import topk_dump_report


def _write_i32_dump(path: str, rows: list[list[int]]) -> None:
    data = array("i")
    for row in rows:
        for v in row:
            data.append(int(v))
    with open(path, "wb") as f:
        f.write(data.tobytes())


class SchedulerTopkDumpBundleTest(unittest.TestCase):
    def test_build_bundle_writes_trace_and_reports(self) -> None:
        topk = 2
        layers = [
            [[0, 1], [0, 1], [2, 3], [4, 5]],
            [[0, 2], [1, 3], [2, 4], [3, 5]],
        ]
        with tempfile.TemporaryDirectory() as dump_dir:
            _write_i32_dump(os.path.join(dump_dir, "ffn_moe_topk-0_pos0.i32"), layers[0])
            _write_i32_dump(os.path.join(dump_dir, "ffn_moe_topk-1_pos0.i32"), layers[1])
            with tempfile.TemporaryDirectory() as out_root:
                out_dir = os.path.join(out_root, "bundle")
                out = topk_dump_report.build_ds4_topk_dump_trace_report_bundle(
                    dump_dir,
                    out_dir=out_dir,
                    pos=0,
                    topk=topk,
                    seed=123,
                    sample_mode="sequential",
                    time_mode="dt_ms",
                    arrival_rate_tps=1000.0,
                    batch_size=2,
                    interactive_prob=0.0,
                    trace_speedup=1.0,
                    expert_queue_max=16,
                    expert_parallelism=1,
                    service_ms=1.0,
                    starvation_ms=10.0,
                    mtp_draft_len=-1,
                    probe_expert_queueing=True,
                    probe_experts=8,
                    probe_batches=(4, 100),
                    probe_trials=4,
                    probe_expert_transitions=True,
                    probe_transition_sparks=2,
                    probe_transition_logical_lanes=8,
                    probe_transition_top_masses=(1, 2, 4),
                    probe_transition_top_next=4,
                )

                trace_path = str(out.get("trace_path", ""))
                report_json_path = str(out.get("report_json_path", ""))
                report_md_path = str(out.get("report_md_path", ""))
                meta_path = str(out.get("bundle_meta_path", ""))
                self.assertTrue(os.path.isfile(trace_path))
                self.assertTrue(os.path.isfile(report_json_path))
                self.assertTrue(os.path.isfile(report_md_path))
                self.assertTrue(os.path.isfile(meta_path))

                with open(report_json_path, "r", encoding="utf-8") as f:
                    report = json.loads(f.read())
                self.assertEqual(report.get("name"), "ds4_topk_dump_route_only_ablation")
                trace_summary = report.get("trace_summary", {})
                self.assertIsInstance(trace_summary, dict)
                inferred = trace_summary.get("inferred", {})
                self.assertIsInstance(inferred, dict)
                self.assertEqual(inferred.get("num_layers"), 2)

                with open(report_md_path, "r", encoding="utf-8") as f:
                    md = f.read()
                self.assertIn("Scheduler Simulator Runtime Trace Report", md)
                self.assertIn("topk_dump_probe: present", md)
                self.assertIn("topk_transition_probe: present", md)

                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.loads(f.read())
                self.assertEqual(meta.get("type"), "ds4_topk_dump_trace_report_bundle")
                dump_meta = meta.get("dump_meta", {})
                self.assertIsInstance(dump_meta, dict)
                self.assertEqual(dump_meta.get("topk"), topk)
                args = meta.get("args", {})
                self.assertIsInstance(args, dict)
                self.assertEqual(args.get("probe_transition_sparks"), 2)
