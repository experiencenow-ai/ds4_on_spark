from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ds4_archive import ArchiveVolume, XorArchiveStore


class XorArchiveStoreTests(unittest.TestCase):
    def test_put_get_uses_equal_offsets_and_rotating_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, extent_payload_bytes=15)
            store.init()
            first = store.put_bytes("models", "a", b"abcdefghijklmno")
            second = store.put_bytes("models", "b", b"pqrstuvwxyz1234")

            self.assertEqual(store.get_bytes("models", "a"), b"abcdefghijklmno")
            self.assertEqual(store.get_bytes("models", "b"), b"pqrstuvwxyz1234")
            self.assertEqual(first["extents"][0]["offset"], 0)
            self.assertEqual(first["extents"][0]["shard_len"], 3)
            self.assertEqual(second["extents"][0]["offset"], 3)
            self.assertEqual(second["extents"][0]["shard_len"], 3)
            self.assertEqual(first["extents"][0]["parity_volume_id"], "v0")
            self.assertEqual(second["extents"][0]["parity_volume_id"], "v1")

    def test_read_recovers_one_corrupt_data_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, extent_payload_bytes=20)
            store.init()
            manifest = store.put_bytes("models", "recover", b"0123456789abcdefghij")
            data_shard = _first_data_shard(manifest)
            _corrupt_shard(store, manifest, data_shard)

            status = store.verify("models", "recover")
            self.assertEqual(status["state"], "degraded")
            self.assertEqual(store.get_bytes("models", "recover"), b"0123456789abcdefghij")

    def test_repair_rewrites_bad_shard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, extent_payload_bytes=20)
            store.init()
            manifest = store.put_bytes("models", "repair", b"abcdefghij0123456789")
            data_shard = _first_data_shard(manifest)
            _corrupt_shard(store, manifest, data_shard)

            repair = store.repair("models", "repair")
            self.assertEqual(repair["verify"]["state"], "healthy")
            self.assertEqual(store.verify("models", "repair")["state"], "healthy")
            self.assertEqual(store.get_bytes("models", "repair"), b"abcdefghij0123456789")

    def test_catalog_rebuilds_from_replicated_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, extent_payload_bytes=10)
            store.init()
            store.put_bytes("datasets", "sample", b"hello archive")
            store.catalog_path.unlink()

            rebuilt = store.rebuild_catalog()
            self.assertIn("datasets/sample", rebuilt["objects"])
            self.assertEqual(store.get_bytes("datasets", "sample"), b"hello archive")

    def test_stage_writes_restored_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, extent_payload_bytes=10)
            store.init()
            store.put_bytes("datasets", "stage", b"stage me")
            out = Path(tmp) / "out.bin"

            store.stage("datasets", "stage", out)

            self.assertEqual(out.read_bytes(), b"stage me")

    def test_four_volume_store_uses_3p1_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, volume_count=4, extent_payload_bytes=12)
            catalog = store.init()
            manifest = store.put_bytes("datasets", "four", b"abcdefghijkl")

            self.assertEqual(catalog["storage_class"]["name"], "archive_3p1_xor")
            self.assertEqual(manifest["storage_class"], "archive_3p1_xor")
            self.assertEqual(len(manifest["extents"][0]["shards"]), 4)
            self.assertEqual(manifest["extents"][0]["shard_len"], 4)
            self.assertEqual(manifest["extents"][0]["parity_volume_id"], "v0")
            self.assertEqual(store.get_bytes("datasets", "four"), b"abcdefghijkl")

    def test_volume_order_can_change_after_disk_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp, extent_payload_bytes=10)
            store.init()
            store.put_bytes("datasets", "moved", b"disk order should not matter")
            root = Path(tmp)
            moved = XorArchiveStore(
                root / "meta",
                [ArchiveVolume(f"v{index}", root / f"vol{index}") for index in reversed(range(6))],
                extent_payload_bytes=10,
                fsync=False,
            )

            self.assertEqual(moved.get_bytes("datasets", "moved"), b"disk order should not matter")


def _store(tmp: str, *, extent_payload_bytes: int, volume_count: int = 6) -> XorArchiveStore:
    root = Path(tmp)
    volumes = [ArchiveVolume(f"v{index}", root / f"vol{index}") for index in range(volume_count)]
    return XorArchiveStore(root / "meta", volumes, extent_payload_bytes=extent_payload_bytes, fsync=False)


def _first_data_shard(manifest: dict) -> dict:
    for shard in manifest["extents"][0]["shards"]:
        if shard["role"] == "data0":
            return shard
    raise AssertionError("data0 shard not found")


def _corrupt_shard(store: XorArchiveStore, manifest: dict, shard: dict) -> None:
    extent = manifest["extents"][0]
    path = store._data_path(shard["volume_id"])  # intentional white-box corruption helper
    with path.open("r+b") as handle:
        handle.seek(extent["offset"])
        handle.write(b"\xff" * extent["shard_len"])


if __name__ == "__main__":
    unittest.main()
