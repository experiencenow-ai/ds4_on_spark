from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_github_pr.py"


def load_script():
    spec = importlib.util.spec_from_file_location("ds4_github_pr", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ds4_github_pr"] = module
    spec.loader.exec_module(module)
    return module


class GithubPrScriptTests(unittest.TestCase):
    def test_create_pushes_then_uses_explicit_head(self) -> None:
        gh = load_script()
        runs: list[list[str]] = []
        outs: list[list[str]] = []

        def fake_run(argv: list[str]) -> None:
            runs.append(argv)

        def fake_out(argv: list[str], *, check: bool = True):
            outs.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return ("codex/test", 0, "")
            if argv[:3] == ["gh", "pr", "view"]:
                return ("", 1, "not found")
            if argv[:3] == ["gh", "pr", "create"]:
                return ("https://example.invalid/pr/1", 0, "")
            raise AssertionError(argv)

        with patch.object(gh, "_run", fake_run), patch.object(gh, "_out", fake_out):
            self.assertEqual(gh.main(["create", "--title", "Test PR"]), 0)

        self.assertEqual(runs, [["git", "push", "origin", "HEAD:refs/heads/codex/test"]])
        self.assertIn(["gh", "pr", "create", "--head", "codex/test", "--base", "main", "--title", "Test PR", "--body", ""], outs)

    def test_create_reuses_existing_pr_after_push(self) -> None:
        gh = load_script()
        runs: list[list[str]] = []

        def fake_out(argv: list[str], *, check: bool = True):
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return ("codex/test", 0, "")
            if argv[:3] == ["gh", "pr", "view"]:
                return ('{"number": 7, "url": "https://example.invalid/pr/7"}', 0, "")
            raise AssertionError(argv)

        with patch.object(gh, "_run", lambda argv: runs.append(argv)), patch.object(gh, "_out", fake_out):
            self.assertEqual(gh.main(["create"]), 0)

        self.assertEqual(runs, [["git", "push", "origin", "HEAD:refs/heads/codex/test"]])

    def test_checks_return_pending_once_then_pass_when_waiting(self) -> None:
        gh = load_script()
        calls = 0

        def fake_rows(ref: str):
            nonlocal calls
            calls += 1
            if calls == 1:
                return [{"name": "audit", "bucket": "pending"}]
            return [{"name": "audit", "bucket": "pass"}]

        with patch.object(gh, "_check_rows", fake_rows), patch.object(gh.time, "sleep", lambda _: None):
            self.assertEqual(gh.wait_checks("7", interval=1, timeout=5, once=False), 0)

        self.assertEqual(calls, 2)

    def test_refuses_to_create_from_main(self) -> None:
        gh = load_script()

        def fake_out(argv: list[str], *, check: bool = True):
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return ("main", 0, "")
            raise AssertionError(argv)

        with patch.object(gh, "_out", fake_out):
            with self.assertRaises(SystemExit) as ctx:
                gh.main(["create", "--title", "Nope"])

        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
