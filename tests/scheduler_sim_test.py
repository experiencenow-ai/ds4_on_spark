import unittest
import tempfile
import os
import dataclasses
import contextlib
import io
import json

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

    def test_trace_jsonl_layers_replay_increases_work_on_same_expert(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(
                json.dumps(
                    {
                        "t_ms": 0.0,
                        "cls": "batch",
                        "layers": [{"candidates": [0]}, {"candidates": [0]}],
                    }
                )
            )
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path)
            self.assertEqual(len(trace), 1)
            self.assertIsNotNone(trace[0].layers)
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
            self.assertEqual(len(m.token_lat_ms_batch), 1)
            self.assertAlmostEqual(m.token_lat_ms_batch[0], 2.0, places=6)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

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
