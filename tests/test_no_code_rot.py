"""CI gate that fails when code rot is present.

Wraps scripts/audit_code_rot.py. Run via pytest.

Per ct direction 2026-05-23 — every line of code must be justified. This test
makes that a structural rule, not a hope.
"""

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


class CodeRotGateTest(unittest.TestCase):
    def test_no_duplicate_functions_or_forbidden_docs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "audit_code_rot.py")],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        self.assertEqual(
            result.returncode,
            0,
            "Code rot present: see audit output above. "
            "Fix DRY violations and remove forbidden probe docs before this PR can land.",
        )

    def test_centaur_complexity_gate(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "score_repo_complexity.py"), "gate"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        self.assertEqual(
            result.returncode,
            0,
            "Centaur complexity regression present: see gate output above. "
            "Reduce complexity or intentionally re-record the baseline with review.",
        )


if __name__ == "__main__":
    unittest.main()
