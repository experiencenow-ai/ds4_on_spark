from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "score_repo_complexity.py"
ZERO_SCAN = {
    "score": 0,
    "max_function_lines": 0,
    "functions_over_50": 0,
    "functions_over_100": 0,
    "repeated_normalized_blocks": 0,
    "max_file_lines": 0,
    "max_file_function_count": 0,
    "file_count": 0,
    "total_line_count": 0,
}


FAKE_CENTAUR = """
from fnmatch import fnmatch
from pathlib import Path

def build_complexity_profile():
    return {"direction": "lower_is_better"}

def compact_complexity_scan(scan):
    return scan

def scan_complexity(root, limit=25, full=False, product_scope="ignore_aware", include_patterns=None, exclude_patterns=None):
    files = []
    for path in sorted(Path(root).rglob("*")):
        rel = str(path.relative_to(root))
        includes = include_patterns or ["**"]
        excludes = exclude_patterns or []
        if not any(fnmatch(rel, pattern) for pattern in includes):
            continue
        if any(fnmatch(rel, pattern) for pattern in excludes):
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        files.append({
            "relative_path": rel,
            "score": line_count,
            "line_count": line_count,
            "max_function_lines": 0,
            "function_count": 0,
        })
    total = sum(item["line_count"] for item in files)
    return {
        "profile_id": "fake",
        "file_count": len(files),
        "score": total,
        "components": {},
        "max_function_lines": 0,
        "functions_over_50": 0,
        "functions_over_100": 0,
        "repeated_normalized_blocks": 0,
        "total_line_count": total,
        "max_file_lines": max([0] + [item["line_count"] for item in files]),
        "max_file_function_count": 0,
        "top_files": files[:limit],
    }
"""


def write_fake_centaur(root: Path) -> Path:
    centaur = root / "centaur"
    centaur.mkdir()
    (centaur / "centaur_complexity.py").write_text(textwrap.dedent(FAKE_CENTAUR), encoding="utf-8")
    return centaur


def write_sample(root: Path, text: str) -> None:
    path = root / "v2" / "src" / "sample.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_test_sample(root: Path, text: str) -> None:
    path = root / "v2" / "tests" / "test_sample.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_pair(temp: Path, current_text: str, base_text: str = "x = 1\n") -> tuple[Path, Path, Path]:
    centaur = write_fake_centaur(temp)
    base = temp / "base"
    current = temp / "current"
    base.mkdir()
    current.mkdir()
    write_sample(base, base_text)
    write_sample(current, current_text)
    return centaur, base, current


class ScoreRepoComplexityTests(unittest.TestCase):
    def run_score(self, root: Path, centaur: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "CENTAUR_REPO": str(centaur)}
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--root", str(root)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_pr_gate_compares_current_tree_to_base_tree_not_static_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            centaur, base, current = make_pair(temp, "x = 1\n")
            (current / ".complexity-baseline.json").write_text(json.dumps({"scan": ZERO_SCAN}), encoding="utf-8")
            pr_gate = self.run_score(current, centaur, "gate-pr", "--base-root", str(base))
            self.assertEqual(pr_gate.returncode, 0, pr_gate.stderr + pr_gate.stdout)
            payload = json.loads(pr_gate.stdout)
            self.assertEqual(payload["mode"], "gate-pr")
            self.assertIn("cost", payload)
            self.assertEqual(payload["cost"]["score_delta"], 0.0)
            self.assertIn("score", payload["cost"]["informational_metrics"])
            self.assertFalse(next(item for item in payload["checks"] if item["name"] == "score")["gated"])
            self.assertFalse(next(item for item in payload["checks"] if item["name"] == "repeated_normalized_blocks")["gated"])
            baseline_gate = self.run_score(current, centaur, "gate-baseline")
            self.assertEqual(baseline_gate.returncode, 1)

    def test_pr_gate_rejects_growth_against_base_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            centaur, base, current = make_pair(temp, "x = 1\ny = 2\n")
            result = self.run_score(current, centaur, "gate-pr", "--base-root", str(base))
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["reason"], "complexity_regression")
            self.assertEqual(payload["violations"][0]["name"], "max_file_lines")

    def test_pr_gate_can_scan_a_git_base_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            centaur = write_fake_centaur(temp)
            repo = temp / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init"], check=True, stdout=subprocess.PIPE)
            write_sample(repo, "x = 1\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "base"], check=True, stdout=subprocess.PIPE)
            base_sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            write_sample(repo, "x = 1\ny = 2\n")
            result = self.run_score(repo, centaur, "gate-pr", "--base-ref", base_sha)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertEqual(json.loads(result.stdout)["base_ref"], base_sha)

    def test_tests_are_out_of_complexity_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            centaur, base, current = make_pair(temp, "x = 1\n")
            write_test_sample(current, "boom = 1\n" * 100)
            result = self.run_score(current, centaur, "gate-pr", "--base-root", str(base))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout)
            self.assertNotIn("v2/tests/**", payload["include_patterns"])
            self.assertEqual(payload["current"]["total_line_count"], payload["baseline"]["total_line_count"])


if __name__ == "__main__":
    unittest.main()
