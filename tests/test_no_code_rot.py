"""CI gate that fails when code rot is present.

Wraps scripts/audit_code_rot.py. Run via pytest.

Per ct direction 2026-05-23 — every line of code must be justified. This test
makes that a structural rule, not a hope.
"""

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_duplicate_functions_or_forbidden_docs() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_code_rot.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    assert result.returncode == 0, (
        "Code rot present: see audit output above. "
        "Fix DRY violations and remove forbidden probe docs before this PR can land."
    )
