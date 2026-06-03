from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_pipeline_runtime_audit.py"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_script_module("ds4_pipeline_runtime_audit", SCRIPT)


class PipelineRuntimeAuditTests(unittest.TestCase):
    def test_pipeline_runtime_audit_passes_checked_in_profiles(self) -> None:
        self.assertEqual(audit.main(), 0)


if __name__ == "__main__":
    unittest.main()
