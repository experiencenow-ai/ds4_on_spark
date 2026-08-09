import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts" / "ds4_layout_inventory.py"
CLEANUP = ROOT / "scripts" / "ds4_layout_cleanup.py"


def run_json(command):
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_inventory_reports_canonical_and_legacy_roots(tmp_path):
    node_root = tmp_path / "spark0"
    (node_root / "sparkdata").mkdir(parents=True)
    (node_root / "srcdata").mkdir()
    (node_root / "extnvme").mkdir()
    report = run_json(
        ["python3", str(INVENTORY), "--node-root", str(node_root), "--json"]
    )
    assert report["canonical"]["sparkdata"]["kind"] == "directory"
    assert report["canonical"]["sparkdata"]["mount"]["is_mount"] is False
    assert report["legacy"]["models"]["kind"] == "missing"


def test_cleanup_requires_exact_snapshot_and_protects_canonical_roots(tmp_path):
    node_root = tmp_path / "spark0"
    (node_root / "sparkdata").mkdir(parents=True)
    (node_root / "srcdata").mkdir()
    (node_root / "extnvme").mkdir()
    old_log = node_root / "old.log"
    old_log.write_text("old\n", encoding="utf-8")
    manifest = tmp_path / "cleanup.json"
    manifest.write_text(
        json.dumps(
            {
                "node": "spark0",
                "entries": [
                    {
                        "path": str(old_log),
                        "action": "delete",
                        "bytes_on_disk": old_log.stat().st_blocks * 512,
                        "files": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "python3",
            str(CLEANUP),
            "--node-root",
            str(node_root),
            "--manifest",
            str(manifest),
            "--apply",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "receipt=" in result.stdout
    assert not old_log.exists()

    protected = tmp_path / "protected.json"
    protected.write_text(
        json.dumps(
            {
                "node": "spark0",
                "entries": [
                    {
                        "path": str(node_root / "sparkdata"),
                        "action": "delete",
                        "bytes_on_disk": 0,
                        "files": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    refused = subprocess.run(
        [
            "python3",
            str(CLEANUP),
            "--node-root",
            str(node_root),
            "--manifest",
            str(protected),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 1
    assert "canonical root is protected" in refused.stdout
