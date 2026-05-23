import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchiveFixtureTest(unittest.TestCase):
    def test_archive_and_restore_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            archive = Path(tmp) / "archive"
            fixture = repo / "fixtures" / "sample" / "record.json"
            manifest = repo / "fixtures" / "fixtures_manifest.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text('{"hello":"archive"}\n', encoding="utf-8")
            archive_cmd = [
                str(ROOT / "scripts" / "archive_fixture.sh"),
                "fixtures/sample/record.json",
                "--archive-root",
                str(archive),
                "--manifest",
                "fixtures/fixtures_manifest.json",
                "--repo-root",
                str(repo),
            ]
            archived = subprocess.run(archive_cmd, check=True, text=True, capture_output=True)
            archived_payload = json.loads(archived.stdout)
            self.assertEqual(archived_payload["archived"], "fixtures/sample/record.json")
            self.assertTrue((archive / "fixtures" / "sample" / "record.json").is_file())
            stub = json.loads(fixture.read_text(encoding="utf-8"))
            self.assertEqual(stub["format"], "centaur-archived-fixture-stub-v1")
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(manifest_payload["format"], "centaur-fixtures-manifest-v1")
            self.assertEqual(manifest_payload["entries"][0]["path"], "fixtures/sample/record.json")
            restore_cmd = [
                str(ROOT / "scripts" / "archive_restore.sh"),
                "fixtures/sample/record.json",
                "--manifest",
                "fixtures/fixtures_manifest.json",
                "--repo-root",
                str(repo),
            ]
            restored = subprocess.run(restore_cmd, check=True, text=True, capture_output=True)
            restored_payload = json.loads(restored.stdout)
            self.assertEqual(restored_payload["restored"], "fixtures/sample/record.json")
            self.assertEqual(fixture.read_text(encoding="utf-8"), '{"hello":"archive"}\n')

    def test_restore_refuses_to_replace_non_stub_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            archive = Path(tmp) / "archive"
            fixture = repo / "fixtures" / "sample" / "record.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text('{"hello":"archive"}\n', encoding="utf-8")
            subprocess.run([
                str(ROOT / "scripts" / "archive_fixture.sh"),
                "fixtures/sample/record.json",
                "--archive-root",
                str(archive),
                "--repo-root",
                str(repo),
            ], check=True, text=True, capture_output=True)
            fixture.write_text('{"not":"a stub"}\n', encoding="utf-8")
            failed = subprocess.run([
                str(ROOT / "scripts" / "archive_restore.sh"),
                "fixtures/sample/record.json",
                "--repo-root",
                str(repo),
            ], text=True, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("not an archive stub", failed.stderr)


if __name__ == "__main__":
    unittest.main()
