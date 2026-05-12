import unittest

from sim.scheduler import expert_queue_probe


class SchedulerExpertQueueProbeTest(unittest.TestCase):
    def test_probe_deterministic_small_batch_all_rows(self) -> None:
        layers = [
            [
                [0, 1],
                [2, 3],
            ]
        ]
        cfg = expert_queue_probe.ExpertQueueProbeConfig(
            experts=4,
            topk=2,
            batches=(2,),
            trials=5,
            seed=123,
            strict_expert_ids=True,
        )
        out = expert_queue_probe.analyze_ds4_ffn_moe_topk_layers(layers, cfg)
        self.assertEqual(out.tokens_per_layer, 2)
        self.assertEqual(out.num_layers, 1)
        self.assertEqual(out.invalid_expert_ids, 0)
        self.assertEqual(out.batches["2"]["active"]["median"], 4.0)
        self.assertEqual(out.batches["2"]["max_depth"]["median"], 1.0)
        self.assertEqual(out.batches["2"]["pair_speedup_cap6"]["median"], 1.0)

    def test_probe_rejects_out_of_range_expert_ids_when_strict(self) -> None:
        layers = [
            [
                [0, 99],
            ]
        ]
        cfg = expert_queue_probe.ExpertQueueProbeConfig(
            experts=4,
            topk=2,
            batches=(1,),
            trials=1,
            seed=1,
            strict_expert_ids=True,
        )
        with self.assertRaises(ValueError):
            expert_queue_probe.analyze_ds4_ffn_moe_topk_layers(layers, cfg)

    def test_probe_allows_out_of_range_expert_ids_when_not_strict(self) -> None:
        layers = [
            [
                [0, 99],
            ]
        ]
        cfg = expert_queue_probe.ExpertQueueProbeConfig(
            experts=4,
            topk=2,
            batches=(1,),
            trials=1,
            seed=1,
            strict_expert_ids=False,
        )
        out = expert_queue_probe.analyze_ds4_ffn_moe_topk_layers(layers, cfg)
        self.assertEqual(out.invalid_expert_ids, 1)

