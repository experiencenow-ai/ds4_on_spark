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
                f.write('{"t_ms":0.0,"cls":"interactive","candidates":[0,1]}\n')
            trace = scheduler_sim.load_trace_jsonl(path)
            self.assertEqual(len(trace), 2)
            self.assertEqual(trace[0].t_ms, 0.0)
            self.assertEqual(trace[0].cls, scheduler_sim.LatencyClass.INTERACTIVE)
            self.assertEqual(trace[1].cls, scheduler_sim.LatencyClass.BATCH)

            cfg = scheduler_sim.SimConfig(
                num_experts=2,
                expert_parallelism=1,
                expert_queue_max=10,
                service_ms=1.0,
                starvation_ms=1e9,
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


if __name__ == "__main__":
    unittest.main()
