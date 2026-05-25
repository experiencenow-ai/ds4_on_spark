from __future__ import annotations

import json
from pathlib import Path
import unittest

from ds4_agent.loop import FakeChatModel, run_agent_loop
from ds4_agent.tool_calls import extract_tool_calls
from ds4_tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "tools" / "registry.jsonl"


class AgentLoopTests(unittest.TestCase):
    def test_openai_tool_call_parser(self) -> None:
        calls = extract_tool_calls(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "tool:ds4.json.validate", "arguments": "{\"text\": \"{}\"}"},
                    }
                ],
            }
        )
        self.assertEqual(calls[0].tool_id, "tool:ds4.json.validate")
        self.assertEqual(calls[0].arguments, {"text": "{}"})

    def test_dsml_tool_call_parser(self) -> None:
        calls = extract_tool_calls(
            {
                "role": "assistant",
                "content": '<｜DSML｜tool_calls><｜DSML｜invoke name="tool:ds4.sha256"><｜DSML｜parameter name="text">abc</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>',
            }
        )
        self.assertEqual(calls[0].tool_id, "tool:ds4.sha256")
        self.assertEqual(calls[0].arguments["text"], "abc")

    def test_agent_invokes_allowed_tool(self) -> None:
        model = FakeChatModel(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "tool:ds4.json.validate",
                                "arguments": json.dumps({"text": "{\"ok\": true}"}),
                            },
                        }
                    ],
                },
                {"role": "assistant", "content": "valid"},
            ]
        )
        result = run_agent_loop(
            model=model,
            registry=ToolRegistry.load(REGISTRY),
            initial_messages=[{"role": "user", "content": "validate json"}],
            allowed_tool_prefixes=["tool:ds4."],
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["round_count"], 1)
        self.assertTrue(result["rounds"][0]["tool_results"][0]["ok"])

    def test_agent_blocks_disallowed_tool(self) -> None:
        model = FakeChatModel(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "tool:repo.tests.echo_contract",
                                "arguments": json.dumps({"message": "hello"}),
                            },
                        }
                    ],
                },
                {"role": "assistant", "content": "blocked"},
            ]
        )
        result = run_agent_loop(
            model=model,
            registry=ToolRegistry.load(REGISTRY),
            allowed_tool_prefixes=["tool:ds4."],
        )
        self.assertFalse(result["rounds"][0]["tool_results"][0]["ok"])
        self.assertIn("denied", result["rounds"][0]["tool_results"][0]["error"])


if __name__ == "__main__":
    unittest.main()
