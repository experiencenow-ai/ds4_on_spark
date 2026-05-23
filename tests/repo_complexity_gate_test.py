import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "score_repo_complexity.py"


def run_script(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd or REPO_ROOT),
        text=True,
        capture_output=True,
    )


class RepoComplexityGateTest(unittest.TestCase):
    def test_complexity_scan_uses_centaur_profile(self) -> None:
        result = run_script("scan", "--limit", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["format"], "ds4-repo-centaur-complexity-v1")
        self.assertEqual(record["profile_source"], "centaur.centaur_complexity")
        self.assertEqual(record["scan"]["profile_id"], "locality_modularity_state_dry_v5")
        self.assertGreater(record["scan"]["score"], 0)
        self.assertLessEqual(len(record["scan"]["top_files"]), 3)

    def test_complexity_gate_rejects_score_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = json.loads(run_script("scan", "--root", str(REPO_ROOT), "--limit", "3").stdout)
            baseline = json.loads(json.dumps(current))
            baseline["scan"]["score"] = max(0.0, float(current["scan"]["score"]) - 1.0)
            (root / ".complexity-baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
            result = run_script("gate", "--root", str(REPO_ROOT), "--baseline", str(root / ".complexity-baseline.json"), "--limit", "3")
        self.assertEqual(result.returncode, 1)
        gate = json.loads(result.stdout)
        self.assertEqual(gate["decision"], "reject")
        self.assertTrue(any(item["name"] == "score" and item["delta"] > 0 for item in gate["violations"]))

    def test_complexity_gate_accepts_recorded_baseline(self) -> None:
        result = run_script("gate", "--limit", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        gate = json.loads(result.stdout)
        self.assertIs(gate["gate_satisfied"], True)
        self.assertEqual(gate["decision"], "accept")


if __name__ == "__main__":
    unittest.main()
