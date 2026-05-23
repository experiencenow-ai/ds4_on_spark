import json
import tempfile
import unittest
from pathlib import Path

from centaur.centaur_archive_manager import (
    ArchiveLayout,
    CentaurArchiveManager,
)


class CentaurArchiveManagerTest(unittest.TestCase):
    def test_archive_manager_stays_compact(self) -> None:
        source = Path(__file__).resolve().parents[1] / "centaur" / "centaur_archive_manager.py"
        code_lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertLessEqual(len(code_lines), 260)

    def test_kv_blob_round_trip_and_stage_for_vram(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CentaurArchiveManager(Path(tmp), ArchiveLayout(chunk_size=11))
            payload = b"abc123" + bytes(range(37)) + b"tail"
            blob_id = manager.put_kv_blob("prefix/system", payload, related_group="longmem.alpha")
            self.assertEqual(manager.get_kv_blob(blob_id), payload)
            staged = manager.stage_for_vram([blob_id])
            staged_manifest = json.loads((staged / "stage_manifest.json").read_text(encoding="utf-8"))
            staged_file = staged / "kv_blobs" / f"{blob_id}.kv"
            self.assertEqual(staged_manifest["format"], "centaur-vram-stage-v1")
            self.assertEqual(staged_manifest["staged"][0]["blob_id"], blob_id)
            self.assertEqual(staged_file.read_bytes(), payload)

    def test_related_group_fetch_preserves_creation_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CentaurArchiveManager(Path(tmp), ArchiveLayout(chunk_size=7))
            first = manager.put_kv_blob("m1", b"first-memory", related_group="domain.same")
            second = manager.put_kv_blob("m2", b"second-memory", related_group="domain.same")
            self.assertNotEqual(first, second)
            self.assertEqual(manager.get_kv_blob_group("domain.same"), [b"first-memory", b"second-memory"])

    def test_duplicate_payload_gets_unique_blob_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CentaurArchiveManager(Path(tmp), ArchiveLayout(chunk_size=7))
            first = manager.put_kv_blob("same", b"same-payload", related_group="domain.same")
            second = manager.put_kv_blob("same", b"same-payload", related_group="domain.same")
            self.assertNotEqual(first, second)
            self.assertEqual(manager.get_kv_blob(first), b"same-payload")
            self.assertEqual(manager.get_kv_blob(second), b"same-payload")

    def test_parity_rebuild_recovers_deleted_simulated_drive_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = CentaurArchiveManager(Path(tmp), ArchiveLayout(chunk_size=13))
            payload = bytes(range(89))
            blob_id = manager.put_kv_blob("kv/rebuild", payload, related_group="longmem.beta")
            failed_path = manager.drive_part_path(blob_id, 3)
            self.assertTrue(failed_path.exists())
            failed_path.unlink()
            before = manager.parity_check()
            self.assertFalse(before["ok"])
            self.assertEqual(before["missing_drive_files"][blob_id], [3])
            rebuild = manager.parity_rebuild(3)
            self.assertTrue(rebuild["ok"], rebuild)
            self.assertIn(blob_id, rebuild["rebuilt_blobs"])
            self.assertTrue(failed_path.exists())
            self.assertEqual(manager.get_kv_blob(blob_id), payload)
            self.assertTrue(manager.parity_check()["ok"])

    def test_layout_is_parametric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            layout = ArchiveLayout(data_drive_count=4, staging_drive_count=1, chunk_size=5)
            manager = CentaurArchiveManager(Path(tmp), layout)
            payload = b"parametric-layout-check"
            blob_id = manager.put_kv_blob("kv/layout", payload, related_group="layout")
            self.assertEqual(manager.get_kv_blob(blob_id), payload)
            self.assertEqual(len(json.loads((Path(tmp) / "archive_manifest.json").read_text(encoding="utf-8"))["kv_blobs"][blob_id]["part_paths"]), 4)

    def test_put_and_get_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "archive"
            bundle = Path(tmp) / "bundle"
            bundle.mkdir()
            (bundle / "run.json").write_text('{"ok":true}\n', encoding="utf-8")
            manager = CentaurArchiveManager(root, ArchiveLayout(chunk_size=11))
            bundle_id = manager.put_bundle(bundle)
            archived = manager.get_bundle(bundle_id)
            self.assertTrue((archived / "run.json").is_file())
            self.assertEqual((archived / "run.json").read_text(encoding="utf-8"), '{"ok":true}\n')


if __name__ == "__main__":
    unittest.main()
