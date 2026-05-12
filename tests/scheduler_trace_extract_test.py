import unittest

from sim.scheduler import trace_extract


class SchedulerTraceExtractTest(unittest.TestCase):
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
