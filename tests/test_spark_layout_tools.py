import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts" / "ds4_layout_inventory.py"
CLEANUP = ROOT / "scripts" / "ds4_layout_cleanup.py"
MANIFEST = ROOT / "scripts" / "ds4_layout_manifest.py"
AUDIT = ROOT / "scripts" / "ds4_layout_audit.py"
APPLY = ROOT / "scripts" / "ds4_layout_apply.sh"
STAGE = ROOT / "scripts" / "ds4_layout_stage.py"


def make_official_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "remote",
            "add",
            "origin",
            "https://github.com/sparkpipe/sparkpipe.git",
        ],
        check=True,
    )


def run_json(command):
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_inventory_reports_canonical_and_legacy_roots(tmp_path):
    node_root = tmp_path / "spark0"
    (node_root / "sparkdata").mkdir(parents=True)
    (node_root / "srcdata").mkdir()
    (node_root / "extnvme").mkdir()
    (node_root / "kvcache").mkdir()
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
    (node_root / "kvcache").mkdir()
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


def test_manifest_records_size_and_reason(tmp_path):
    node_root = tmp_path / "spark0"
    node_root.mkdir()
    old_log = node_root / "old.log"
    old_log.write_text("old\n", encoding="utf-8")
    result = run_json(
        [
            "python3",
            str(MANIFEST),
            "--node-root",
            str(node_root),
            "--path",
            str(old_log),
            "--reason",
            "test cleanup",
        ]
    )
    entry = result["entries"][0]
    assert entry["reason"] == "test cleanup"
    assert entry["files"] == 1
    assert entry["bytes_on_disk"] == old_log.stat().st_blocks * 512


def test_manifest_rejects_symlinks(tmp_path):
    node_root = tmp_path / "spark0"
    node_root.mkdir()
    target = node_root / "real.log"
    target.write_text("old\n", encoding="utf-8")
    link = node_root / "link.log"
    link.symlink_to(target)
    result = subprocess.run(
        [
            "python3",
            str(MANIFEST),
            "--node-root",
            str(node_root),
            "--path",
            str(link),
            "--reason",
            "test cleanup",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "symlinks are not cleanup targets" in result.stderr


def test_apply_creates_real_data_roots_and_rejects_symlinks(tmp_path):
    node_root = tmp_path / "spark0"
    node_root.mkdir()
    make_official_repo(node_root / "sparkpipe")
    result = subprocess.run(
        ["bash", str(APPLY), "--apply", "--node-root", str(node_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "kvcache=" in result.stdout
    for name in ("sparkpipe", "sparkdata", "srcdata", "extnvme", "kvcache"):
        assert (node_root / name).is_dir()
        assert not (node_root / name).is_symlink()
    (node_root / "kvcache").rmdir()
    (node_root / "kvcache").symlink_to(node_root / "sparkdata")
    refused = subprocess.run(
        ["bash", str(APPLY), "--apply", "--node-root", str(node_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 1
    assert "refusing symlink canonical root" in refused.stderr


def test_audit_requires_official_repo_and_topology_format_cache_names(tmp_path):
    node_root = tmp_path / "spark0"
    node_root.mkdir()
    make_official_repo(node_root / "sparkpipe")
    for name in ("sparkdata", "srcdata", "extnvme", "kvcache"):
        (node_root / name).mkdir()
    (node_root / "kvcache" / "dsv4_flash" / "pp13.bf16").mkdir(parents=True)
    report = run_json(
        ["python3", str(AUDIT), "--node-root", str(node_root), "--json"]
    )
    assert report["ok"] is True
    (node_root / "kvcache" / "dsv4_flash" / "fp8-pp13").mkdir()
    refused = subprocess.run(
        ["python3", str(AUDIT), "--node-root", str(node_root), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 1
    assert "dsv4_flash/fp8-pp13" in refused.stdout


def test_stage_creates_hashed_hardlink_dataset_and_rejects_symlinks(tmp_path):
    node_root = tmp_path / "spark0"
    source = tmp_path / "source"
    source.mkdir()
    node_root.mkdir()
    (node_root / "srcdata").mkdir()
    payload = source / "model-00001.safetensors"
    payload.write_bytes(b"rank-local-layer")
    staged = run_json(
        [
            "python3", str(STAGE), "--node-root", str(node_root),
            "--root", "srcdata", "--dataset", "dsv4_flash.fp8.pp13",
            "--source", str(source), "--apply",
        ]
    )
    destination = node_root / "srcdata" / "dsv4_flash.fp8.pp13"
    assert staged["ok"] is True
    assert (destination / payload.name).stat().st_ino == payload.stat().st_ino
    verified = run_json(
        [
            "python3", str(STAGE), "--node-root", str(node_root),
            "--root", "srcdata", "--dataset", "dsv4_flash.fp8.pp13",
            "--verify",
        ]
    )
    assert verified == staged
    linked_source = tmp_path / "linked-source"
    linked_source.symlink_to(source, target_is_directory=True)
    refused = subprocess.run(
        [
            "python3", str(STAGE), "--node-root", str(node_root),
            "--root", "srcdata", "--dataset", "dsv4_pro.fp8.pp13",
            "--source", str(linked_source), "--apply",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 1
    assert "symlinked source" in refused.stderr
