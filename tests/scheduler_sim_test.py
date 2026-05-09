import unittest
import tempfile
import os

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

    def test_trace_jsonl_scores_length_must_match_candidates(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"interactive","candidates":[0,1],"scores":[0.9]}\n')
            with self.assertRaises(ValueError):
                scheduler_sim.load_trace_jsonl(path)
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


if __name__ == "__main__":
    unittest.main()
