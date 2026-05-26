from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "xhigh_clean_workspace.py"


class XhighCleanWorkspaceTests(unittest.TestCase):
    def test_dry_run_prints_detached_worktree_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "repo"
            target = Path(tmp) / "workspaces" / "xhigh0"
            source.mkdir()
            subprocess.run(["git", "-C", str(source), "init"], check=True, stdout=subprocess.PIPE)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-root",
                    str(source),
                    "--path",
                    str(target),
                    "--base-ref",
                    "origin/main",
                    "--dry-run",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("worktree add --detach", result.stdout)
            self.assertIn("origin/main", result.stdout)


if __name__ == "__main__":
    unittest.main()
