from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_diffusiongemma_gguf_eval.py"


def load_script():
    spec = importlib.util.spec_from_file_location("ds4_diffusiongemma_gguf_eval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ds4_diffusiongemma_gguf_eval"] = module
    spec.loader.exec_module(module)
    return module


class DiffusionGemmaGgufEvalTests(unittest.TestCase):
    def test_write_compsec_requests_with_thinking_prompt(self) -> None:
        dg = load_script()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "requests.jsonl"
            dg.main([
                "write-requests",
                "--out-jsonl",
                str(out),
                "--source",
                "COMPSEC",
                "--prompt-mode",
                "thinking",
                "--max-output-tokens",
                "2048",
            ])
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 17)
        self.assertTrue(rows[0]["request_id"].startswith("diffusiongemma-thinking-000-compsec-076"))
        self.assertEqual(rows[0]["max_output_tokens"], 2048)
        messages = rows[0]["input"]["messages"]
        self.assertIn("reasoning channel", messages[0]["content"])
        self.assertIn("Answer: <line number", messages[1]["content"])
        self.assertEqual(rows[0]["input"]["metadata"]["ds4_eval"]["answer"], "17-20")

    def test_grade_accepts_diffusiongemma_collect_shape(self) -> None:
        dg = load_script()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            requests = root / "requests.jsonl"
            collect = root / "collect.json"
            grade = root / "grade.json"
            dg.main(["write-requests", "--out-jsonl", str(requests), "--source", "COMPSEC", "--limit", "1"])
            row = json.loads(requests.read_text(encoding="utf-8").splitlines()[0])
            collect.write_text(json.dumps({
                "format": "diffusiongemma-collect-v1",
                "results": [{
                    "request": {"request_id": row["request_id"]},
                    "result": {
                        "request_id": row["request_id"],
                        "output": {"text": "Reasoning omitted.\nAnswer: 20"},
                        "usage": {"completion_tokens": 4},
                    },
                }],
            }), encoding="utf-8")
            dg.main(["grade", "--requests-jsonl", str(requests), "--collect-json", str(collect), "--out-json", str(grade)])
            summary = json.loads(grade.read_text(encoding="utf-8"))
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["rows"][0]["got"], "20")


if __name__ == "__main__":
    unittest.main()
