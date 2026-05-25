from __future__ import annotations

import sys
import unittest

from ds4_tools.cpu_batch import CpuBatchService
from ds4_tools.registry import ToolRegistry

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "tools" / "registry.jsonl"


class CpuBatchTests(unittest.TestCase):
    def test_batch_preserves_order_and_service_shape(self) -> None:
        service = CpuBatchService()
        result = service.run_batch({
            "service": "sha256",
            "items": [{"custom_id": "b", "text": "bravo"}, {"custom_id": "a", "text": "alpha"}],
            "concurrency": 1,
        })
        self.assertTrue(result["ok"], result)
        self.assertEqual([item["custom_id"] for item in result["results"]], ["b", "a"])
        self.assertEqual(result["results"][0]["response"]["bytes"], 5)

    def test_json_required_keys_and_regex_flags(self) -> None:
        service = CpuBatchService()
        checked = service.run_batch({
            "service": "json_validate",
            "items": [{"text": "{\"ok\": true}", "required_keys": ["ok", "missing"]}],
        })
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["results"][0]["response"]["missing_keys"], ["missing"])
        matched = service.run_batch({
            "service": "regex_match",
            "items": [{"text": "Alpha\nbeta", "pattern": "^beta$", "flags": ["m"]}],
        })
        self.assertTrue(matched["results"][0]["response"]["matched"])

    def test_diff_stats_and_allowlisted_command(self) -> None:
        service = CpuBatchService(commands={"py_echo": {"argv": [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], "allow_stdin": True}})
        diffed = service.run_batch({
            "service": "diff_stats",
            "items": [{"text": "diff --git a/a.txt b/a.txt\n@@\n-old\n+new\n"}],
        })
        self.assertEqual(diffed["results"][0]["response"]["additions"], 1)
        self.assertEqual(diffed["results"][0]["response"]["deletions"], 1)
        commanded = service.run_batch({
            "service": "command",
            "items": [{"name": "py_echo", "stdin": "ok"}],
        })
        self.assertTrue(commanded["ok"], commanded)
        self.assertIn("OK", commanded["results"][0]["response"]["stdout"])

    def test_registry_exposes_cpu_batch(self) -> None:
        registry = ToolRegistry.load(REGISTRY)
        result = registry.invoke("tool:ds4.cpu.batch", {"service": "text_metrics", "items": [{"text": "one two"}]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["results"][0]["response"]["words"], 2)


if __name__ == "__main__":
    unittest.main()
