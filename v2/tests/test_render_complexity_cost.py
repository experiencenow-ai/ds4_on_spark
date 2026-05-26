from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_complexity_cost.py"


class RenderComplexityCostTests(unittest.TestCase):
    def test_rendered_report_shows_cost_and_gate_scope(self) -> None:
        payload = {
            "gate_satisfied": True,
            "base_ref": "abc123",
            "profile_id": "fake",
            "baseline": {"score": 10.0, "file_count": 2, "total_line_count": 20},
            "current": {"score": 12.5, "file_count": 3, "total_line_count": 25},
            "cost": {"score_delta": 2.5, "file_count_delta": 1, "total_line_count_delta": 5},
            "checks": [
                {"name": "score", "baseline": 10.0, "current": 12.5, "delta": 2.5, "gated": False, "ok": True},
                {"name": "max_function_lines", "baseline": 40, "current": 40, "delta": 0, "gated": True, "ok": True},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            gate = Path(tmp) / "gate.json"
            out = Path(tmp) / "cost.md"
            gate.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), str(gate), "--output", str(out)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            text = out.read_text(encoding="utf-8")
            self.assertIn("<!-- ds4-complexity-cost-report -->", text)
            self.assertIn("`+2.5`", text)
            self.assertIn("| Max function lines | `0` | `40` | `40` | gated | pass |", text)
            self.assertIn("Tests are excluded from scoring", text)


if __name__ == "__main__":
    unittest.main()
