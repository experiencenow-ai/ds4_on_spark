from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "centaur_smart_skeleton_submit.py"


def load_script():
    spec = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[SCRIPT.stem] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def sidecar(category: str, source_file: str, index: int) -> dict[str, object]:
    return {
        "format": "centaur-function-sidecar-v1",
        "category": category,
        "sidecar_id": f"fside-{category}-{index}",
        "source_file": source_file,
        "source_sha256": f"sha256:{category}-{source_file}-{index}",
        "line_start": index * 10,
        "line_end": (index * 10) + 5,
        "signature": f"int32_t fn_{index}(void)",
        "function_name": f"fn_{index}",
        "annotation": {
            "sidecar_id": f"fside-{category}-{index}",
            "function_name": f"fn_{index}",
            "summary": f"summary {index}",
            "protocol_role": f"role {index}",
            "state_effects": ["state"],
            "invariants": ["invariant"],
            "liveness_risks": ["none"],
            "edit_hazards": ["hazard"],
            "lookup_tags": [category, source_file, f"fn_{index}"],
            "confidence": 0.9,
        },
        "worker": {"status": "success"},
    }


class CentaurSmartSkeletonSubmitTests(unittest.TestCase):
    def test_plan_splits_large_files_and_stages_reductions(self) -> None:
        submit = load_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parsed = root / "parsed.jsonl"
            report = root / "report.json"
            out = root / "out"
            rows = [
                sidecar("dataflow_core", "df/src/a.c", 1),
                sidecar("dataflow_core", "df/src/a.c", 2),
                sidecar("ledger_ufc", "ledger/src/b.c", 1),
                sidecar("ledger_ufc", "ledger/src/b.c", 2),
                sidecar("ledger_ufc", "ledger/src/b.c", 3),
            ]
            write_jsonl(parsed, rows)
            report.write_text(json.dumps({"ready": False, "totals": {"remaining": 1}}), encoding="utf-8")

            manifest = submit.build_submission_plan(parsed, report, out, max_sidecars_per_file_task=2)

            self.assertFalse(manifest["report_ready"])
            self.assertEqual(manifest["success_sidecar_count"], 5)
            self.assertEqual(manifest["source_file_count"], 2)
            self.assertEqual(manifest["task_counts"]["file_skeleton"], 2)
            self.assertEqual(manifest["task_counts"]["file_skeleton_slice"], 2)
            self.assertEqual(manifest["task_counts"]["module_skeleton"], 2)
            self.assertEqual(manifest["task_counts"]["repo_capsule"], 1)
            self.assertEqual(manifest["waves"]["1"]["task_count"], 3)
            self.assertEqual(manifest["waves"]["2"]["task_count"], 1)
            self.assertEqual(manifest["waves"]["3"]["task_count"], 2)
            self.assertEqual(manifest["waves"]["4"]["task_count"], 1)
            self.assertTrue((out / "manifest.json").is_file())
            self.assertTrue((out / "launch_commands.sh").is_file())

    def test_launch_refuses_incomplete_manifest_by_default(self) -> None:
        submit = load_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "format": "centaur-smart-skeleton-quartet-plan-v1",
                "report_ready": False,
                "allow_incomplete": False,
                "out_root": str(root / "out"),
                "quartets": [],
                "waves": {"1": {"task_paths": {}}},
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            args = type("Args", (), {"manifest": str(manifest_path), "wave": "1", "allow_incomplete": False})()

            self.assertEqual(submit.launch(args), 2)


if __name__ == "__main__":
    unittest.main()
