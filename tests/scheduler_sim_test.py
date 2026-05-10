import unittest
import tempfile
import os
import dataclasses
import contextlib
import io
import json
import sys

from sim.scheduler import scheduler_sim


class SchedulerSimTest(unittest.TestCase):
    def test_synthetic_trace_deterministic(self) -> None:
        cfg = scheduler_sim.TraceConfig(
            num_tokens=10,
            num_experts=8,
            num_candidates=4,
            interactive_prob=0.25,
            arrival_rate_tps=1000.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        t0 = scheduler_sim.generate_synthetic_trace(cfg)
        t1 = scheduler_sim.generate_synthetic_trace(cfg)
        self.assertEqual(t0, t1)
        self.assertEqual(len(t0), 10)
        self.assertTrue(all(r.t_ms >= 0.0 for r in t0))
        self.assertTrue(all(len(r.candidates) == 4 for r in t0))

    def test_synthetic_trace_num_layers_emits_layers_and_union_candidates(self) -> None:
        cfg = scheduler_sim.TraceConfig(
            num_tokens=8,
            num_experts=8,
            num_candidates=3,
            interactive_prob=0.0,
            arrival_rate_tps=1000.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
            num_layers=3,
        )
        t0 = scheduler_sim.generate_synthetic_trace(cfg)
        t1 = scheduler_sim.generate_synthetic_trace(cfg)
        self.assertEqual(t0, t1)
        self.assertEqual(len(t0), 8)
        for r in t0:
            self.assertIsNotNone(r.layers)
            self.assertEqual(len(r.layers or ()), 3)
            union: list[int] = []
            seen: set[int] = set()
            for lr in r.layers or ():
                self.assertEqual(len(lr.candidates), 3)
                for c in lr.candidates:
                    if c not in seen:
                        union.append(c)
                        seen.add(c)
            self.assertEqual(r.candidates, tuple(union))

    def test_hotset_trace_deterministic_and_rotates(self) -> None:
        cfg = scheduler_sim.HotsetTraceConfig(
            num_tokens=4,
            num_experts=8,
            num_candidates=2,
            interactive_prob=0.0,
            arrival_rate_tps=1000.0,
            burst_prob=0.0,
            burst_scale=1.0,
            hotset_size=2,
            hotset_bias=1.0,
            hotset_rotate_every_tokens=1,
            seed=123,
        )
        t0 = scheduler_sim.generate_hotset_trace(cfg)
        t1 = scheduler_sim.generate_hotset_trace(cfg)
        self.assertEqual(t0, t1)
        self.assertEqual(len(t0), 4)
        self.assertNotEqual(set(t0[0].candidates), set(t0[1].candidates))

    def test_trace_jsonl_layers_run_sequentially_across_experts(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(
                json.dumps(
                    {
                        "t_ms": 0.0,
                        "cls": "batch",
                        "layers": [{"candidates": [0]}, {"candidates": [1]}],
                    }
                )
            )
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path)
            self.assertEqual(len(trace), 1)
            self.assertIsNotNone(trace[0].layers)
            cfg = scheduler_sim.SimConfig(
                num_experts=2,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=1.0,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(len(m.token_lat_ms_batch), 1)
            self.assertAlmostEqual(m.token_lat_ms_batch[0], 2.0, places=6)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_partial_admit_any_layer_counts_layer_drops(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "layers": [{"candidates": [0]}, {"candidates": [1]}]}))
            f.write("\n")
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [1], "cost_scale": 5.0}))
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path)
            cfg = scheduler_sim.SimConfig(
                num_experts=2,
                expert_parallelism=1,
                expert_queue_max=1,
                service_ms=1.0,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.partial_admit_tokens, 0)
            self.assertEqual(m.partial_admit_any_layer_tokens, 1)
            self.assertEqual(m.skipped_stages_backpressure, 1)
            self.assertEqual(m.skipped_stages_backpressure_batch, 1)
            self.assertEqual(m.skipped_stages_backpressure_verify, 1)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_jsonl_meta_record_ignored_and_collected(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"type": "meta", "meta": {"runtime_commit": "abc123", "num_layers": 2}}))
            f.write("\n")
            f.write(json.dumps({"t_ms": 0.0, "cls": "interactive", "candidates": [0]}))
            f.write("\n")
        try:
            meta: dict[str, object] = {}
            trace = scheduler_sim.load_trace_jsonl(tmp_path, meta_out=meta)
            self.assertEqual(len(trace), 1)
            self.assertEqual(meta.get("runtime_commit"), "abc123")
            self.assertEqual(meta.get("num_layers"), 2)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_jsonl_stdin_dash_loads(self) -> None:
        payload = json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0, 1]}) + "\n"
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            trace = scheduler_sim.load_trace_jsonl("-")
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0].candidates, (0, 1))
        finally:
            sys.stdin = old_stdin

    def test_trace_jsonl_non_route_default_errors(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"type": "decode", "t_ms": 0.0, "decode_ms": 0.01}))
            f.write("\n")
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0]}))
            f.write("\n")
        try:
            with self.assertRaises(ValueError):
                scheduler_sim.load_trace_jsonl(tmp_path)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_jsonl_non_route_skip_ignores_mixed_logs(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"type": "decode", "t_ms": 0.0, "decode_ms": 0.01}))
            f.write("\n")
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0]}))
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path, non_route_policy="skip")
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0].candidates, (0,))
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_canonicalize_jsonl_stdout_dash_reads_stdin(self) -> None:
        payload = json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0], "accepted_mtp": 1}) + "\n"
        buf = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(
                    ["--trace-jsonl", "-", "--canonicalize-trace-jsonl", "-", "--trace-time-mode", "t_ms", "--mtp-draft-len", "2", "--json"]
                )
            self.assertEqual(rc, 0)
        finally:
            sys.stdin = old_stdin
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip() != ""]
        self.assertGreaterEqual(len(lines), 2)
        meta = json.loads(lines[0])
        self.assertEqual(meta.get("type"), "meta")
        first_route = json.loads(lines[1])
        self.assertEqual(first_route.get("mtp_accept_len"), 2)

    def test_summary_json_outputs_concise_metrics(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = scheduler_sim.main(["--num-tokens", "2000", "--summary-json"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertIn("summary", out)
        summary = out["summary"]
        self.assertIsInstance(summary, dict)
        for k in ("makespan_ms", "token_throughput_tps", "task_throughput_tps", "drop_frac_tokens"):
            self.assertIn(k, summary)

    def test_summary_json_compare_omits_full_metrics(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = scheduler_sim.main(["--num-tokens", "2000", "--summary-json", "--compare", "mtp_off:{\"mtp_draft_len\":0}"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertIn("baseline", out)
        self.assertIn("variants", out)
        self.assertNotIn("metrics", out["baseline"])
        self.assertIn("summary", out["baseline"])
        self.assertIn("mtp_off", out["variants"])
        self.assertNotIn("metrics", out["variants"]["mtp_off"])
        self.assertIn("delta_vs_baseline", out["variants"]["mtp_off"])

    def test_infer_num_experts_from_trace_uses_meta(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 7))]
        meta: dict[str, object] = {"num_experts": 10}
        self.assertEqual(scheduler_sim.infer_num_experts_from_trace(trace, meta), 10)

    def test_infer_num_experts_from_trace_falls_back_to_trace_range(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 9))]
        self.assertEqual(scheduler_sim.infer_num_experts_from_trace(trace), 10)

    def test_infer_mtp_draft_len_from_trace_uses_meta(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1))]
        meta: dict[str, object] = {"mtp_draft_len": 3}
        self.assertEqual(scheduler_sim.infer_mtp_draft_len_from_trace(trace, meta), 3)

    def test_infer_mtp_draft_len_from_trace_from_accepted_and_rejected(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), accepted_mtp=1, rejected_mtp=1),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), accepted_mtp=0, rejected_mtp=2),
        ]
        self.assertEqual(scheduler_sim.infer_mtp_draft_len_from_trace(trace), 2)

    def test_trace_replay_auto_num_experts_and_mtp_draft_len(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0, 7], "accepted_mtp": 1, "rejected_mtp": 1}))
            f.write("\n")
            f.write(json.dumps({"t_ms": 1.0, "cls": "batch", "candidates": [7, 0], "accepted_mtp": 2, "rejected_mtp": 0}))
            f.write("\n")
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", tmp_path, "--num-experts", "0", "--mtp-draft-len", "-1", "--service-ms", "0.01", "--json"])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue())
            self.assertEqual(out.get("expert_queue", {}).get("num_experts"), 8)
            self.assertEqual(out.get("mtp", {}).get("draft_len"), 2)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_canonicalize_jsonl_writes_meta_and_derives_t_ms_and_accept_len(self) -> None:
        in_path = ""
        out_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f_in:
            in_path = f_in.name
            f_in.write(json.dumps({"type": "meta", "meta": {"runtime_commit": "abc123"}}))
            f_in.write("\n")
            f_in.write(json.dumps({"dt_ms": 0.1, "cls": "batch", "candidates": [0, 7], "accepted_mtp": 1, "rejected_mtp": 1}))
            f_in.write("\n")
            f_in.write(json.dumps({"dt_ms": 0.2, "cls": "batch", "candidates": [7, 0], "accepted_mtp": 0, "rejected_mtp": 2}))
            f_in.write("\n")
        with tempfile.NamedTemporaryFile("w", delete=False) as f_out:
            out_path = f_out.name

        try:
            rc = scheduler_sim.main(
                [
                    "--trace-jsonl",
                    in_path,
                    "--trace-time-mode",
                    "dt_ms",
                    "--num-experts",
                    "0",
                    "--mtp-draft-len",
                    "-1",
                    "--canonicalize-trace-jsonl",
                    out_path,
                ]
            )
            self.assertEqual(rc, 0)

            with open(out_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip() != ""]
            self.assertGreaterEqual(len(lines), 3)

            meta_obj = json.loads(lines[0])
            self.assertEqual(meta_obj.get("type"), "meta")
            meta = meta_obj.get("meta") or {}
            self.assertEqual(meta.get("runtime_commit"), "abc123")
            self.assertEqual(meta.get("canonicalized_trace"), True)
            self.assertEqual(meta.get("num_experts"), 8)
            self.assertEqual(meta.get("mtp_draft_len"), 2)

            r0 = json.loads(lines[1])
            self.assertAlmostEqual(float(r0.get("t_ms")), 0.1, places=9)
            self.assertEqual(r0.get("mtp_accept_len"), 2)
            r1 = json.loads(lines[2])
            self.assertAlmostEqual(float(r1.get("t_ms")), 0.3, places=9)
            self.assertEqual(r1.get("mtp_accept_len"), 1)
        finally:
            for p in (in_path, out_path):
                if p != "" and os.path.exists(p):
                    os.unlink(p)

    def test_trace_derive_cost_scale_kv_tokens_p50_fills_missing_and_records_meta(self) -> None:
        in_path = ""
        out_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f_in:
            in_path = f_in.name
            f_in.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0], "kv_tokens": 10}))
            f_in.write("\n")
            f_in.write(json.dumps({"t_ms": 1.0, "cls": "batch", "candidates": [0], "kv_tokens": 20}))
            f_in.write("\n")
        with tempfile.NamedTemporaryFile("w", delete=False) as f_out:
            out_path = f_out.name

        try:
            rc = scheduler_sim.main(
                [
                    "--trace-jsonl",
                    in_path,
                    "--trace-time-mode",
                    "t_ms",
                    "--num-experts",
                    "0",
                    "--mtp-draft-len",
                    "0",
                    "--trace-derive-cost-scale",
                    "kv_tokens_p50",
                    "--canonicalize-trace-jsonl",
                    out_path,
                ]
            )
            self.assertEqual(rc, 0)

            with open(out_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip() != ""]
            self.assertGreaterEqual(len(lines), 3)
            meta_obj = json.loads(lines[0])
            meta = meta_obj.get("meta") or {}
            derived = meta.get("derived_cost_scale") or {}
            self.assertEqual(derived.get("mode"), "kv_tokens_p50")
            self.assertEqual(derived.get("field"), "kv_tokens")
            self.assertEqual(int(derived.get("filled") or 0), 2)

            r0 = json.loads(lines[1])
            r1 = json.loads(lines[2])
            self.assertAlmostEqual(float(r0.get("cost_scale")), 1.0, places=9)
            self.assertAlmostEqual(float(r1.get("cost_scale")), 2.0, places=9)
        finally:
            for p in (in_path, out_path):
                if p != "" and os.path.exists(p):
                    os.unlink(p)

    def test_adaptive_k_hits_min_and_max(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1, 2, 3),
            )
            for _ in range(50)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=4,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=10.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=2,
                k_max_interactive=4,
                k_min_batch=1,
                k_max_batch=4,
                q_low=0,
                q_high=10,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertGreaterEqual(len(m.chosen_k_batch), 1)
        self.assertEqual(min(m.chosen_k_batch), 1)
        self.assertEqual(max(m.chosen_k_batch), 4)

    def test_task_queue_wait_and_utilization_metrics_consistent(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.1,
                cls=scheduler_sim.LatencyClass.INTERACTIVE if (i % 2) == 0 else scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
            )
            for i in range(50)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=2,
                k_max_interactive=2,
                k_min_batch=2,
                k_max_batch=2,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.admitted_tasks, len(m.task_queue_wait_ms_interactive) + len(m.task_queue_wait_ms_batch))
        self.assertTrue(all(0.0 <= x <= 1.0 for x in m.mean_utilization_per_expert))
        self.assertTrue(all(0.0 <= x <= 1.0 for x in m.saturated_time_frac_per_expert))

    def test_expert_queue_reports_per_expert_starvation_fraction_and_max_wait(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for _i in range(3)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=10.0,
            starvation_ms=9.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.tasks_started_per_expert, [3])
        self.assertEqual(m.starved_tasks_started_per_expert, [2])
        self.assertAlmostEqual(m.max_task_queue_wait_ms_per_expert[0], 20.0, places=6)

        out = m.to_jsonable()
        q = out.get("expert_queue", {})
        self.assertAlmostEqual(q.get("starvation_task_frac", {}).get("p50", 0.0), (2.0 / 3.0), places=6)
        self.assertAlmostEqual(q.get("max_task_queue_wait_ms", {}).get("max", 0.0), 20.0, places=6)

    def test_backpressure_drops_tasks(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i),
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
            )
            for i in range(100)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=1,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=2,
                k_max_batch=2,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertGreater(m.dropped_tasks_backpressure, 0)

    def test_time_weighted_queue_depth_hilo_hist_present_and_nonzero(self) -> None:
        trace: list[scheduler_sim.TokenRoute] = []
        for i in range(20):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.INTERACTIVE if (i % 2) == 0 else scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                )
            )
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=5.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            pending_hist_max_depth=64,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(len(m.hi_queue_depth_hist), len(m.pending_depth_hist))
        self.assertEqual(len(m.lo_queue_depth_hist), len(m.pending_depth_hist))
        self.assertGreater(sum(m.hi_queue_depth_hist), 0.0)
        self.assertGreater(sum(m.lo_queue_depth_hist), 0.0)

    def test_backpressure_drops_tokens_and_excludes_latency(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
            )
            for i in range(100)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=1,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=2,
                k_max_batch=2,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertGreater(m.dropped_tokens_backpressure, 0)
        self.assertEqual(len(m.token_lat_ms_batch), m.admitted_tokens_batch)

    def test_expert_queue_reserve_interactive_keeps_headroom_under_batch_load(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,)),
        ]
        base = dict(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=2,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m_no_reserve = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, expert_queue_reserve_interactive=0), trace)
        m_reserve = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, expert_queue_reserve_interactive=1), trace)
        self.assertGreater(m_no_reserve.dropped_tokens_backpressure_interactive, 0)
        self.assertEqual(m_reserve.dropped_tokens_backpressure_interactive, 0)

    def test_k_signal_class_tasks_ignores_lo_inflight_for_interactive_queue(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=0.001, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(1,)),
        ]
        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        )
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            k_signal="class",
            pending_units="tasks",
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(len(m.pending_signal_interactive), 1)
        self.assertEqual(m.pending_signal_interactive[0], 0.0)
        self.assertEqual(len(m.chosen_k_interactive), 1)
        self.assertEqual(m.chosen_k_interactive[0], 4)

    def test_k_signal_candidates_ignores_unrelated_congestion(self) -> None:
        trace = []
        for i in range(50):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=float(i) * 0.001,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                )
            )
        trace.append(
            scheduler_sim.TokenRoute(
                t_ms=0.0025,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(1,),
            )
        )
        trace.sort(key=lambda r: r.t_ms)

        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=4,
            q_low=0,
            q_high=1,
        )
        cfg_global = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            k_signal="global",
        )
        cfg_candidates = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            k_signal="candidates",
        )
        mg = scheduler_sim.run_simulation(cfg_global, trace)
        mc = scheduler_sim.run_simulation(cfg_candidates, trace)
        idx = next(i for i, r in enumerate(trace) if r.candidates == (1,))
        self.assertLessEqual(mg.chosen_k_batch[idx], mc.chosen_k_batch[idx])
        self.assertGreater(mg.pending_signal_batch[idx], mc.pending_signal_batch[idx])

    def test_k_signal_class_ignores_other_class_queue_backlog(self) -> None:
        trace: list[scheduler_sim.TokenRoute] = []
        for i in range(50):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=float(i) * 0.001,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                )
            )
        trace.append(
            scheduler_sim.TokenRoute(
                t_ms=0.0025,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(1,),
            )
        )
        trace.sort(key=lambda r: r.t_ms)

        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=2,
        )
        base = dict(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
        )
        m_global = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, k_signal="global"), trace)
        m_class = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, k_signal="class"), trace)

        self.assertEqual(len(m_global.chosen_k_interactive), 1)
        self.assertEqual(len(m_class.chosen_k_interactive), 1)
        self.assertLessEqual(m_global.chosen_k_interactive[0], m_class.chosen_k_interactive[0])
        self.assertGreater(m_global.pending_signal_interactive[0], m_class.pending_signal_interactive[0])

    def test_k_scope_layer_uses_layer_local_congestion_for_chosen_k_total(self) -> None:
        trace: list[scheduler_sim.TokenRoute] = []
        for i in range(10):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=float(i) * 0.0001,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                    layers=(
                        scheduler_sim.LayerRoute(candidates=(0,)),
                        scheduler_sim.LayerRoute(candidates=(0,)),
                    ),
                )
            )
        trace.append(
            scheduler_sim.TokenRoute(
                t_ms=0.002,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1, 2, 3, 4),
                layers=(
                    scheduler_sim.LayerRoute(candidates=(0,)),
                    scheduler_sim.LayerRoute(candidates=(1, 2, 3, 4)),
                ),
            )
        )
        trace.sort(key=lambda r: r.t_ms)

        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=4,
            q_low=0,
            q_high=1,
        )
        base = dict(
            num_experts=5,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            k_mode="controller",
            k_signal="candidates",
        )
        cfg_token = scheduler_sim.SimConfig(**base, k_scope="token")
        cfg_layer = scheduler_sim.SimConfig(**base, k_scope="layer")

        m_token = scheduler_sim.run_simulation(cfg_token, trace)
        m_layer = scheduler_sim.run_simulation(cfg_layer, trace)
        idx = next(i for i, r in enumerate(trace) if r.candidates == (0, 1, 2, 3, 4))
        self.assertEqual(m_token.chosen_k_total_batch[idx], 2)
        self.assertEqual(m_layer.chosen_k_total_batch[idx], 5)

    def test_pending_units_work_lets_k_ignore_low_cost_inflight(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), cost_scale=0.01),
            scheduler_sim.TokenRoute(t_ms=0.1, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), cost_scale=0.01),
        ]
        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=2,
            q_low=0,
            q_high=1,
        )
        base = dict(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            service_base_ms=0.0,
            service_per_task_ms=100.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            k_signal="global",
        )
        m_tasks = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, pending_units="tasks"), trace)
        m_work = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, pending_units="work"), trace)
        self.assertEqual(m_tasks.chosen_k_batch[1], 1)
        self.assertEqual(m_work.chosen_k_batch[1], 2)
        self.assertGreater(m_tasks.pending_signal_batch[1], m_work.pending_signal_batch[1])

    def test_pending_work_metrics_time_weighted(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), cost_scale=2.0),
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), cost_scale=1.0),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            service_base_ms=0.0,
            service_per_task_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(len(m.mean_pending_work_per_expert), 1)
        self.assertAlmostEqual(m.max_pending_work_per_expert[0], 3.0, places=6)
        self.assertAlmostEqual(m.mean_pending_work_per_expert[0], (7.0 / 3.0), places=6)

    def test_compare_variants_reports_delta(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1, 2, 3),
            )
            for i in range(200)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=4,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=0.1,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=2,
                k_max_interactive=2,
                k_min_batch=2,
                k_max_batch=2,
                q_low=0,
                q_high=0,
            ),
            mtp_draft_len=2,
            mtp_accept_prob=1.0,
            mtp_accept_decay=1.0,
        )
        out = scheduler_sim.compare_simulation_variants(cfg, trace, [("mtp_off", {"mtp_draft_len": 0})])
        base_out = out["baseline"]
        var_out = out["variants"]["mtp_off"]
        self.assertGreater(base_out["summary"]["output_tokens"], var_out["summary"]["output_tokens"])
        self.assertLess(var_out["delta_vs_baseline"]["output_tokens"], 0.0)

    def test_mtp_draft_attempt_policy_stop_at_reject_reduces_draft_work(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i),
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                mtp_accept_len=1,
            )
            for i in range(50)
        ]
        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        )
        cfg_full = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=0.1,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            mtp_draft_len=4,
            mtp_accept_prob=0.5,
            mtp_accept_decay=1.0,
            mtp_draft_cost_scale=0.25,
            mtp_draft_attempt_policy="full",
        )
        cfg_stop = dataclasses.replace(cfg_full, mtp_draft_attempt_policy="stop_at_reject")
        m_full = scheduler_sim.run_simulation(cfg_full, trace)
        m_stop = scheduler_sim.run_simulation(cfg_stop, trace)
        self.assertEqual(m_full.mtp_draft_tokens_total, len(trace) * 4)
        self.assertEqual(m_stop.mtp_draft_tokens_total, len(trace) * 1)
        self.assertGreater(m_full.work_units_mtp_draft, m_stop.work_units_mtp_draft)
        self.assertAlmostEqual(m_full.work_units_mtp_draft, float(len(trace) * 4) * 0.25, places=6)
        self.assertAlmostEqual(m_stop.work_units_mtp_draft, float(len(trace) * 1) * 0.25, places=6)

    def test_starvation_counts_queue_wait(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0,),
            )
            for _ in range(10)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=10.0,
            starvation_ms=1.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertGreater(m.starved_tasks, 0)

    def test_trace_jsonl_replay_loads_and_sorts(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.2,"cls":"batch","candidates":[1,0]}\n')
                f.write('{"t_ms":0.0,"cls":"interactive","candidates":[0,1],"scores":[0.9,0.1]}\n')
            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual(len(trace), 2)
            self.assertEqual(trace[0].t_ms, 0.0)
            self.assertEqual(trace[0].cls, scheduler_sim.LatencyClass.INTERACTIVE)
            self.assertEqual(trace[1].cls, scheduler_sim.LatencyClass.BATCH)
            self.assertEqual(trace[0].scores, (0.9, 0.1))

            cfg = scheduler_sim.SimConfig(
                num_experts=2,
                expert_parallelism=1,
                expert_queue_max=10,
                service_ms=1.0,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.num_tokens, 2)
            self.assertGreater(m.makespan_ms, 0.0)
        finally:
            os.unlink(path)

    def test_trace_jsonl_extra_fields_parse_and_record_metrics(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"token_index":0,"cls":"interactive","candidates":[0,1],"kv_tokens":128,"expert_batch_size":4,"decode_ms":1.5}\n')
                f.write('{"t_ms":0.01,"token_index":1,"cls":"batch","candidates":[1,0],"kv_tokens":256,"expert_batch_size":8,"decode_ms":2.0}\n')
            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual([r.token_index for r in trace], [0, 1])
            self.assertEqual(trace[0].kv_tokens, 128)
            self.assertEqual(trace[1].kv_tokens, 256)
            self.assertEqual(trace[0].expert_batch_size, 4)
            self.assertEqual(trace[1].expert_batch_size, 8)

            cfg = scheduler_sim.SimConfig(
                num_experts=2,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=0.1,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.admitted_tokens_interactive, 1)
            self.assertEqual(m.admitted_tokens_batch, 1)
            self.assertEqual(m.trace_kv_tokens_interactive, [128.0])
            self.assertEqual(m.trace_kv_tokens_batch, [256.0])
            self.assertEqual(m.trace_expert_batch_size_interactive, [4.0])
            self.assertEqual(m.trace_expert_batch_size_batch, [8.0])
            mj = m.to_jsonable()
            self.assertEqual(mj["trace"]["kv_tokens"]["interactive"]["count"], 1)
            self.assertEqual(mj["trace"]["expert_batch_size"]["batch"]["count"], 1)
        finally:
            os.unlink(path)

    def test_trace_jsonl_dt_ms_time_mode_loads(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"dt_ms":0.0,"cls":"interactive","candidates":[0,1]}\n')
                f.write('{"dt_ms":0.25,"cls":"batch","candidates":[1,0]}\n')
            trace = scheduler_sim.load_trace_jsonl(path, time_mode="dt_ms")
            self.assertEqual(len(trace), 2)
            self.assertEqual(trace[0].t_ms, 0.0)
            self.assertAlmostEqual(trace[1].t_ms, 0.25, places=9)
        finally:
            os.unlink(path)

    def test_trace_speedup_scales_timestamps(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=10.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(1,)),
        ]
        scaled = scheduler_sim.scale_trace_speedup(trace, 2.0)
        self.assertEqual([r.t_ms for r in scaled], [0.0, 5.0])

    def test_trace_speedup_applies_in_trace_summary(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0]}\n')
                f.write('{"t_ms":10.0,"cls":"batch","candidates":[1]}\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", path, "--trace-speedup", "2", "--trace-summary", "--json"])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue().strip())
            self.assertEqual(out["t_ms"]["max"], 5.0)
        finally:
            os.unlink(path)

    def test_trace_jsonl_dt_ms_rejected_without_mode(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"dt_ms":0.0,"cls":"interactive","candidates":[0,1]}\n')
            with self.assertRaises(ValueError):
                scheduler_sim.load_trace_jsonl(path)
        finally:
            os.unlink(path)

    def test_trace_jsonl_duplicate_candidates_rejected(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0,0]}\n')
            with self.assertRaises(ValueError):
                scheduler_sim.load_trace_jsonl(path)
        finally:
            os.unlink(path)

    def test_trace_expert_id_out_of_range_rejected(self) -> None:
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(2,))]
        with self.assertRaises(ValueError) as ctx:
            scheduler_sim.run_simulation(cfg, trace)
        self.assertIn("out of range", str(ctx.exception))

    def test_write_trace_jsonl_roundtrip(self) -> None:
        trace = scheduler_sim.generate_synthetic_trace(
            scheduler_sim.TraceConfig(
                num_tokens=64,
                num_experts=8,
                num_candidates=4,
                interactive_prob=0.5,
                arrival_rate_tps=1000.0,
                burst_prob=0.0,
                burst_scale=1.0,
                zipf_alpha=1.1,
                seed=123,
            )
        )
        fd, path = tempfile.mkstemp(prefix="sched_trace_out_", suffix=".jsonl")
        try:
            os.close(fd)
            scheduler_sim.write_trace_jsonl(path, trace)
            loaded = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual(len(loaded), len(trace))
            self.assertEqual([r.t_ms for r in loaded], [r.t_ms for r in trace])
            self.assertEqual([r.cls for r in loaded], [r.cls for r in trace])
            self.assertEqual([r.candidates for r in loaded], [r.candidates for r in trace])
        finally:
            os.unlink(path)

    def test_trace_csv_replay_loads_and_sorts(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".csv")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("t_ms,cls,candidates,scores\n")
                f.write('0.2,batch,"[1,0]","[0.1,0.9]"\n')
                f.write('0.0,interactive,"[0,1]","[0.9,0.1]"\n')
            trace = scheduler_sim.load_trace_csv(path)
            self.assertEqual(len(trace), 2)
            self.assertEqual(trace[0].t_ms, 0.0)
            self.assertEqual(trace[0].cls, scheduler_sim.LatencyClass.INTERACTIVE)
            self.assertEqual(trace[1].cls, scheduler_sim.LatencyClass.BATCH)
            self.assertEqual(trace[0].scores, (0.9, 0.1))

            cfg = scheduler_sim.SimConfig(
                num_experts=2,
                expert_parallelism=1,
                expert_queue_max=10,
                service_ms=1.0,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.num_tokens, 2)
            self.assertGreater(m.makespan_ms, 0.0)
        finally:
            os.unlink(path)

    def test_trace_csv_dt_ms_time_mode_loads(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".csv")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("dt_ms,cls,candidates\n")
                f.write('0.0,interactive,"0 1"\n')
                f.write('0.25,batch,"1 0"\n')
            trace = scheduler_sim.load_trace_csv(path, time_mode="dt_ms")
            self.assertEqual(len(trace), 2)
            self.assertEqual(trace[0].t_ms, 0.0)
            self.assertAlmostEqual(trace[1].t_ms, 0.25, places=9)
        finally:
            os.unlink(path)

    def test_write_trace_csv_roundtrip(self) -> None:
        trace = scheduler_sim.generate_synthetic_trace(
            scheduler_sim.TraceConfig(
                num_tokens=64,
                num_experts=8,
                num_candidates=4,
                interactive_prob=0.5,
                arrival_rate_tps=1000.0,
                burst_prob=0.0,
                burst_scale=1.0,
                zipf_alpha=1.1,
                seed=123,
            )
        )
        fd, path = tempfile.mkstemp(prefix="sched_trace_out_", suffix=".csv")
        try:
            os.close(fd)
            scheduler_sim.write_trace_csv(path, trace)
            loaded = scheduler_sim.load_trace_csv(path)
            self.assertEqual(len(loaded), len(trace))
            self.assertEqual([r.t_ms for r in loaded], [r.t_ms for r in trace])
            self.assertEqual([r.cls for r in loaded], [r.cls for r in trace])
            self.assertEqual([r.candidates for r in loaded], [r.candidates for r in trace])
        finally:
            os.unlink(path)

    def test_trace_jsonl_k_and_k_mode_trace_override_controller(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0,1,2],"k":1}\n')

            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual(trace[0].k, 1)

            cfg_trace = scheduler_sim.SimConfig(
                num_experts=3,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=1.0,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=3,
                    k_max_interactive=3,
                    k_min_batch=3,
                    k_max_batch=3,
                    q_low=0,
                    q_high=0,
                ),
                k_mode="trace",
            )
            m_trace = scheduler_sim.run_simulation(cfg_trace, trace)
            self.assertEqual(m_trace.chosen_k_batch, [1])
            self.assertEqual(m_trace.admitted_tasks, 1)

            cfg_ctrl = dataclasses.replace(cfg_trace, k_mode="controller")
            m_ctrl = scheduler_sim.run_simulation(cfg_ctrl, trace)
            self.assertEqual(m_ctrl.chosen_k_batch, [3])
            self.assertEqual(m_ctrl.admitted_tasks, 3)
        finally:
            os.unlink(path)

    def test_k_mode_trace_requires_k_field(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1, 2))]
        cfg = scheduler_sim.SimConfig(
            num_experts=3,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            k_mode="trace",
        )
        with self.assertRaises(ValueError):
            scheduler_sim.run_simulation(cfg, trace)

    def test_trace_jsonl_scores_length_must_match_candidates(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"interactive","candidates":[0,1],"scores":[0.9]}\n')
            with self.assertRaises(ValueError):
                scheduler_sim.load_trace_jsonl(path)
        finally:
            os.unlink(path)

    def test_trace_jsonl_cost_scale_parses_and_affects_makespan(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"cost_scale":2.0}\n')
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"cost_scale":2.0}\n')
            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual(trace[0].cost_scale, 2.0)

            cfg = scheduler_sim.SimConfig(
                num_experts=1,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=1.0,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
            )
            m_scaled = scheduler_sim.run_simulation(cfg, trace)
            m_base = scheduler_sim.run_simulation(cfg, [dataclasses.replace(r, cost_scale=None) for r in trace])
            self.assertGreater(m_scaled.makespan_ms, m_base.makespan_ms)
        finally:
            os.unlink(path)

    def test_k_mode_trace_accepts_per_layer_k_when_layers_present(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"interactive","candidates":[0,1,2,3],"layers":[{"candidates":[0,1],"k":1},{"candidates":[2,3],"k":2}]}\n')
            trace = scheduler_sim.load_trace_jsonl(path)

            cfg = scheduler_sim.SimConfig(
                num_experts=4,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=1.0,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
                k_mode="trace",
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.admitted_tokens, 1)
            self.assertEqual(m.dropped_tokens_backpressure, 0)
            self.assertEqual(m.admitted_tasks, 3)
            self.assertEqual(m.chosen_k_interactive, [1])
            self.assertEqual(m.effective_k_interactive, [1])
            self.assertEqual(m.effective_k_total_interactive, [3])
        finally:
            os.unlink(path)

    def test_k_mode_trace_requires_k_for_all_layers_when_route_k_missing(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0, 1, 2, 3),
                layers=(
                    scheduler_sim.LayerRoute(candidates=(0, 1), k=None),
                    scheduler_sim.LayerRoute(candidates=(2, 3), k=2),
                ),
                k=None,
            )
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=4,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            k_mode="trace",
        )
        with self.assertRaises(ValueError):
            scheduler_sim.run_simulation(cfg, trace)

    def test_trace_jsonl_mtp_accept_len_overrides_sampling(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"mtp_accept_len":1}\n')
                f.write('{"t_ms":0.01,"cls":"batch","candidates":[0],"mtp_accept_len":2}\n')
                f.write('{"t_ms":0.02,"cls":"batch","candidates":[0],"mtp_accept_len":3}\n')
            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual([r.mtp_accept_len for r in trace], [1, 2, 3])

            cfg = scheduler_sim.SimConfig(
                num_experts=1,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=0.1,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
                mtp_draft_len=2,
                mtp_accept_prob=0.0,
                mtp_accept_decay=1.0,
                mtp_draft_cost_scale=0.25,
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.mtp_accept_len_per_step, [1, 2, 3])
            self.assertEqual(m.mtp_output_tokens, 6)
            self.assertEqual(m.mtp_draft_tokens_total, 6)
            self.assertEqual(m.mtp_draft_tokens_accepted, 3)
            self.assertEqual(m.mtp_draft_tokens_rejected, 3)
            self.assertEqual(m.mtp_bonus_tokens, 1)
        finally:
            os.unlink(path)

    def test_trace_jsonl_accepted_mtp_derives_accept_len(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"accepted_mtp":0}\n')
                f.write('{"t_ms":0.01,"cls":"batch","candidates":[0],"accepted_mtp":1}\n')
                f.write('{"t_ms":0.02,"cls":"batch","candidates":[0],"accepted_mtp":2}\n')
            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual([r.accepted_mtp for r in trace], [0, 1, 2])

            cfg = scheduler_sim.SimConfig(
                num_experts=1,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=0.1,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
                mtp_draft_len=2,
                mtp_accept_prob=0.0,
                mtp_accept_decay=1.0,
                mtp_draft_cost_scale=0.25,
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.mtp_accept_len_per_step, [1, 2, 3])
            self.assertEqual(m.mtp_output_tokens, 6)
            self.assertEqual(m.mtp_draft_tokens_total, 6)
            self.assertEqual(m.mtp_draft_tokens_accepted, 3)
            self.assertEqual(m.mtp_draft_tokens_rejected, 3)
            self.assertEqual(m.mtp_bonus_tokens, 1)
        finally:
            os.unlink(path)

    def test_trace_jsonl_rejected_mtp_derives_accept_len(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"rejected_mtp":2}\n')
                f.write('{"t_ms":0.01,"cls":"batch","candidates":[0],"rejected_mtp":1}\n')
                f.write('{"t_ms":0.02,"cls":"batch","candidates":[0],"rejected_mtp":0}\n')
            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual([r.rejected_mtp for r in trace], [2, 1, 0])

            cfg = scheduler_sim.SimConfig(
                num_experts=1,
                expert_parallelism=1,
                expert_queue_max=10_000,
                service_ms=0.1,
                starvation_ms=1e9,
                hi_burst=0,
                promote_ms=0.0,
                adaptive_k=scheduler_sim.AdaptiveKConfig(
                    k_min_interactive=1,
                    k_max_interactive=1,
                    k_min_batch=1,
                    k_max_batch=1,
                    q_low=0,
                    q_high=0,
                ),
                mtp_draft_len=2,
                mtp_accept_prob=0.0,
                mtp_accept_decay=1.0,
                mtp_draft_cost_scale=0.25,
            )
            m = scheduler_sim.run_simulation(cfg, trace)
            self.assertEqual(m.mtp_accept_len_per_step, [1, 2, 3])
            self.assertEqual(m.mtp_output_tokens, 6)
            self.assertEqual(m.mtp_draft_tokens_total, 6)
            self.assertEqual(m.mtp_draft_tokens_accepted, 3)
            self.assertEqual(m.mtp_draft_tokens_rejected, 3)
            self.assertEqual(m.mtp_bonus_tokens, 1)
        finally:
            os.unlink(path)

    def test_trace_replay_expert_id_range_checked(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(2,)),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        with self.assertRaises(ValueError):
            scheduler_sim.run_simulation(cfg, trace)

    def test_hi_burst_forces_batch_starts(self) -> None:
        trace = []
        for i in range(40):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=float(i) * 0.01,
                    cls=scheduler_sim.LatencyClass.INTERACTIVE,
                    candidates=(0,),
                )
            )
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=float(i) * 0.01,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                )
            )
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=2,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertGreater(m.forced_batch_starts, 0)

    def test_promote_ms_reduces_starvation(self) -> None:
        trace = []
        for i in range(200):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=float(i) * 0.01,
                    cls=scheduler_sim.LatencyClass.INTERACTIVE,
                    candidates=(0,),
                )
            )
        for i in range(50):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=float(i) * 0.01,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                )
            )
        trace.sort(key=lambda r: r.t_ms)

        base_cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=5.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        aged_cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=5.0,
            hi_burst=0,
            promote_ms=1.0,
            adaptive_k=base_cfg.adaptive_k,
        )
        m0 = scheduler_sim.run_simulation(base_cfg, trace)
        m1 = scheduler_sim.run_simulation(aged_cfg, trace)
        self.assertGreater(m1.promoted_tasks, 0)
        self.assertLessEqual(m1.starved_tasks, m0.starved_tasks)

    def test_admit_policy_least_pending_reduces_latency(self) -> None:
        trace = []
        for i in range(50):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                )
            )
        trace.append(
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0, 1),
            )
        )

        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        )
        base = dict(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=10.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
        )
        cfg_ordered = scheduler_sim.SimConfig(**base, admit_policy="ordered")
        cfg_least = scheduler_sim.SimConfig(**base, admit_policy="least_pending")
        m0 = scheduler_sim.run_simulation(cfg_ordered, trace)
        m1 = scheduler_sim.run_simulation(cfg_least, trace)
        self.assertGreater(m0.token_lat_ms_interactive[0], m1.token_lat_ms_interactive[0])

    def test_effective_k_and_partial_admit_metrics(self) -> None:
        trace = []
        for i in range(2):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                )
            )
        trace.append(
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
            )
        )

        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=1,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=2,
                k_max_batch=2,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(len(m.effective_k_batch), m.admitted_tokens_batch)
        self.assertGreater(m.partial_admit_tokens, 0)

    def test_admit_policy_score_desc_can_override_router_order(self) -> None:
        trace = []
        for i in range(20):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                    scores=(0.0,),
                )
            )
        trace.append(
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0, 1),
                scores=(0.1, 0.9),
            )
        )

        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        )
        base = dict(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=10.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
        )
        cfg_ordered = scheduler_sim.SimConfig(**base, admit_policy="ordered")
        cfg_scored = scheduler_sim.SimConfig(**base, admit_policy="score_desc")

        m0 = scheduler_sim.run_simulation(cfg_ordered, trace)
        m1 = scheduler_sim.run_simulation(cfg_scored, trace)
        self.assertGreater(len(m0.token_lat_ms_interactive), 0)
        self.assertGreater(len(m1.token_lat_ms_interactive), 0)
        self.assertGreater(m0.token_lat_ms_interactive[0], m1.token_lat_ms_interactive[0])

    def test_admit_policy_score_desc_requires_scores(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0, 1),
            )
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            admit_policy="score_desc",
        )
        with self.assertRaises(ValueError):
            scheduler_sim.run_simulation(cfg, trace)

    def test_batching_service_model_reduces_makespan(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for _ in range(4)
        ]
        base = dict(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=0.1,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            service_base_ms=1.0,
            service_per_task_ms=0.1,
        )
        serial_cfg = scheduler_sim.SimConfig(**base, batch_max_batch=1)
        batch_cfg = scheduler_sim.SimConfig(**base, batch_max_batch=4)
        m0 = scheduler_sim.run_simulation(serial_cfg, trace)
        m1 = scheduler_sim.run_simulation(batch_cfg, trace)
        self.assertLess(m1.makespan_ms, m0.makespan_ms)

    def test_work_batch_size_metrics_track_started_batches(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for _ in range(4)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=0.1,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            service_base_ms=1.0,
            service_per_task_ms=0.1,
            batch_max_batch=4,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.service_batches_started, 2)
        self.assertEqual(m.service_batch_size_batch, [1.0, 3.0])
        self.assertEqual(m.service_batch_size_interactive, [])

    def test_batch_wait_delays_singleton_batch_start(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            batch_max_batch=4,
            batch_wait_batch_ms=2.5,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.admitted_tasks_batch, 1)
        self.assertEqual(len(m.task_queue_wait_ms_batch), 1)
        self.assertGreaterEqual(m.task_queue_wait_ms_batch[0] + 1e-9, 2.5)

    def test_markov_trace_deterministic_and_sticky(self) -> None:
        cfg = scheduler_sim.MarkovTraceConfig(
            num_tokens=10,
            num_experts=8,
            num_candidates=4,
            interactive_prob=0.25,
            arrival_rate_tps=1000.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            stay_prob=1.0,
            seed=123,
        )
        t0 = scheduler_sim.generate_markov_trace(cfg)
        t1 = scheduler_sim.generate_markov_trace(cfg)
        self.assertEqual(t0, t1)
        primaries = [r.candidates[0] for r in t0]
        self.assertEqual(len(set(primaries)), 1)

    def test_sla_violation_counts(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for _ in range(2)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=10.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            sla_batch_ms=15.0,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.admitted_tokens_batch, 2)
        self.assertEqual(m.token_sla_violations_batch, 1)

    def test_mtp_accept_all_produces_bonus_tokens(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for i in range(10)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            sim_seed=123,
            mtp_draft_len=2,
            mtp_accept_prob=1.0,
            mtp_accept_decay=1.0,
            mtp_draft_cost_scale=0.25,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.mtp_verify_steps, 10)
        self.assertEqual(m.mtp_output_tokens, 30)
        self.assertEqual(m.mtp_draft_tokens_total, 20)
        self.assertEqual(m.mtp_draft_tokens_accepted, 20)
        self.assertEqual(m.mtp_draft_tokens_rejected, 0)
        self.assertEqual(m.mtp_bonus_tokens, 10)
        self.assertEqual(m.mtp_accept_len_per_step, [3 for _ in range(10)])

    def test_mtp_accept_none_degenerates_to_one_token(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for i in range(10)
        ]
        base = dict(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        cfg_no_mtp = scheduler_sim.SimConfig(**base)
        cfg_mtp = scheduler_sim.SimConfig(**base, sim_seed=123, mtp_draft_len=2, mtp_accept_prob=0.0, mtp_draft_cost_scale=0.25)
        m0 = scheduler_sim.run_simulation(cfg_no_mtp, trace)
        m1 = scheduler_sim.run_simulation(cfg_mtp, trace)
        self.assertEqual(m1.mtp_output_tokens, 10)
        self.assertGreater(m1.makespan_ms, m0.makespan_ms)

    def test_mtp_verify_per_draft_cost_scale_increases_makespan(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for i in range(10)
        ]
        base = dict(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            sim_seed=123,
            mtp_draft_len=2,
            mtp_accept_prob=0.0,
            mtp_accept_decay=1.0,
            mtp_draft_cost_scale=0.25,
        )
        cfg0 = scheduler_sim.SimConfig(**base, mtp_verify_per_draft_cost_scale=0.0)
        cfg1 = scheduler_sim.SimConfig(**base, mtp_verify_per_draft_cost_scale=0.5)
        m0 = scheduler_sim.run_simulation(cfg0, trace)
        m1 = scheduler_sim.run_simulation(cfg1, trace)
        self.assertGreater(m1.makespan_ms, m0.makespan_ms)

    def test_mtp_phase_queue_wait_and_starvation_metrics(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for i in range(3)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=0.0001,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            sim_seed=123,
            mtp_draft_len=2,
            mtp_accept_prob=0.0,
            mtp_accept_decay=1.0,
            mtp_draft_cost_scale=0.25,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.tasks_started_mtp_draft, len(trace) * 2)
        self.assertEqual(m.tasks_started_mtp_verify, len(trace) * 1)
        self.assertEqual(len(m.task_queue_wait_ms_mtp_draft), m.tasks_started_mtp_draft)
        self.assertEqual(len(m.task_queue_wait_ms_mtp_verify), m.tasks_started_mtp_verify)
        self.assertEqual(m.starved_tasks, (m.starved_tasks_mtp_draft + m.starved_tasks_mtp_verify))
        self.assertLessEqual(m.starved_tasks_mtp_draft, m.tasks_started_mtp_draft)
        self.assertLessEqual(m.starved_tasks_mtp_verify, m.tasks_started_mtp_verify)

    def test_output_token_latency_matches_token_latency_when_mtp_disabled(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for i in range(10)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.output_token_lat_ms_batch, m.token_lat_ms_batch)

    def test_trace_decode_ms_collected_and_error_reported(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0,),
                decode_ms=2.0,
            ),
            scheduler_sim.TokenRoute(
                t_ms=10.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                decode_ms=4.0,
            ),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.admitted_tokens_interactive, 1)
        self.assertEqual(m.admitted_tokens_batch, 1)
        self.assertEqual(m.trace_decode_ms_interactive, [2.0])
        self.assertEqual(m.trace_decode_ms_batch, [4.0])
        self.assertEqual(len(m.trace_decode_error_ms_interactive), 1)
        self.assertEqual(len(m.trace_decode_error_ms_batch), 1)

    def test_expected_mtp_accept_len_simple_cases(self) -> None:
        self.assertAlmostEqual(scheduler_sim.expected_mtp_accept_len(0, 1.0, 1.0), 1.0)
        self.assertAlmostEqual(scheduler_sim.expected_mtp_accept_len(2, 0.0, 1.0), 1.0)
        self.assertAlmostEqual(scheduler_sim.expected_mtp_accept_len(2, 1.0, 1.0), 3.0)
        self.assertAlmostEqual(scheduler_sim.expected_mtp_accept_len(2, 0.5, 1.0), 1.75)

    def test_arrival_units_output_tokens_rescales_steps_rate(self) -> None:
        steps = scheduler_sim.arrival_rate_steps_tps(1000.0, "steps", 2, 1.0, 1.0)
        self.assertAlmostEqual(steps, 1000.0)
        steps_out = scheduler_sim.arrival_rate_steps_tps(1000.0, "output_tokens", 2, 1.0, 1.0)
        self.assertAlmostEqual(steps_out, (1000.0 / 3.0))
        with self.assertRaises(ValueError):
            scheduler_sim.arrival_rate_steps_tps(1000.0, "bad_units", 2, 1.0, 1.0)

    def test_work_units_and_service_slot_ms_track_mtp_efficiency(self) -> None:
        trace_mtp = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0,),
                k=1,
                mtp_accept_len=3,
            )
        ]
        trace_off = [dataclasses.replace(trace_mtp[0], mtp_accept_len=None)]
        cfg_base = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=1,
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            k_mode="trace",
            service_base_ms=0.0,
            service_per_task_ms=1.0,
        )
        m_off = scheduler_sim.run_simulation(dataclasses.replace(cfg_base, mtp_draft_len=0), trace_off)
        m_on = scheduler_sim.run_simulation(
            dataclasses.replace(cfg_base, mtp_draft_len=2, mtp_draft_cost_scale=0.25, mtp_accept_prob=0.0, mtp_accept_decay=1.0),
            trace_mtp,
        )
        self.assertAlmostEqual(m_off.work_units_total, 1.0, places=6)
        self.assertAlmostEqual(m_off.service_slot_ms_total, 1.0, places=6)
        self.assertAlmostEqual(m_on.work_units_total, 1.5, places=6)
        self.assertAlmostEqual(m_on.service_slot_ms_total, 1.5, places=6)
        self.assertEqual(m_on.mtp_output_tokens, 3)
        self.assertLess((m_on.service_slot_ms_total / float(m_on.mtp_output_tokens)), (m_off.service_slot_ms_total / float(m_off.admitted_tokens)))


if __name__ == "__main__":
    unittest.main()
