from __future__ import annotations

from pathlib import Path
import unittest

from ds4_tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "tools" / "registry.jsonl"


class ToolLatticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry.load(REGISTRY)

    def test_search_finds_json_tool(self) -> None:
        matches = self.registry.search("json validate")
        self.assertEqual(matches[0]["tool_id"], "tool:ds4.json.validate")

    def test_describe_returns_stable_location(self) -> None:
        tool = self.registry.describe("tool:ds4.json.validate")
        self.assertEqual(tool["tool_id"], "tool:ds4.json.validate")
        self.assertEqual(tool["stability"], "stable")

    def test_python_tool_invocation(self) -> None:
        result = self.registry.invoke("tool:ds4.json.validate", {"text": "{\"ok\": true}"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["type"], "dict")

    def test_schema_blocks_unexpected_arguments(self) -> None:
        result = self.registry.invoke("tool:ds4.sha256", {"text": "abc", "extra": "no"})
        self.assertFalse(result["ok"])
        self.assertIn("unsupported", result["error"])

    def test_bash_tool_is_fixed_argv_and_structured(self) -> None:
        result = self.registry.invoke("tool:repo.tests.echo_contract", {"message": "hello"})
        self.assertTrue(result["ok"], result)
        self.assertIn("hello", result["result"]["stdout"])


if __name__ == "__main__":
    unittest.main()
