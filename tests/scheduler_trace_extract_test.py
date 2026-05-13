import unittest

from sim.scheduler import trace_extract


class SchedulerTraceExtractTest(unittest.TestCase):
    def test_extract_route_record_coerces_numeric_strings(self) -> None:
        obj = {
            "t_ms": "1.25",
            "cls": "0",
            "route": {"expert_id": "7", "k": "2"},
            "mtp": {"accepted": "1", "rejected": "0"},
            "cost_scale": "1.5",
            "decode_ms": "0.75",
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.get("t_ms"), 1.25)
        self.assertEqual(rec.get("cls"), "interactive")
        self.assertEqual(rec.get("candidates"), [7])
        self.assertEqual(rec.get("k"), 2)
        self.assertEqual(rec.get("accepted_mtp"), 1)
        self.assertEqual(rec.get("rejected_mtp"), 0)
        self.assertEqual(rec.get("cost_scale"), 1.5)
        self.assertEqual(rec.get("decode_ms"), 0.75)

    def test_extract_route_record_coerces_nested_layer_cost_scale(self) -> None:
        obj = {
            "t_ms": 0.0,
            "cls": "batch",
            "route": {
                "layers": [
                    {"candidates": ["1", "2"], "k": "1", "cost_scale": "2.0"},
                    {"candidates": ["3"], "k": "1", "cost_scale": "1.0"},
                ]
            },
        }
        rec = trace_extract.extract_route_record(obj)
        self.assertIsNotNone(rec)
        assert rec is not None
        layers = rec.get("layers")
        self.assertIsInstance(layers, list)
        assert isinstance(layers, list)
        self.assertEqual(layers[0].get("cost_scale"), 2.0)
        self.assertEqual(layers[1].get("cost_scale"), 1.0)

    def test_pack_layers_by_token_index_orders_by_layer_index(self) -> None:
        routes = [
            {"token_index": 0, "layer_index": 2, "t_ms": 0.0, "cls": "batch", "candidates": [3]},
            {"token_index": 0, "layer_index": 0, "t_ms": 0.0, "cls": "batch", "candidates": [1]},
            {"token_index": 0, "layer_index": 1, "t_ms": 0.0, "cls": "batch", "candidates": [2]},
        ]
        packed = trace_extract.pack_layers_by_token_index(routes, require_layer_index=True, strict=True)
        self.assertEqual(len(packed), 1)
        rec = packed[0]
        self.assertEqual(rec["token_index"], 0)
        self.assertEqual(rec["cls"], "batch")
        self.assertEqual(rec["t_ms"], 0.0)
        self.assertEqual(rec["candidates"], [1, 2, 3])
        layers = rec.get("layers")
        self.assertIsInstance(layers, list)
        self.assertEqual([l["candidates"] for l in layers], [[1], [2], [3]])
        self.assertEqual([l.get("layer_index") for l in layers], [0, 1, 2])

    def test_pack_layers_by_token_index_rejects_time_mismatch(self) -> None:
        routes = [
            {"token_index": 0, "layer_index": 0, "t_ms": 0.0, "cls": "batch", "candidates": [1]},
            {"token_index": 0, "layer_index": 1, "t_ms": 1.0, "cls": "batch", "candidates": [2]},
        ]
        with self.assertRaises(ValueError):
            trace_extract.pack_layers_by_token_index(routes, require_layer_index=True, strict=True)

    def test_pack_layers_by_token_index_requires_token_index(self) -> None:
        routes = [{"t_ms": 0.0, "cls": "batch", "candidates": [1]}]
        with self.assertRaises(ValueError):
            trace_extract.pack_layers_by_token_index(routes, require_layer_index=False, strict=True)
