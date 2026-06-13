from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from ds4_transfer.fast_copy import FileItem
from ds4_transfer.waterfall_copy import build_waterfall_plan, _load_keep_manifests


class WaterfallCopyPlanTests(unittest.TestCase):
    def test_routes_files_only_as_far_as_last_needed_node(self) -> None:
        nodes = ("spark0", "spark1", "spark2", "spark3")
        files = [
            FileItem("config.json", 10),
            FileItem("model-00001-of-000004.safetensors", 100),
            FileItem("model-00002-of-000004.safetensors", 200),
            FileItem("model-00003-of-000004.safetensors", 300),
            FileItem("model-00004-of-000004.safetensors", 400),
        ]
        keep_by_node = {
            "spark0": {"config.json", "model-00001-of-000004.safetensors"},
            "spark1": {"config.json", "model-00002-of-000004.safetensors"},
            "spark2": {"config.json", "model-00003-of-000004.safetensors"},
            "spark3": {"config.json", "model-00004-of-000004.safetensors"},
        }
        plan = build_waterfall_plan(files, nodes, keep_by_node)
        self.assertEqual([item.relpath for item in plan.edge_files[0]], [
            "config.json",
            "model-00002-of-000004.safetensors",
            "model-00003-of-000004.safetensors",
            "model-00004-of-000004.safetensors",
        ])
        self.assertEqual([item.relpath for item in plan.edge_files[1]], [
            "config.json",
            "model-00003-of-000004.safetensors",
            "model-00004-of-000004.safetensors",
        ])
        self.assertEqual([item.relpath for item in plan.edge_files[2]], [
            "config.json",
            "model-00004-of-000004.safetensors",
        ])

    def test_rejects_keep_manifest_file_missing_from_source(self) -> None:
        nodes = ("spark0", "spark1")
        files = [FileItem("config.json", 10)]
        keep_by_node = {
            "spark0": {"config.json"},
            "spark1": {"config.json", "missing.safetensors"},
        }
        with self.assertRaises(ValueError):
            build_waterfall_plan(files, nodes, keep_by_node)

    def test_loads_per_node_keep_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "spark0_keep.txt").write_text("config.json\n# comment\nmodel-00001.safetensors\n", encoding="utf-8")
            (root / "spark1_keep.txt").write_text("config.json\nmodel-00002.safetensors\n", encoding="utf-8")
            keep = _load_keep_manifests(("spark0", "spark1"), str(root), "{node}_keep.txt")
        self.assertEqual(keep["spark0"], {"config.json", "model-00001.safetensors"})
        self.assertEqual(keep["spark1"], {"config.json", "model-00002.safetensors"})


if __name__ == "__main__":
    unittest.main()
