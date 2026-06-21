from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ds4_waterfall_stage_model.py"


def load_script():
    spec = importlib.util.spec_from_file_location("ds4_waterfall_stage_model", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WaterfallStageModelTests(unittest.TestCase):
    def test_build_plan_maps_shards_to_pipeline_ranks(self) -> None:
        mod = load_script()
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "GLM-5.2-NVFP4"
            model_dir.mkdir()
            files = {
                "model-00001-of-00003.safetensors": b"a" * 11,
                "model-00002-of-00003.safetensors": b"b" * 13,
                "model-00003-of-00003.safetensors": b"c" * 17,
                "model-mtp.safetensors": b"d" * 19,
                "model-mtp-inputscales.safetensors": b"e" * 23,
                "config.json": b"{}",
            }
            for name, data in files.items():
                (model_dir / name).write_bytes(data)
            index = {
                "metadata": {},
                "weight_map": {
                    "model.embed_tokens.weight": "model-00001-of-00003.safetensors",
                    "model.layers.0.self_attn.q_proj.weight": "model-00001-of-00003.safetensors",
                    "model.layers.2.self_attn.q_proj.weight": "model-00002-of-00003.safetensors",
                    "model.layers.4.self_attn.q_proj.weight": "model-00003-of-00003.safetensors",
                    "model.layers.6.eh_proj.weight": "model-mtp.safetensors",
                    "model.layers.6.mlp.experts.0.down_proj.input_scale": "model-mtp-inputscales.safetensors",
                },
            }
            (model_dir / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
            args = Namespace(
                source_full_dir=str(model_dir),
                partition=[2, 2, 2],
                nodes=["spark0", "spark1", "spark2"],
                layer_regex=mod.DEFAULT_LAYER_REGEX,
                extra_safetensors="all",
                skip_cache=True,
                allow_partial=False,
            )
            by_rel = {item.rel: item for item in mod.build_plan(args)}
            self.assertEqual(by_rel["model-00001-of-00003.safetensors"].needed_ranks, (0, 1, 2))
            self.assertEqual(by_rel["model-00002-of-00003.safetensors"].needed_ranks, (1,))
            self.assertEqual(by_rel["model-00003-of-00003.safetensors"].needed_ranks, (2,))
            self.assertEqual(by_rel["model-mtp.safetensors"].needed_ranks, (0, 1, 2))
            self.assertEqual(by_rel["model-mtp-inputscales.safetensors"].needed_ranks, (0, 1, 2))
            self.assertEqual(by_rel["config.json"].needed_ranks, (0, 1, 2))
            summary = mod.summarize(list(by_rel.values()), 3)
            self.assertEqual(summary["edge_transfer_totals"][0]["edge"], [0, 1])
            self.assertEqual(summary["edge_transfer_totals"][1]["edge"], [1, 2])

    def test_partition_parser_accepts_already_parsed_lists(self) -> None:
        mod = load_script()
        self.assertEqual(mod.parse_partition([6, 4, 4]), [6, 4, 4])

    def test_missing_indexed_shards_are_rejected(self) -> None:
        mod = load_script()
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "model"
            model_dir.mkdir()
            (model_dir / "model-00001-of-00002.safetensors").write_bytes(b"a")
            index = {
                "metadata": {},
                "weight_map": {
                    "model.layers.0.self_attn.q_proj.weight": "model-00001-of-00002.safetensors",
                    "model.layers.1.self_attn.q_proj.weight": "model-00002-of-00002.safetensors",
                },
            }
            (model_dir / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
            args = Namespace(
                source_full_dir=str(model_dir),
                partition=[1, 1],
                nodes=["spark0", "spark1"],
                layer_regex=mod.DEFAULT_LAYER_REGEX,
                extra_safetensors="all",
                skip_cache=True,
                allow_partial=False,
                watch_source=False,
            )
            with self.assertRaises(SystemExit):
                mod.build_plan(args)
            args.allow_partial = True
            by_rel = {item.rel: item for item in mod.build_plan(args)}
            self.assertIn("model-00001-of-00002.safetensors", by_rel)

    def test_watch_source_keeps_missing_indexed_shards_pending(self) -> None:
        mod = load_script()
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "model"
            model_dir.mkdir()
            (model_dir / "model-00001-of-00002.safetensors").write_bytes(b"a")
            index = {
                "metadata": {},
                "weight_map": {
                    "model.layers.0.self_attn.q_proj.weight": "model-00001-of-00002.safetensors",
                    "model.layers.1.self_attn.q_proj.weight": "model-00002-of-00002.safetensors",
                },
            }
            (model_dir / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
            args = Namespace(
                source_full_dir=str(model_dir),
                partition=[1, 1],
                nodes=["spark0", "spark1"],
                layer_regex=mod.DEFAULT_LAYER_REGEX,
                extra_safetensors="all",
                skip_cache=True,
                allow_partial=False,
                watch_source=True,
            )
            by_rel = {item.rel: item for item in mod.build_plan(args)}
            self.assertEqual(by_rel["model-00001-of-00002.safetensors"].size, 1)
            self.assertEqual(by_rel["model-00002-of-00002.safetensors"].size, -1)
            self.assertEqual(by_rel["model-00002-of-00002.safetensors"].needed_ranks, (1,))


if __name__ == "__main__":
    unittest.main()
