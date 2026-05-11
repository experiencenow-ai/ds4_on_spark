import unittest
import tempfile
import os
import dataclasses
import contextlib
import io
import json
import sys

from sim.scheduler import scheduler_sim
from sim.scheduler import recommendations
from sim.scheduler import trace_extract


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

    def test_synthetic_trace_score_mode_random_emits_scores(self) -> None:
        cfg = scheduler_sim.TraceConfig(
            num_tokens=6,
            num_experts=8,
            num_candidates=4,
            interactive_prob=0.0,
            arrival_rate_tps=1000.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
            synthetic_score_mode="random",
        )
        t0 = scheduler_sim.generate_synthetic_trace(cfg)
        t1 = scheduler_sim.generate_synthetic_trace(cfg)
        self.assertEqual(t0, t1)
        for r in t0:
            self.assertIsNotNone(r.scores)
            self.assertEqual(len(r.scores or ()), 4)

    def test_synthetic_trace_multi_layer_score_mode_emits_layer_scores_only(self) -> None:
        cfg = scheduler_sim.TraceConfig(
            num_tokens=5,
            num_experts=8,
            num_candidates=3,
            interactive_prob=0.0,
            arrival_rate_tps=1000.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
            num_layers=3,
            synthetic_score_mode="random",
        )
        trace = scheduler_sim.generate_synthetic_trace(cfg)
        for r in trace:
            self.assertIsNone(r.scores)
            self.assertIsNotNone(r.layers)
            for lr in r.layers or ():
                self.assertIsNotNone(lr.scores)
                self.assertEqual(len(lr.scores or ()), 3)

    def test_synthetic_trace_cost_scale_lognormal_emits_positive(self) -> None:
        cfg = scheduler_sim.TraceConfig(
            num_tokens=8,
            num_experts=8,
            num_candidates=4,
            interactive_prob=0.0,
            arrival_rate_tps=1000.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
            synthetic_cost_scale_mode="lognormal",
            synthetic_cost_scale_log_sigma=0.2,
        )
        trace = scheduler_sim.generate_synthetic_trace(cfg)
        self.assertTrue(all(r.cost_scale is not None and float(r.cost_scale) > 0.0 for r in trace))

    def test_twostream_trace_deterministic_and_splits_by_rate(self) -> None:
        cfg = scheduler_sim.TwoStreamTraceConfig(
            num_tokens=40,
            num_experts=8,
            num_candidates=4,
            interactive_arrival_rate_tps=1000.0,
            batch_arrival_rate_tps=3000.0,
            interactive_burst_prob=0.0,
            interactive_burst_scale=1.0,
            batch_burst_prob=0.0,
            batch_burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        t0 = scheduler_sim.generate_twostream_trace(cfg)
        t1 = scheduler_sim.generate_twostream_trace(cfg)
        self.assertEqual(t0, t1)
        self.assertEqual(len(t0), 40)
        self.assertTrue(all(r.t_ms >= 0.0 for r in t0))
        self.assertTrue(all(len(r.candidates) == 4 for r in t0))
        num_hi = sum(1 for r in t0 if r.cls == scheduler_sim.LatencyClass.INTERACTIVE)
        self.assertEqual(num_hi, 10)

    def test_twostream_trace_all_batch_when_interactive_rate_zero(self) -> None:
        cfg = scheduler_sim.TwoStreamTraceConfig(
            num_tokens=12,
            num_experts=8,
            num_candidates=3,
            interactive_arrival_rate_tps=0.0,
            batch_arrival_rate_tps=1000.0,
            interactive_burst_prob=0.0,
            interactive_burst_scale=1.0,
            batch_burst_prob=0.0,
            batch_burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        trace = scheduler_sim.generate_twostream_trace(cfg)
        self.assertEqual(len(trace), 12)
        self.assertTrue(all(r.cls == scheduler_sim.LatencyClass.BATCH for r in trace))

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

    def test_trace_jsonl_loads_dflash_fields(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0], "dflash_accept_len": 3, "accepted_dflash": 2, "rejected_dflash": 0}))
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path)
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0].dflash_accept_len, 3)
            self.assertEqual(trace[0].accepted_dflash, 2)
            self.assertEqual(trace[0].rejected_dflash, 0)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_extract_runtime_separates_mtp_and_dflash_accept_counters(self) -> None:
        obj = {
            "t_ms": 0.0,
            "cls": "batch",
            "route": {"candidates": [0, 1]},
            "mtp": {"accept_len": 2, "accepted": 1, "rejected": 0},
            "dflash": {"accept_len": 4, "accepted": 3, "rejected": 0},
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        if rec is None:
            return
        self.assertEqual(rec.get("mtp_accept_len"), 2)
        self.assertEqual(rec.get("accepted_mtp"), 1)
        self.assertEqual(rec.get("rejected_mtp"), 0)
        self.assertEqual(rec.get("dflash_accept_len"), 4)
        self.assertEqual(rec.get("accepted_dflash"), 3)
        self.assertEqual(rec.get("rejected_dflash"), 0)

    def test_trace_extract_does_not_treat_dflash_accept_len_as_mtp(self) -> None:
        obj = {
            "t_ms": 0.0,
            "cls": "batch",
            "route": {"candidates": [0]},
            "dflash": {"accept_len": 3, "accepted": 2, "rejected": 0},
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        if rec is None:
            return
        self.assertNotIn("mtp_accept_len", rec)
        self.assertNotIn("accepted_mtp", rec)
        self.assertNotIn("rejected_mtp", rec)
        self.assertEqual(rec.get("dflash_accept_len"), 3)

    def test_runtime_trace_ablation_applies_dflash_cost_scale_from_meta(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                dflash_accept_len=3,
                accepted_dflash=2,
                rejected_dflash=0,
            )
        ]
        out = recommendations.run_runtime_trace_mtp_ablation(
            trace=trace,
            trace_meta={"num_experts": 1, "dflash_draft_cost_scale": 0.5},
            expert_queue_max=10_000,
            expert_parallelism=1,
            service_ms=1.0,
            starvation_ms=1e9,
        )
        dflash = out.get("dflash_comparator")
        self.assertIsInstance(dflash, dict)
        if not isinstance(dflash, dict):
            return
        summary = dflash.get("summary")
        self.assertIsInstance(summary, dict)
        if not isinstance(summary, dict):
            return
        self.assertAlmostEqual(float(summary.get("dflash_draft_cost_scale", 0.0)), 0.5, places=6)
        ratio_adj = float(dflash.get("service_slot_ms_per_output_token_ratio_vs_target_only_adjusted", 0.0))
        self.assertGreater(ratio_adj, 0.0)

    def test_summary_json_emits_per_layer_stage_skip_fractions(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
                layers=(scheduler_sim.LayerRoute(candidates=(0,)), scheduler_sim.LayerRoute(candidates=(1,))),
                cost_scale=1.0,
            ),
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(1,),
                cost_scale=100.0,
            ),
        ]
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
            sim_seed=123,
        )
        metrics = scheduler_sim.run_simulation(cfg, trace)
        summary = scheduler_sim.compare_summary_jsonable(metrics)
        self.assertIn("stages_total_layer0", summary)
        self.assertIn("stages_total_layer1", summary)
        self.assertIn("skipped_stage_frac_layer0", summary)
        self.assertIn("skipped_stage_frac_layer1", summary)
        self.assertAlmostEqual(float(summary["stages_total_layer0"]), 2.0, places=6)
        self.assertAlmostEqual(float(summary["stages_total_layer1"]), 1.0, places=6)
        self.assertAlmostEqual(float(summary["skipped_stage_frac_layer0"]), 0.0, places=6)
        self.assertAlmostEqual(float(summary["skipped_stage_frac_layer1"]), 1.0, places=6)

    def test_adaptive_k_per_class_q_threshold_overrides(self) -> None:
        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=4,
            k_min_batch=1,
            k_max_batch=4,
            q_low=10,
            q_high=20,
            q_low_interactive=0,
            q_high_interactive=0,
            q_low_batch=-1,
            q_high_batch=-1,
        )
        self.assertEqual(scheduler_sim.choose_k(adapt, scheduler_sim.LatencyClass.INTERACTIVE, 0.0), 4)
        self.assertEqual(scheduler_sim.choose_k(adapt, scheduler_sim.LatencyClass.INTERACTIVE, 5.0), 1)
        self.assertEqual(scheduler_sim.choose_k(adapt, scheduler_sim.LatencyClass.BATCH, 5.0), 4)
        self.assertEqual(scheduler_sim.choose_k(adapt, scheduler_sim.LatencyClass.BATCH, 25.0), 1)

    def test_admit_policy_least_pending_work_prefers_lower_pending_work(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), k=1, cost_scale=10.0),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), k=1, cost_scale=1.0),
            scheduler_sim.TokenRoute(t_ms=2.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), k=1, cost_scale=1.0),
        ]
        base_cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=100.0,
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
            backpressure_units="work",
        )
        m_count = scheduler_sim.run_simulation(dataclasses.replace(base_cfg, admit_policy="least_pending"), trace)
        m_work = scheduler_sim.run_simulation(dataclasses.replace(base_cfg, admit_policy="least_pending_work"), trace)
        self.assertEqual(m_count.tasks_started_per_expert, [2, 1])
        self.assertEqual(m_work.tasks_started_per_expert, [1, 2])

    def test_summary_includes_dflash_comparator_metrics(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                dflash_accept_len=3,
                accepted_dflash=2,
                rejected_dflash=0,
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
            dflash_draft_cost_scale=0.5,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertEqual(int(s["dflash_steps"]), 1)
        self.assertEqual(int(s["dflash_output_tokens"]), 3)
        self.assertEqual(int(s["dflash_bonus_tokens"]), 2)
        self.assertAlmostEqual(float(s["dflash_mean_accept_len"]), 3.0, places=6)
        self.assertAlmostEqual(float(s["dflash_accept_len_p50"]), 3.0, places=6)
        self.assertAlmostEqual(float(s["dflash_accept_len_p95"]), 3.0, places=6)
        self.assertAlmostEqual(float(s["dflash_accept_rate"]), 1.0, places=6)
        self.assertAlmostEqual(float(s["dflash_service_slot_ms_per_output_token"]), (1.0 / 3.0), places=6)
        self.assertAlmostEqual(float(s["dflash_draft_cost_scale"]), 0.5, places=6)
        self.assertAlmostEqual(float(s["dflash_service_slot_ms_per_output_token_adjusted"]), 0.5, places=6)

    def test_summary_includes_mtp_accept_len_percentiles(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=2.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
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
            mtp_draft_len=2,
            mtp_accept_prob=1.0,
            mtp_accept_decay=1.0,
            mtp_draft_attempt_policy="full",
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertAlmostEqual(float(s["mtp_mean_accept_len"]), 3.0, places=6)
        self.assertAlmostEqual(float(s["mtp_accept_len_p50"]), 3.0, places=6)
        self.assertAlmostEqual(float(s["mtp_accept_len_p95"]), 3.0, places=6)
        self.assertAlmostEqual(float(s["mtp_mean_draft_attempt_len"]), 2.0, places=6)
        self.assertAlmostEqual(float(s["mtp_draft_attempt_len_p50"]), 2.0, places=6)
        self.assertAlmostEqual(float(s["mtp_draft_attempt_len_p95"]), 2.0, places=6)

    def test_summary_includes_pending_hi_lo_depth_time_weighted(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
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
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertIn("pending_hi_depth_time_weighted_p95", s)
        self.assertIn("pending_lo_depth_time_weighted_p95", s)
        self.assertIn("pending_hi_work_depth_time_weighted_p95", s)
        self.assertIn("pending_lo_work_depth_time_weighted_p95", s)
        self.assertAlmostEqual(float(s["hi_queue_depth_time_weighted_p95"]), 0.0, places=6)
        self.assertAlmostEqual(float(s["pending_hi_depth_time_weighted_p95"]), 1.0, places=6)
        self.assertAlmostEqual(float(s["pending_lo_depth_time_weighted_p95"]), 1.0, places=6)
        self.assertAlmostEqual(float(s["pending_hi_work_depth_time_weighted_p95"]), 1.0, places=6)
        self.assertAlmostEqual(float(s["pending_lo_work_depth_time_weighted_p95"]), 1.0, places=6)

    def test_summary_includes_pending_signal_and_k_controller_activity(self) -> None:
        trace_cfg = scheduler_sim.TwoStreamTraceConfig(
            num_tokens=200,
            num_experts=8,
            num_candidates=8,
            interactive_arrival_rate_tps=500.0,
            batch_arrival_rate_tps=20000.0,
            interactive_burst_prob=0.0,
            interactive_burst_scale=1.0,
            batch_burst_prob=0.0,
            batch_burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        trace = scheduler_sim.generate_twostream_trace(trace_cfg)
        cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=128,
            service_ms=1.0,
            starvation_ms=100.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=4,
                k_min_batch=1,
                k_max_batch=2,
                q_low=8,
                q_high=96,
            ),
            k_mode="controller",
            k_signal="global",
            sim_seed=123,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        s = scheduler_sim.compare_summary_jsonable(m)
        for k in (
            "pending_signal_p50_interactive",
            "pending_signal_p95_interactive",
            "pending_signal_p50_batch",
            "pending_signal_p95_batch",
            "k_update_frac_tokens_interactive",
            "k_update_frac_tokens_batch",
            "k_change_frac_tokens_interactive",
            "k_change_frac_tokens_batch",
        ):
            self.assertIn(k, s)
        self.assertGreaterEqual(float(s["pending_signal_p95_interactive"]), 0.0)
        self.assertGreaterEqual(float(s["pending_signal_p95_batch"]), 0.0)
        self.assertGreaterEqual(float(s["k_update_frac_tokens_interactive"]), 0.0)
        self.assertLessEqual(float(s["k_update_frac_tokens_interactive"]), 1.0)
        self.assertGreaterEqual(float(s["k_update_frac_tokens_batch"]), 0.0)
        self.assertLessEqual(float(s["k_update_frac_tokens_batch"]), 1.0)

    def test_stage_skip_totals_count_attempts(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                layers=(scheduler_sim.LayerRoute(candidates=(0,)), scheduler_sim.LayerRoute(candidates=(0,))),
            ),
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                layers=(scheduler_sim.LayerRoute(candidates=(0,)), scheduler_sim.LayerRoute(candidates=(0,))),
            ),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
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
        self.assertEqual(m.stages_total, 4)
        self.assertEqual(m.stages_total_batch, 4)
        self.assertEqual(m.stages_total_verify, 4)
        self.assertEqual(m.skipped_stages_backpressure, 2)
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertAlmostEqual(float(s["skipped_stage_frac"]), 0.5, places=6)
        self.assertAlmostEqual(float(s["skipped_stage_frac_verify"]), 0.5, places=6)

    def test_backpressure_zero_admit_policy_stall_retries_instead_of_drop(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), k=1),
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), k=1),
        ]
        base_cfg = scheduler_sim.SimConfig(
            num_experts=1,
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
            k_mode="trace",
        )

        m_skip = scheduler_sim.run_simulation(dataclasses.replace(base_cfg, backpressure_zero_admit_policy="skip"), trace)
        self.assertEqual(m_skip.dropped_tokens_backpressure, 1)

        m_stall = scheduler_sim.run_simulation(dataclasses.replace(base_cfg, backpressure_zero_admit_policy="stall"), trace)
        self.assertEqual(m_stall.dropped_tokens_backpressure, 0)
        self.assertEqual(len(m_stall.token_lat_ms_batch), 2)
        self.assertAlmostEqual(max(m_stall.token_lat_ms_batch), 2.0, places=6)
        s = scheduler_sim.compare_summary_jsonable(m_stall)
        self.assertEqual(int(s["blocked_stages_backpressure_attempts"]), 1)

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

    def test_trace_jsonl_non_json_line_skip_ignores(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write("not-json\n")
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0]}))
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path, non_route_policy="skip")
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0].candidates, (0,))
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_jsonl_non_json_line_error_raises(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write("not-json\n")
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0]}))
            f.write("\n")
        try:
            with self.assertRaises(ValueError):
                scheduler_sim.load_trace_jsonl(tmp_path, non_route_policy="error")
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_jsonl_runtime_input_format_maps_aliases_and_filters_by_type(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"type": "meta", "meta": {"runtime_commit": "abc123"}}))
            f.write("\n")
            f.write(json.dumps({"type": "decode", "dt_ms": 0.0, "decode_ms": 0.01}))
            f.write("\n")
            f.write(
                json.dumps(
                    {
                        "type": "route",
                        "dt_ms": 0.0,
                        "latency_class": "interactive",
                        "routing": {"expert_ids": [3, 7, 1]},
                    }
                )
            )
            f.write("\n")
        try:
            meta: dict[str, object] = {}
            trace = scheduler_sim.load_trace_jsonl(
                tmp_path,
                time_mode="dt_ms",
                meta_out=meta,
                non_route_policy="skip",
                input_format="runtime",
                route_type="route",
            )
            self.assertEqual(len(trace), 1)
            self.assertEqual(meta.get("runtime_commit"), "abc123")
            self.assertEqual(trace[0].cls, scheduler_sim.LatencyClass.INTERACTIVE)
            self.assertEqual(trace[0].candidates, (3, 7, 1))
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_jsonl_runtime_input_format_extracts_embedded_json_when_non_route_skip(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write('INFO: {"type":"meta","meta":{"runtime_commit":"abc123"}}\n')
            f.write(
                '2026-05-11T00:00:00Z route={"type":"route","dt_ms":0.0,"latency_class":"interactive","routing":{"expert_ids":[3,7,1]}} trailing\n'
            )
        try:
            meta: dict[str, object] = {}
            trace = scheduler_sim.load_trace_jsonl(
                tmp_path,
                time_mode="dt_ms",
                meta_out=meta,
                non_route_policy="skip",
                input_format="runtime",
                route_type="route",
            )
            self.assertEqual(len(trace), 1)
            self.assertEqual(meta.get("runtime_commit"), "abc123")
            self.assertEqual(trace[0].cls, scheduler_sim.LatencyClass.INTERACTIVE)
            self.assertEqual(trace[0].candidates, (3, 7, 1))
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_synthetic_score_mode_rejected_in_trace_replay(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0, 1]}))
            f.write("\n")
        try:
            with self.assertRaises(SystemExit):
                scheduler_sim.main(["--trace-jsonl", tmp_path, "--synthetic-score-mode", "random", "--json"])
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

    def test_trace_canonicalize_derives_dflash_accept_len_from_rejected_when_draft_len_known(self) -> None:
        payload = ""
        payload += json.dumps({"type": "meta", "meta": {"dflash_draft_len": 4}}) + "\n"
        payload += json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0], "rejected_dflash": 3}) + "\n"
        buf = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", "-", "--canonicalize-trace-jsonl", "-", "--trace-time-mode", "t_ms", "--mtp-draft-len", "0", "--json"])
            self.assertEqual(rc, 0)
        finally:
            sys.stdin = old_stdin
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip() != ""]
        self.assertGreaterEqual(len(lines), 2)
        route0 = json.loads(lines[1])
        self.assertEqual(route0.get("dflash_accept_len"), 2)

    def test_trace_canonicalize_derives_mtp_accept_len_from_rejected_when_draft_len_known(self) -> None:
        payload = ""
        payload += json.dumps({"type": "meta", "meta": {"mtp_draft_len": 4}}) + "\n"
        payload += json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0], "rejected_mtp": 3}) + "\n"
        buf = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", "-", "--canonicalize-trace-jsonl", "-", "--trace-time-mode", "t_ms", "--mtp-draft-len", "0", "--json"])
            self.assertEqual(rc, 0)
        finally:
            sys.stdin = old_stdin
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip() != ""]
        self.assertGreaterEqual(len(lines), 2)
        route0 = json.loads(lines[1])
        self.assertEqual(route0.get("mtp_accept_len"), 2)

    def test_trace_canonicalize_skips_mtp_accept_len_when_rejected_out_of_range(self) -> None:
        payload = ""
        payload += json.dumps({"type": "meta", "meta": {"mtp_draft_len": 2}}) + "\n"
        payload += json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0], "rejected_mtp": 7}) + "\n"
        buf = io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", "-", "--canonicalize-trace-jsonl", "-", "--trace-time-mode", "t_ms", "--mtp-draft-len", "0", "--json"])
            self.assertEqual(rc, 0)
        finally:
            sys.stdin = old_stdin
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip() != ""]
        self.assertGreaterEqual(len(lines), 2)
        route0 = json.loads(lines[1])
        self.assertNotIn("mtp_accept_len", route0)

    def test_trace_replay_accounts_dflash_accept_len_from_rejected_when_draft_len_known(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps({"type": "meta", "meta": {"dflash_draft_len": 4}}))
                f.write("\n")
                f.write(json.dumps({"t_ms": 0.0, "cls": "batch", "candidates": [0], "rejected_dflash": 3}))
                f.write("\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", path, "--trace-time-mode", "t_ms", "--num-experts", "0", "--mtp-draft-len", "0", "--dflash-draft-len", "-1", "--service-ms", "0.01", "--summary-json"])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue())
            self.assertEqual(int(out["summary"]["dflash_steps"]), 1)
            self.assertEqual(int(out["summary"]["dflash_output_tokens"]), 2)
            self.assertAlmostEqual(float(out["summary"]["dflash_mean_accept_len"]), 2.0, places=6)
        finally:
            os.unlink(path)

    def test_dump_sim_jsonl_writes_token_records(self) -> None:
        out_buf = io.StringIO()
        dump_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            dump_path = f.name
        try:
            with contextlib.redirect_stdout(out_buf):
                rc = scheduler_sim.main(["--num-tokens", "50", "--num-experts", "16", "--dump-sim-jsonl", dump_path, "--summary-json"])
            self.assertEqual(rc, 0)
            summary_out = json.loads(out_buf.getvalue())
            self.assertIn("summary", summary_out)

            with open(dump_path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip() != ""]
            self.assertEqual(len(lines), 51)
            meta = json.loads(lines[0])
            self.assertEqual(meta.get("type"), "meta")
            meta_obj = meta.get("meta")
            self.assertIsInstance(meta_obj, dict)
            self.assertTrue(bool(meta_obj.get("sim_token_dump")))
            self.assertEqual(int(meta_obj.get("num_tokens") or 0), 50)

            for i, ln in enumerate(lines[1:], 0):
                rec = json.loads(ln)
                self.assertEqual(rec.get("type"), "sim_token")
                self.assertEqual(rec.get("i"), i)
                self.assertIn(rec.get("cls"), ("interactive", "batch"))
                self.assertIsNotNone(rec.get("done_ms"))
                lat_ms = rec.get("lat_ms")
                if lat_ms is not None:
                    self.assertGreaterEqual(float(lat_ms), 0.0)
        finally:
            if dump_path != "" and os.path.exists(dump_path):
                os.unlink(dump_path)

    def test_dump_sim_jsonl_with_compare_writes_one_file_per_label(self) -> None:
        out_buf = io.StringIO()
        with tempfile.TemporaryDirectory() as td:
            dump_tmpl = os.path.join(td, "sim_{label}.jsonl")
            with contextlib.redirect_stdout(out_buf):
                rc = scheduler_sim.main(
                    [
                        "--num-tokens",
                        "20",
                        "--num-experts",
                        "8",
                        "--num-candidates",
                        "4",
                        "--summary-json",
                        "--dump-sim-jsonl",
                        dump_tmpl,
                        "--compare",
                        'v1:{"expert_queue_max":64}',
                    ]
                )
            self.assertEqual(rc, 0)
            summary_out = json.loads(out_buf.getvalue())
            self.assertIn("baseline", summary_out)
            self.assertIn("variants", summary_out)

            for label in ("baseline", "v1"):
                dump_path = os.path.join(td, f"sim_{label}.jsonl")
                with open(dump_path, "r", encoding="utf-8") as f:
                    lines = [ln for ln in f.read().splitlines() if ln.strip() != ""]
                self.assertEqual(len(lines), 21)
                meta = json.loads(lines[0])
                self.assertEqual(meta.get("type"), "meta")
                self.assertTrue(bool(meta.get("meta", {}).get("sim_token_dump")))

    def test_summary_json_outputs_concise_metrics(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = scheduler_sim.main(["--num-tokens", "2000", "--summary-json"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertIn("summary", out)
        summary = out["summary"]
        self.assertIsInstance(summary, dict)
        for k in (
            "makespan_ms",
            "token_throughput_tps",
            "task_throughput_tps",
            "drop_frac_tokens",
            "drop_frac_tokens_interactive",
            "drop_frac_tokens_batch",
            "partial_admit_frac_tokens",
            "starved_task_frac",
            "starved_task_frac_interactive",
            "service_batch_size_p50_interactive",
            "service_batch_size_p95_interactive",
            "service_batch_size_p50_batch",
            "service_batch_size_p95_batch",
            "trace_expert_batch_size_p50_interactive",
            "trace_expert_batch_size_p95_interactive",
            "trace_expert_batch_size_present_frac_interactive",
            "trace_expert_batch_size_leq1_frac_interactive",
            "trace_expert_batch_size_leq4_frac_interactive",
            "trace_expert_batch_size_p50_batch",
            "trace_expert_batch_size_p95_batch",
            "trace_expert_batch_size_present_frac_batch",
            "trace_expert_batch_size_leq1_frac_batch",
            "trace_expert_batch_size_leq4_frac_batch",
            "trace_decode_ms_p50_interactive",
            "trace_decode_ms_p95_interactive",
            "trace_decode_ms_p50_batch",
            "trace_decode_ms_p95_batch",
            "trace_decode_error_ms_p50_interactive",
            "trace_decode_error_ms_p95_interactive",
            "trace_decode_error_ms_p50_batch",
            "trace_decode_error_ms_p95_batch",
            "trace_kv_tokens_p50_interactive",
            "trace_kv_tokens_p95_interactive",
            "trace_kv_tokens_p50_batch",
            "trace_kv_tokens_p95_batch",
            "expert_max_pending_tasks_max",
            "expert_max_pending_tasks_p95",
            "expert_max_queue_tasks_max",
            "expert_max_queue_tasks_p95",
            "expert_max_pending_work_p95",
            "expert_max_queue_work_p95",
            "expert_utilization_p50",
            "expert_utilization_gini",
            "expert_saturation_p95",
            "expert_tasks_started_gini",
            "expert_tasks_started_top1_frac",
            "pending_depth_time_weighted_p95",
            "pending_depth_time_weighted_p95_mtp_draft",
            "pending_depth_time_weighted_p95_mtp_verify",
            "mtp_accept_rate",
            "mtp_mean_accept_len",
            "mtp_mean_draft_attempt_len",
        ):
            self.assertIn(k, summary)

    def test_summary_reports_trace_expert_batch_size_presence_and_underfill_fracs(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,), expert_batch_size=1),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,), expert_batch_size=4),
            scheduler_sim.TokenRoute(t_ms=2.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,), expert_batch_size=None),
            scheduler_sim.TokenRoute(t_ms=3.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), expert_batch_size=1),
            scheduler_sim.TokenRoute(t_ms=4.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), expert_batch_size=8),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=0.01,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertAlmostEqual(float(s.get("trace_expert_batch_size_present_frac_interactive", 0.0)), 2.0 / 3.0, places=6)
        self.assertAlmostEqual(float(s.get("trace_expert_batch_size_leq1_frac_interactive", 0.0)), 0.5, places=6)
        self.assertAlmostEqual(float(s.get("trace_expert_batch_size_leq4_frac_interactive", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(s.get("trace_expert_batch_size_present_frac_batch", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(s.get("trace_expert_batch_size_leq1_frac_batch", 0.0)), 0.5, places=6)
        self.assertAlmostEqual(float(s.get("trace_expert_batch_size_leq4_frac_batch", 0.0)), 0.5, places=6)

    def test_summary_json_reports_max_pending_p95(self) -> None:
        trace = []
        for _ in range(12):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                    cost_scale=2.0,
                )
            )
        for _ in range(3):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(1,),
                    cost_scale=1.0,
                )
            )
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=100_000,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertAlmostEqual(float(s.get("expert_max_pending_tasks_p95", 0.0)), 11.55, places=6)
        self.assertAlmostEqual(float(s.get("expert_max_pending_work_p95", 0.0)), 22.95, places=6)

    def test_summary_json_reports_pending_depth_per_layer_means(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
                layers=(
                    scheduler_sim.LayerRoute(candidates=(0,), k=1),
                    scheduler_sim.LayerRoute(candidates=(1,), k=1),
                ),
            )
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=100,
            expert_parallelism=1,
            expert_queue_max=1000,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertIn("pending_depth_time_weighted_mean_layer0", s)
        self.assertIn("pending_depth_time_weighted_mean_layer1", s)
        self.assertAlmostEqual(float(s.get("pending_depth_time_weighted_mean_layer0", 0.0)), 0.005, places=6)
        self.assertAlmostEqual(float(s.get("pending_depth_time_weighted_mean_layer1", 0.0)), 0.005, places=6)
        self.assertAlmostEqual(float(s.get("pending_depth_time_weighted_p95_layer0", 1.0)), 0.0, places=6)
        self.assertAlmostEqual(float(s.get("pending_depth_time_weighted_p95_layer1", 1.0)), 0.0, places=6)

    def test_summary_json_reports_max_queue_p95(self) -> None:
        trace = []
        for _ in range(12):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(0,),
                    cost_scale=2.0,
                )
            )
        for _ in range(3):
            trace.append(
                scheduler_sim.TokenRoute(
                    t_ms=0.0,
                    cls=scheduler_sim.LatencyClass.BATCH,
                    candidates=(1,),
                    cost_scale=1.0,
                )
            )
        cfg = scheduler_sim.SimConfig(
            num_experts=2,
            expert_parallelism=1,
            expert_queue_max=100_000,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertAlmostEqual(float(s.get("expert_max_queue_tasks_p95", 0.0)), 10.55, places=6)
        self.assertAlmostEqual(float(s.get("expert_max_queue_work_p95", 0.0)), 21.0, places=6)

    def test_mtp_pending_depth_time_weighted_tracks_draft_and_verify(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)) for _ in range(200)]
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
            mtp_draft_len=2,
            mtp_accept_prob=0.0,
            mtp_accept_decay=1.0,
            mtp_draft_cost_scale=0.25,
            sim_seed=123,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertTrue(any(t > 0.0 for t in (m.pending_depth_hist_mtp_draft[1:] if len(m.pending_depth_hist_mtp_draft) > 1 else [])) or m.pending_depth_hist_mtp_draft_overflow > 0.0)
        self.assertTrue(any(t > 0.0 for t in (m.pending_depth_hist_mtp_verify[1:] if len(m.pending_depth_hist_mtp_verify) > 1 else [])) or m.pending_depth_hist_mtp_verify_overflow > 0.0)

    def test_expert_load_skew_summary_peaks_when_single_expert_used(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=float(i), cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)) for i in range(60)]
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
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertGreater(float(s.get("expert_tasks_started_gini", 0.0)), 0.70)
        self.assertGreater(float(s.get("expert_utilization_gini", 0.0)), 0.60)
        self.assertAlmostEqual(float(s.get("expert_tasks_started_top1_frac", 0.0)), 1.0, places=6)

    def test_admit_policy_least_pending_reduces_load_skew_and_makespan(self) -> None:
        candidates = tuple(range(8))
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=candidates) for _ in range(256)]
        cfg = scheduler_sim.SimConfig(
            num_experts=8,
            expert_parallelism=1,
            expert_queue_max=100_000,
            service_ms=1.0,
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
            sim_seed=123,
        )
        ordered = scheduler_sim.run_simulation(dataclasses.replace(cfg, admit_policy="ordered"), trace)
        balanced = scheduler_sim.run_simulation(dataclasses.replace(cfg, admit_policy="least_pending"), trace)
        s_ordered = scheduler_sim.compare_summary_jsonable(ordered)
        s_balanced = scheduler_sim.compare_summary_jsonable(balanced)
        self.assertGreater(float(s_ordered.get("expert_tasks_started_gini", 0.0)), 0.70)
        self.assertLess(float(s_balanced.get("expert_tasks_started_gini", 1.0)), 0.20)
        self.assertLess(float(s_balanced.get("expert_tasks_started_top1_frac", 1.0)), float(s_ordered.get("expert_tasks_started_top1_frac", 0.0)))
        self.assertLess(float(s_balanced.get("makespan_ms", 1e9)), float(s_ordered.get("makespan_ms", 0.0)))

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

    def test_infer_mtp_draft_len_from_trace_from_accept_len(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), mtp_accept_len=3),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), mtp_accept_len=1),
        ]
        self.assertEqual(scheduler_sim.infer_mtp_draft_len_from_trace(trace), 2)

    def test_infer_mtp_draft_len_from_trace_accept_len_all_rejects_defaults_to_one(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), mtp_accept_len=1)]
        self.assertEqual(scheduler_sim.infer_mtp_draft_len_from_trace(trace), 1)

    def test_infer_dflash_draft_len_from_trace_from_accept_len(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), dflash_accept_len=4),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), dflash_accept_len=1),
        ]
        self.assertEqual(scheduler_sim.infer_dflash_draft_len_from_trace(trace), 3)

    def test_infer_dflash_draft_len_from_trace_accept_len_all_rejects_defaults_to_one(self) -> None:
        trace = [scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1), dflash_accept_len=1)]
        self.assertEqual(scheduler_sim.infer_dflash_draft_len_from_trace(trace), 1)

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
        self.assertEqual(m.starved_task_queue_wait_ms_interactive, [])
        self.assertEqual(m.starved_task_queue_wait_ms_batch, [10.0, 20.0])

        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertAlmostEqual(s.get("starved_task_queue_wait_ms_p95", 0.0), 19.5, places=6)
        self.assertAlmostEqual(s.get("starved_task_queue_wait_ms_p95_batch", 0.0), 19.5, places=6)
        self.assertAlmostEqual(s.get("starved_task_queue_wait_ms_p95_interactive", 0.0), 0.0, places=6)

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

    def test_k_signal_global_mean_dampens_single_hot_expert(self) -> None:
        trace: list[scheduler_sim.TokenRoute] = []
        for i in range(50):
            trace.append(scheduler_sim.TokenRoute(t_ms=float(i) * 0.001, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)))
        trace.append(scheduler_sim.TokenRoute(t_ms=0.0025, cls=scheduler_sim.LatencyClass.BATCH, candidates=(1,)))
        trace.sort(key=lambda r: r.t_ms)

        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=4,
            q_low=0,
            q_high=8,
        )
        base = dict(
            num_experts=8,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1000.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            k_mode="controller",
        )
        m_global = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, k_signal="global"), trace)
        m_mean = scheduler_sim.run_simulation(scheduler_sim.SimConfig(**base, k_signal="global_mean"), trace)
        idx = next(i for i, r in enumerate(trace) if r.candidates == (1,))
        self.assertLessEqual(m_mean.pending_signal_batch[idx], m_global.pending_signal_batch[idx])
        self.assertGreaterEqual(m_mean.chosen_k_batch[idx], m_global.chosen_k_batch[idx])

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

    def test_backpressure_units_work_caps_cost_scale(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), cost_scale=2.0),
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), cost_scale=2.0),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=2,
            service_ms=10.0,
            service_base_ms=0.0,
            service_per_task_ms=10.0,
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
        )
        m_tasks = scheduler_sim.run_simulation(dataclasses.replace(cfg, backpressure_units="tasks"), trace)
        m_work = scheduler_sim.run_simulation(dataclasses.replace(cfg, backpressure_units="work"), trace)
        self.assertEqual(m_tasks.dropped_tokens_backpressure, 0)
        self.assertEqual(m_work.dropped_tokens_backpressure, 1)

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

    def test_pending_work_depth_time_weighted_p95_tracks_peak_backlog(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), cost_scale=2.0),
            scheduler_sim.TokenRoute(t_ms=5.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), cost_scale=2.0),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=1.0,
            service_base_ms=0.0,
            service_per_task_ms=10.0,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertEqual(s["pending_work_depth_time_weighted_p95"], 4.0)
        self.assertEqual(s["lo_queue_work_depth_time_weighted_p95"], 2.0)

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

    def test_mtp_accept_model_hist_can_force_bonus_tokens(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i) * 0.01,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
            for i in range(20)
        ]
        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        )
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=0.01,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            mtp_draft_len=2,
            mtp_accept_model="hist",
            mtp_accept_hist=(0.0, 0.0, 1.0),
            mtp_accept_prob=0.0,
            mtp_accept_decay=1.0,
            mtp_draft_cost_scale=0.25,
            mtp_draft_attempt_policy="full",
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.mtp_bonus_tokens, len(trace))
        self.assertTrue(all(al == 3 for al in m.mtp_accept_len_per_step))

    def test_expected_mtp_accept_len_hist_is_weighted_mean(self) -> None:
        exp = scheduler_sim.expected_mtp_accept_len(
            2,
            0.0,
            1.0,
            mtp_accept_model="hist",
            mtp_accept_hist=(0.0, 0.25, 0.75),
        )
        self.assertAlmostEqual(exp, (2.0 * 0.25) + (3.0 * 0.75), places=6)

    def test_mtp_accept_model_hist_requires_len_draft_plus_one(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
            )
        ]
        adapt = scheduler_sim.AdaptiveKConfig(
            k_min_interactive=1,
            k_max_interactive=1,
            k_min_batch=1,
            k_max_batch=1,
            q_low=0,
            q_high=0,
        )
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=10_000,
            service_ms=0.01,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=adapt,
            mtp_draft_len=2,
            mtp_accept_model="hist",
            mtp_accept_hist=(1.0, 0.0),
            mtp_draft_cost_scale=0.25,
        )
        with self.assertRaises(ValueError):
            scheduler_sim.run_simulation(cfg, trace)

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

    def test_trace_summary_includes_dflash_accept_len(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"dflash_accept_len":3,"accepted_dflash":2,"rejected_dflash":0}\n')
                f.write('{"t_ms":1.0,"cls":"batch","candidates":[0],"accepted_dflash":1,"rejected_dflash":1}\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", path, "--trace-summary", "--json"])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue().strip())
            present = out["optional_fields_present"]
            self.assertEqual(present["dflash_accept_len"], 1)
            self.assertEqual(present["accepted_dflash"], 1)
            self.assertEqual(present["rejected_dflash"], 0)
            dsum = out["dflash_accept_len_derived"]
            self.assertEqual(dsum["count"], 2)
            self.assertEqual(dsum["min"], 2.0)
            self.assertEqual(dsum["max"], 3.0)
        finally:
            os.unlink(path)

    def test_trace_summary_derives_dflash_accept_len_from_rejected_with_meta(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"type":"meta","meta":{"dflash_draft_len":4}}\n')
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"rejected_dflash":3}\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", path, "--trace-summary", "--json"])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue().strip())
            present = out["optional_fields_present"]
            self.assertEqual(present["dflash_accept_len"], 0)
            self.assertEqual(present["accepted_dflash"], 0)
            self.assertEqual(present["rejected_dflash"], 1)
            dsum = out["dflash_accept_len_derived"]
            self.assertEqual(dsum["count"], 1)
            self.assertEqual(dsum["min"], 2.0)
            self.assertEqual(dsum["max"], 2.0)
        finally:
            os.unlink(path)

    def test_sim_summary_derives_dflash_accept_len_from_rejected_with_meta(self) -> None:
        fd, path = tempfile.mkstemp(prefix="sched_trace_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"type":"meta","meta":{"num_experts":1,"dflash_draft_len":4}}\n')
                f.write('{"t_ms":0.0,"cls":"batch","candidates":[0],"rejected_dflash":3}\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = scheduler_sim.main(["--trace-jsonl", path, "--num-experts", "1", "--service-ms", "1.0", "--expert-queue-max", "16", "--summary-json"])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue().strip())
            s = out["summary"]
            self.assertEqual(int(s["dflash_steps"]), 1)
            self.assertEqual(int(s["dflash_output_tokens"]), 2)
            self.assertEqual(int(s["dflash_bonus_tokens"]), 1)
            self.assertAlmostEqual(float(s["dflash_mean_accept_len"]), 2.0, places=6)
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
            expert_parallelism=16,
            expert_queue_max=10_000,
            service_ms=0.01,
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
            expert_parallelism=16,
            expert_queue_max=10_000,
            service_ms=0.01,
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

    def test_mtp_verify_layer0_backpressure_clamps_accept_len(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                mtp_accept_len=3,
            ),
            scheduler_sim.TokenRoute(
                t_ms=0.1,
                cls=scheduler_sim.LatencyClass.INTERACTIVE,
                candidates=(0,),
                mtp_accept_len=1,
            ),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=2,
            expert_queue_reserve_interactive=1,
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
        token_states: list[scheduler_sim.TokenState] = []
        m = scheduler_sim.run_simulation(cfg, trace, token_states_out=token_states)
        self.assertEqual(len(token_states), 2)
        self.assertTrue(token_states[0].mtp_verify_layer0_skipped_backpressure)
        self.assertTrue(token_states[0].mtp_accept_len_clamped_backpressure)
        self.assertEqual(token_states[0].mtp_accept_len, 1)
        self.assertEqual(token_states[0].output_len, 1)
        self.assertEqual(m.mtp_verify_layer0_skipped_backpressure, 1)
        self.assertEqual(m.mtp_accept_len_clamped_backpressure, 1)
        self.assertEqual(m.mtp_accept_len_per_step[0], 1)

    def test_mtp_accounting_does_not_require_verify_layer0_admission(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
                layers=(
                    scheduler_sim.LayerRoute(candidates=(0,), cost_scale=1.0),
                    scheduler_sim.LayerRoute(candidates=(1,), cost_scale=1e-9),
                ),
            ),
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0, 1),
                layers=(
                    scheduler_sim.LayerRoute(candidates=(0,), cost_scale=1.0),
                    scheduler_sim.LayerRoute(candidates=(1,), cost_scale=1e-9),
                ),
            ),
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
                k_min_batch=1,
                k_max_batch=1,
                q_low=0,
                q_high=0,
            ),
            sim_seed=123,
            mtp_draft_len=1,
            mtp_accept_prob=0.0,
            mtp_accept_decay=1.0,
            mtp_draft_cost_scale=1.0,
        )
        m = scheduler_sim.run_simulation(cfg, trace)
        self.assertEqual(m.mtp_accept_len_per_step, [1, 1])
        self.assertEqual(m.mtp_output_tokens, 2)

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
            expert_parallelism=16,
            expert_queue_max=10_000,
            service_ms=0.01,
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
            expert_parallelism=16,
            expert_queue_max=10_000,
            service_ms=0.01,
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

    def test_trace_arrival_units_output_tokens_scales_trace_for_mtp_variants(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=float(i),
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                k=1,
            )
            for i in range(10)
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=16,
            expert_queue_max=10_000,
            service_ms=0.01,
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
        variants = [("mtp_on", {"mtp_draft_len": 2, "mtp_accept_prob": 1.0, "mtp_accept_decay": 1.0})]
        out = scheduler_sim.compare_simulation_summaries(cfg, trace, variants, arrival_units="output_tokens")
        base_tps = float(out["baseline"]["summary"]["output_token_throughput_tps"])  # type: ignore[index]
        mtp_tps = float(out["variants"]["mtp_on"]["summary"]["output_token_throughput_tps"])  # type: ignore[index]
        self.assertAlmostEqual(base_tps, mtp_tps, delta=2.0)

    def test_compare_allows_mtp_off_variant_on_mtp_trace(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(
                t_ms=0.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                k=1,
                mtp_accept_len=3,
            ),
            scheduler_sim.TokenRoute(
                t_ms=1.0,
                cls=scheduler_sim.LatencyClass.BATCH,
                candidates=(0,),
                k=1,
                mtp_accept_len=1,
            ),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=16,
            expert_queue_max=10_000,
            service_ms=0.01,
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
            mtp_draft_len=2,
            mtp_accept_prob=0.0,
            mtp_accept_decay=1.0,
        )
        out = scheduler_sim.compare_simulation_summaries(cfg, trace, [("mtp_off", {"mtp_draft_len": 0})])
        base_out = float(out["baseline"]["summary"]["output_tokens"])  # type: ignore[index]
        off_out = float(out["variants"]["mtp_off"]["summary"]["output_tokens"])  # type: ignore[index]
        self.assertGreater(base_out, off_out)
        self.assertEqual(float(out["variants"]["mtp_off"]["summary"]["mtp_accept_rate"]), 0.0)  # type: ignore[index]

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

    def test_trace_extract_maps_common_aliases(self) -> None:
        obj = {
            "ts_us": 5000,
            "latency_class": "interactive",
            "experts": [7, 3, 19],
            "router_scores": [0.9, 0.7, 0.4],
            "token_idx": 12,
            "accepted_mtp": 1,
            "rejected_mtp": 1,
            "decode_ms": 2.5,
            "kv_tokens": 2048,
            "expert_batch_size": 8,
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertAlmostEqual(float(rec["t_ms"]), 5.0)
        self.assertEqual(rec["cls"], "interactive")
        self.assertEqual(rec["token_index"], 12)
        self.assertEqual(rec["candidates"], [7, 3, 19])
        self.assertEqual(rec["scores"], [0.9, 0.7, 0.4])
        self.assertEqual(rec["accepted_mtp"], 1)
        self.assertEqual(rec["rejected_mtp"], 1)
        self.assertAlmostEqual(float(rec["decode_ms"]), 2.5)
        self.assertEqual(rec["kv_tokens"], 2048)
        self.assertEqual(rec["expert_batch_size"], 8)

    def test_trace_extract_maps_numeric_cls_to_latency_class(self) -> None:
        obj = {"t_ms": 0.0, "cls": 0, "candidates": [7, 3, 19]}
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["cls"], "interactive")
        self.assertEqual(rec["candidates"], [7, 3, 19])

        obj2 = {"t_ms": 0.0, "cls_id": 1, "candidates": [0]}
        rec2 = trace_extract.extract_route_record(obj2)
        self.assertIsNotNone(rec2)
        assert rec2 is not None
        self.assertEqual(rec2["cls"], "batch")

    def test_trace_load_jsonl_runtime_accepts_numeric_cls(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"t_ms": 0.0, "cls": 0, "candidates": [0]}))
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path, input_format="runtime", non_route_policy="error")
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0].cls, scheduler_sim.LatencyClass.INTERACTIVE)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_extract_maps_ns_timestamps(self) -> None:
        obj = {
            "ts_ns": 5_000_000,
            "latency_class": "interactive",
            "experts": [7, 3, 19],
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertAlmostEqual(float(rec["t_ms"]), 5.0)
        self.assertEqual(rec["cls"], "interactive")
        self.assertEqual(rec["candidates"], [7, 3, 19])

        obj2 = {"dt_ns": 200_000, "cls": "batch", "candidates": [0]}
        rec2 = trace_extract.extract_route_record(obj2)
        self.assertIsNotNone(rec2)
        assert rec2 is not None
        self.assertAlmostEqual(float(rec2["dt_ms"]), 0.2, places=6)
        self.assertEqual(rec2["cls"], "batch")

    def test_trace_extract_maps_nested_mtp_fields(self) -> None:
        obj = {
            "ts_us": 5000,
            "latency_class": "interactive",
            "route": {"experts": [7, 3, 19]},
            "mtp": {"accept_len": 2, "accepted": 1, "rejected": 0},
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["candidates"], [7, 3, 19])
        self.assertEqual(rec["mtp_accept_len"], 2)
        self.assertEqual(rec["accepted_mtp"], 1)
        self.assertEqual(rec["rejected_mtp"], 0)

        obj2 = {
            "t_ms": 0.0,
            "cls": "batch",
            "route": {"candidates": [0], "accept_len": 3, "mtp_accepted": 2, "mtp_rejected": 0},
        }
        rec2 = trace_extract.extract_route_record(obj2)
        self.assertIsNotNone(rec2)
        assert rec2 is not None
        self.assertEqual(rec2["candidates"], [0])
        self.assertEqual(rec2["mtp_accept_len"], 3)
        self.assertEqual(rec2["accepted_mtp"], 2)
        self.assertEqual(rec2["rejected_mtp"], 0)

    def test_trace_extract_maps_nested_dflash_fields_separately(self) -> None:
        obj = {
            "t_ms": 0.0,
            "cls": "batch",
            "route": {"candidates": [0]},
            "spec_decode": {"accept_len": 3, "accepted": 2, "rejected": 0},
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["candidates"], [0])
        self.assertEqual(rec.get("dflash_accept_len"), 3)
        self.assertEqual(rec.get("accepted_dflash"), 2)
        self.assertEqual(rec.get("rejected_dflash"), 0)
        self.assertNotIn("mtp_accept_len", rec)
        self.assertNotIn("accepted_mtp", rec)
        self.assertNotIn("rejected_mtp", rec)

        obj2 = {
            "t_ms": 0.0,
            "cls": "batch",
            "route": {"candidates": [0]},
            "spec_decode": {"mtp_accept_len": 2, "mtp_accepted": 1, "mtp_rejected": 1},
        }
        rec2 = trace_extract.extract_route_record(obj2)
        self.assertIsNotNone(rec2)
        assert rec2 is not None
        self.assertEqual(rec2.get("mtp_accept_len"), 2)
        self.assertEqual(rec2.get("accepted_mtp"), 1)
        self.assertEqual(rec2.get("rejected_mtp"), 1)
        self.assertNotIn("dflash_accept_len", rec2)
        self.assertNotIn("accepted_dflash", rec2)
        self.assertNotIn("rejected_dflash", rec2)

    def test_trace_extract_preserves_layers_and_unions_candidates(self) -> None:
        obj = {
            "t_ms": 1.0,
            "cls": "batch",
            "layers": [
                {"experts": [1, 2], "router_scores": [0.2, 0.1], "chosen_k": 1},
                {"route": {"experts": [2, 3], "router_scores": [0.5, 0.4], "k": 2, "cost_scale": 0.5}},
            ],
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["candidates"], [1, 2, 3])
        self.assertNotIn("scores", rec)
        self.assertNotIn("k", rec)
        layers = rec.get("layers")
        self.assertIsInstance(layers, list)
        assert isinstance(layers, list)
        self.assertEqual(len(layers), 2)
        self.assertEqual(layers[0].get("candidates"), [1, 2])
        self.assertEqual(layers[0].get("scores"), [0.2, 0.1])
        self.assertEqual(layers[0].get("k"), 1)
        self.assertEqual(layers[1].get("candidates"), [2, 3])
        self.assertEqual(layers[1].get("scores"), [0.5, 0.4])
        self.assertEqual(layers[1].get("k"), 2)
        self.assertAlmostEqual(float(layers[1].get("cost_scale", 0.0)), 0.5, places=6)

    def test_trace_extract_filters_route_type(self) -> None:
        route = {"type": "moe_route", "t_ms": 0.0, "cls": "batch", "candidates": [0]}
        other = {"type": "log", "t_ms": 0.0, "msg": "hello"}
        out = trace_extract.extract_jsonl_lines(
            [json.dumps(route), json.dumps(other)],
            route_type="moe_route",
            non_route_policy="skip",
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["candidates"], [0])

    def test_trace_extract_default_cls_fills_missing_cls(self) -> None:
        obj = {"t_ms": 0.0, "candidates": [0]}
        self.assertIsNone(trace_extract.extract_route_record(obj))
        rec = trace_extract.extract_route_record(obj, default_cls="batch")
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec["cls"], "batch")

    def test_trace_load_jsonl_runtime_default_cls_allows_missing_cls(self) -> None:
        tmp_path = ""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            tmp_path = f.name
            f.write(json.dumps({"t_ms": 0.0, "candidates": [0]}))
            f.write("\n")
        try:
            trace = scheduler_sim.load_trace_jsonl(tmp_path, input_format="runtime", non_route_policy="error", default_cls="interactive")
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0].cls, scheduler_sim.LatencyClass.INTERACTIVE)
        finally:
            if tmp_path != "" and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_trace_extract_non_json_line_skip_ignores(self) -> None:
        out = trace_extract.extract_jsonl_lines(
            [
                "not-json",
                json.dumps({"t_ms": 0.0, "cls": "interactive", "candidates": [0]}),
            ],
            non_route_policy="skip",
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["candidates"], [0])

    def test_trace_extract_non_json_line_error_raises(self) -> None:
        with self.assertRaises(ValueError):
            trace_extract.extract_jsonl_lines(
                [
                    "not-json",
                    json.dumps({"t_ms": 0.0, "cls": "interactive", "candidates": [0]}),
                ],
                non_route_policy="error",
            )

    def test_trace_extract_non_route_error_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            trace_extract.extract_jsonl_lines(
                [json.dumps({"type": "log", "t_ms": 0.0, "msg": "hello"})],
                route_type="moe_route",
                non_route_policy="error",
            )

    def test_trace_extract_embedded_json_extracts_route_record(self) -> None:
        route = {"type": "moe_route", "t_ms": 0.0, "cls": "interactive", "candidates": [0, 1, 2]}
        line = f"INFO scheduler route={json.dumps(route)} done"
        out = trace_extract.extract_jsonl_lines([line], non_route_policy="skip")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["candidates"], [0, 1, 2])

    def test_trace_extract_embedded_json_disabled_skips(self) -> None:
        route = {"type": "moe_route", "t_ms": 0.0, "cls": "interactive", "candidates": [0]}
        line = f"INFO scheduler route={json.dumps(route)} done"
        out = trace_extract.extract_jsonl_lines([line], non_route_policy="skip", allow_substrings=False)
        self.assertEqual(len(out), 0)

    def test_trace_extract_json_array_line_extracts_records(self) -> None:
        routes = [
            {"t_ms": 0.0, "cls": "interactive", "candidates": [0]},
            {"t_ms": 1.0, "cls": "batch", "candidates": [1]},
        ]
        out = trace_extract.extract_jsonl_lines([json.dumps(routes)], non_route_policy="skip")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["candidates"], [0])
        self.assertEqual(out[1]["candidates"], [1])

    def test_recommendations_quick_expert_queue_reserve_prevents_interactive_drops(self) -> None:
        from sim.scheduler import recommendations

        out = recommendations.run_recommendations(quick=True)
        scenario = out["scenarios"]["expert_queue_reserve"]
        base = scenario["results"]["baseline"]["summary"]
        no_reserve = scenario["results"]["variants"]["no_reserve"]["summary"]
        self.assertLessEqual(float(base["drop_frac_tokens_interactive"]), 1e-9)
        self.assertGreater(float(no_reserve["drop_frac_tokens_interactive"]), 0.0)

    def test_recommendations_quick_mtp_sweep_has_breakeven(self) -> None:
        from sim.scheduler import recommendations

        out = recommendations.run_recommendations(quick=True)
        sweep = out["scenarios"]["mtp_efficiency_sweep"]["sweep"]
        self.assertGreaterEqual(len(sweep), 3)
        worst = float(sweep[0]["service_slot_ms_per_output_token_ratio_vs_no_mtp"])
        best = float(sweep[-1]["service_slot_ms_per_output_token_ratio_vs_no_mtp"])
        self.assertGreaterEqual(worst, 1.0)
        self.assertLess(best, 1.0)

    def test_recommendations_quick_adaptive_k_batch_avoids_fixed_batch_k2_drop_spike(self) -> None:
        from sim.scheduler import recommendations

        out = recommendations.run_recommendations(quick=True)
        scenario = out["scenarios"]["adaptive_k_batch"]
        base = scenario["results"]["baseline"]["summary"]
        fixed_hi = scenario["results"]["variants"]["batch_k_fixed_2"]["summary"]
        base_drop = float(base["drop_frac_tokens"])
        fixed_hi_drop = float(fixed_hi["drop_frac_tokens"])
        self.assertLess(base_drop, fixed_hi_drop)
        self.assertGreaterEqual(fixed_hi_drop, (base_drop + 0.05))

    def test_recommendations_quick_mtp_congestion_sweep_stop_at_reject_reduces_overhead_at_zero_accept(self) -> None:
        from sim.scheduler import recommendations

        out = recommendations.run_recommendations(quick=True)
        sweep = out["scenarios"]["mtp_congestion_sweep"]["sweep"]
        row0 = next(r for r in sweep if float(r["accept_prob"]) == 0.0)
        full = row0["mtp_full"]
        stop = row0["mtp_stop_at_reject"]
        self.assertLess(float(stop["service_slot_ms_per_output_token"]), float(full["service_slot_ms_per_output_token"]))

    def test_recommendations_runtime_trace_mtp_ablation_runs(self) -> None:
        from sim.scheduler import recommendations
        from sim.scheduler import scheduler_sim

        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0, 1, 2), mtp_accept_len=3),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1, 2), mtp_accept_len=1),
            scheduler_sim.TokenRoute(t_ms=2.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0, 1, 2), mtp_accept_len=2),
        ]

        out = recommendations.run_runtime_trace_mtp_ablation(trace=trace, trace_meta={})
        self.assertEqual(out["name"], "runtime_trace_mtp_ablation")
        self.assertIn("trace_summary", out)
        self.assertIn("results", out)
        self.assertIn("arrival_units_steps", out["results"])
        self.assertIn("arrival_units_output_tokens", out["results"])
        self.assertIn("baseline", out["results"]["arrival_units_steps"])
        self.assertIn("variants", out["results"]["arrival_units_steps"])
        self.assertIn("mtp_off", out["results"]["arrival_units_steps"]["variants"])

    def test_trace_sweep_runs_on_synthetic_trace(self) -> None:
        from sim.scheduler import scheduler_sim
        from sim.scheduler import trace_sweep

        trace_cfg = scheduler_sim.TwoStreamTraceConfig(
            num_tokens=400,
            num_experts=8,
            num_candidates=8,
            interactive_arrival_rate_tps=200.0,
            batch_arrival_rate_tps=200.0,
            interactive_burst_prob=0.0,
            interactive_burst_scale=1.0,
            batch_burst_prob=0.0,
            batch_burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        trace = scheduler_sim.generate_twostream_trace(trace_cfg)
        base_cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=1.0,
            starvation_ms=100.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=4,
                k_min_batch=1,
                k_max_batch=2,
                q_low=8,
                q_high=48,
            ),
            sim_seed=123,
        )

        out = trace_sweep.run_trace_sweeps(trace, base_cfg, trace_meta={"note": "unit_test"}, max_tokens=200)
        scenarios = out.get("scenarios", {})
        self.assertIn("k_signal_policy", scenarios)
        self.assertIn("admit_policy", scenarios)
        self.assertIn("adaptive_k_policy", scenarios)
        self.assertIn("starvation_knobs", scenarios)
        self.assertIn("expert_queue_max_sweep", scenarios)
        self.assertIn("expert_queue_reserve_sweep", scenarios)
        self.assertIn("expert_batching_sweep", scenarios)
        self.assertNotIn("mtp_attempt_policy", scenarios)
        self.assertNotIn("pending_units", scenarios)
        self.assertNotIn("k_scope", scenarios)

        ksig = scenarios["k_signal_policy"]["results"]
        self.assertIn("baseline", ksig)
        self.assertIn("variants", ksig)
        self.assertIn("k_signal_global", ksig["variants"])

        adaptive = scenarios["adaptive_k_policy"]["results"]["variants"]
        self.assertIn("k_fixed_min", adaptive)
        self.assertIn("k_fixed_max", adaptive)

        reserve = scenarios["expert_queue_reserve_sweep"]["results"]["variants"]
        self.assertIn("reserve_0", reserve)

        qmax = scenarios["expert_queue_max_sweep"]["results"]["variants"]
        self.assertIn("queue_max_32", qmax)
        self.assertIn("queue_max_128", qmax)

        summary = out.get("trace_summary")
        self.assertIsInstance(summary, dict)
        self.assertIn("tokens", summary)

    def test_trace_sweep_includes_score_desc_admit_policy_when_scores_present(self) -> None:
        from sim.scheduler import scheduler_sim
        from sim.scheduler import trace_sweep

        trace_cfg = scheduler_sim.TwoStreamTraceConfig(
            num_tokens=250,
            num_experts=8,
            num_candidates=8,
            interactive_arrival_rate_tps=200.0,
            batch_arrival_rate_tps=200.0,
            interactive_burst_prob=0.0,
            interactive_burst_scale=1.0,
            batch_burst_prob=0.0,
            batch_burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
            synthetic_score_mode="random",
        )
        trace = scheduler_sim.generate_twostream_trace(trace_cfg)
        base_cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=1.0,
            starvation_ms=100.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=4,
                k_min_batch=1,
                k_max_batch=2,
                q_low=8,
                q_high=48,
            ),
            sim_seed=123,
        )

        out = trace_sweep.run_trace_sweeps(trace, base_cfg, max_tokens=100)
        admit = out["scenarios"]["admit_policy"]["results"]["variants"]
        self.assertIn("admit_score_desc", admit)

    def test_trace_sweep_includes_pending_units_when_cost_scale_present(self) -> None:
        from sim.scheduler import scheduler_sim
        from sim.scheduler import trace_sweep

        trace_cfg = scheduler_sim.TwoStreamTraceConfig(
            num_tokens=250,
            num_experts=8,
            num_candidates=8,
            interactive_arrival_rate_tps=200.0,
            batch_arrival_rate_tps=200.0,
            interactive_burst_prob=0.0,
            interactive_burst_scale=1.0,
            batch_burst_prob=0.0,
            batch_burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
            synthetic_cost_scale_mode="lognormal",
            synthetic_cost_scale_log_sigma=0.9,
        )
        trace = scheduler_sim.generate_twostream_trace(trace_cfg)
        base_cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=1.0,
            starvation_ms=100.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=4,
                k_min_batch=1,
                k_max_batch=2,
                q_low=8,
                q_high=48,
            ),
            sim_seed=123,
        )

        out = trace_sweep.run_trace_sweeps(trace, base_cfg, max_tokens=100)
        self.assertIn("pending_units", out["scenarios"])
        variants = out["scenarios"]["pending_units"]["results"]["variants"]
        self.assertIn("pending_work", variants)
        self.assertIn("backpressure_units", out["scenarios"])
        variants_bp = out["scenarios"]["backpressure_units"]["results"]["variants"]
        self.assertIn("backpressure_work", variants_bp)

    def test_trace_sweep_includes_k_scope_when_multi_layer_controller(self) -> None:
        from sim.scheduler import scheduler_sim
        from sim.scheduler import trace_sweep

        trace_cfg = scheduler_sim.TwoStreamTraceConfig(
            num_tokens=250,
            num_experts=8,
            num_candidates=8,
            interactive_arrival_rate_tps=200.0,
            batch_arrival_rate_tps=200.0,
            interactive_burst_prob=0.0,
            interactive_burst_scale=1.0,
            batch_burst_prob=0.0,
            batch_burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
            num_layers=2,
        )
        trace = scheduler_sim.generate_twostream_trace(trace_cfg)
        base_cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=1.0,
            starvation_ms=100.0,
            hi_burst=0,
            promote_ms=0.0,
            adaptive_k=scheduler_sim.AdaptiveKConfig(
                k_min_interactive=1,
                k_max_interactive=4,
                k_min_batch=1,
                k_max_batch=2,
                q_low=8,
                q_high=48,
            ),
            sim_seed=123,
        )

        out = trace_sweep.run_trace_sweeps(trace, base_cfg, max_tokens=100)
        self.assertIn("k_scope", out["scenarios"])
        variants = out["scenarios"]["k_scope"]["results"]["variants"]
        self.assertIn("k_scope_layer", variants)

    def test_trace_sweep_includes_mtp_attempt_policy_when_enabled(self) -> None:
        from sim.scheduler import scheduler_sim
        from sim.scheduler import trace_sweep

        trace_cfg = scheduler_sim.TraceConfig(
            num_tokens=250,
            num_experts=8,
            num_candidates=8,
            interactive_prob=0.5,
            arrival_rate_tps=200.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        trace = scheduler_sim.generate_synthetic_trace(trace_cfg)
        base_cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=1.0,
            starvation_ms=100.0,
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
            mtp_accept_prob=0.4,
            mtp_accept_decay=0.8,
            mtp_draft_cost_scale=0.25,
        )
        out = trace_sweep.run_trace_sweeps(trace, base_cfg)
        self.assertIn("mtp_attempt_policy", out.get("scenarios", {}))

    def test_trace_sweep_includes_mtp_accept_prob_sweep_when_trace_omits_accept_len(self) -> None:
        from sim.scheduler import scheduler_sim
        from sim.scheduler import trace_sweep

        trace_cfg = scheduler_sim.TraceConfig(
            num_tokens=250,
            num_experts=8,
            num_candidates=8,
            interactive_prob=0.5,
            arrival_rate_tps=200.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        trace = scheduler_sim.generate_synthetic_trace(trace_cfg)
        base_cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=1.0,
            starvation_ms=100.0,
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
            mtp_accept_prob=0.4,
            mtp_accept_decay=0.8,
            mtp_draft_cost_scale=0.25,
        )
        out = trace_sweep.run_trace_sweeps(trace, base_cfg)
        scenarios = out.get("scenarios", {})
        self.assertIn("mtp_accept_prob_sweep", scenarios)
        variants = scenarios["mtp_accept_prob_sweep"]["results"]["variants"]
        self.assertIn("accept_prob_0", variants)
        self.assertIn("accept_prob_20", variants)
        self.assertNotIn("accept_prob_40", variants)
        self.assertIn("accept_prob_100", variants)

    def test_trace_sweep_omits_mtp_accept_prob_sweep_when_trace_has_accept_len(self) -> None:
        import dataclasses

        from sim.scheduler import scheduler_sim
        from sim.scheduler import trace_sweep

        trace_cfg = scheduler_sim.TraceConfig(
            num_tokens=120,
            num_experts=8,
            num_candidates=8,
            interactive_prob=0.5,
            arrival_rate_tps=200.0,
            burst_prob=0.0,
            burst_scale=1.0,
            zipf_alpha=1.1,
            seed=123,
        )
        trace0 = scheduler_sim.generate_synthetic_trace(trace_cfg)
        trace = list(trace0)
        trace[0] = dataclasses.replace(trace[0], mtp_accept_len=1)
        base_cfg = scheduler_sim.SimConfig(
            num_experts=trace_cfg.num_experts,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=1.0,
            starvation_ms=100.0,
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
            mtp_accept_prob=0.4,
            mtp_accept_decay=0.8,
            mtp_draft_cost_scale=0.25,
        )
        out = trace_sweep.run_trace_sweeps(trace, base_cfg)
        scenarios = out.get("scenarios", {})
        self.assertIn("mtp_attempt_policy", scenarios)
        self.assertNotIn("mtp_accept_prob_sweep", scenarios)

    def test_summary_reports_forced_batch_starts(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=2.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=10.0,
            starvation_ms=1e9,
            hi_burst=1,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertEqual(float(s.get("forced_batch_starts", -1.0)), 1.0)
        self.assertAlmostEqual(float(s.get("forced_batch_start_frac", -1.0)), 1.0 / 3.0, places=9)

    def test_summary_reports_promoted_tasks(self) -> None:
        trace = [
            scheduler_sim.TokenRoute(t_ms=0.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=1.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=2.0, cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,)),
            scheduler_sim.TokenRoute(t_ms=3.0, cls=scheduler_sim.LatencyClass.INTERACTIVE, candidates=(0,)),
        ]
        cfg = scheduler_sim.SimConfig(
            num_experts=1,
            expert_parallelism=1,
            expert_queue_max=64,
            service_ms=10.0,
            starvation_ms=1e9,
            hi_burst=0,
            promote_ms=5.0,
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
        s = scheduler_sim.compare_summary_jsonable(m)
        self.assertEqual(float(s.get("promoted_tasks", -1.0)), 1.0)
        self.assertAlmostEqual(float(s.get("promoted_task_frac", -1.0)), 0.25, places=9)

    def test_recommendations_quick_expert_batching_reduces_service_per_output_token(self) -> None:
        from sim.scheduler import recommendations

        out = recommendations.run_recommendations(quick=True)
        scenario = out["scenarios"]["expert_batching"]
        base = scenario["results"]["baseline"]["summary"]
        b4 = scenario["results"]["variants"]["batch_max_batch_4"]["summary"]
        self.assertLess(float(b4["service_slot_ms_per_output_token"]), float(base["service_slot_ms_per_output_token"]))
        self.assertLess(float(b4["drop_frac_tokens"]), float(base["drop_frac_tokens"]))


if __name__ == "__main__":
    unittest.main()
