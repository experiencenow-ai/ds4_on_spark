import json
import os
import subprocess
import tempfile
import unittest


class BuildDs4MultisparkExpertManifestsTest(unittest.TestCase):
    def _write_owner_table(self, path: str) -> None:
        obj = {
            "schema": "ds4_expert_owner_table_v1",
            "strategy": "affinity",
            "num_layers": 2,
            "experts": 5,
            "sparks": 3,
            "logical_lanes": 5,
            "table_balance": {},
            "same_spark": {},
            "owner_table": [
                [0, 1, 2, 0, 1],
                [2, 2, 1, 1, 0],
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj))

    def test_cli_writes_partitioned_rank_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            owner = os.path.join(td, "owner.json")
            out_dir = os.path.join(td, "manifests")
            self._write_owner_table(owner)
            subprocess.run(
                [
                    "python3",
                    "scripts/build_ds4_multispark_expert_manifests.py",
                    "--owner-table-json",
                    owner,
                    "--out-dir",
                    out_dir,
                ],
                check=True,
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with open(os.path.join(out_dir, "manifest.json"), "r", encoding="utf-8") as f:
                index = json.loads(f.read())
            self.assertEqual(index["schema"], "ds4_multispark_owned_expert_manifest_index_v1")
            self.assertEqual(index["world_size"], 3)
            self.assertEqual(len(index["ranks"]), 3)
            with open(os.path.join(out_dir, "rank-000.json"), "r", encoding="utf-8") as f:
                rank0 = json.loads(f.read())
            self.assertEqual(rank0["schema"], "ds4_multispark_owned_expert_manifest_v1")
            self.assertEqual(rank0["owned_experts_by_layer"], [[0, 3], [4]])
            self.assertEqual(rank0["total_owned_layer_experts"], 3)
            all_by_layer = [set(), set()]
            for rank in range(3):
                with open(os.path.join(out_dir, f"rank-{rank:03d}.json"), "r", encoding="utf-8") as f:
                    manifest = json.loads(f.read())
                for layer, experts in enumerate(manifest["owned_experts_by_layer"]):
                    all_by_layer[layer].update(experts)
            self.assertEqual(all_by_layer, [{0, 1, 2, 3, 4}, {0, 1, 2, 3, 4}])

    def test_cli_rejects_out_of_range_owner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            owner = os.path.join(td, "owner.json")
            out_dir = os.path.join(td, "manifests")
            self._write_owner_table(owner)
            with open(owner, "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
            obj["owner_table"][0][0] = 9
            with open(owner, "w", encoding="utf-8") as f:
                f.write(json.dumps(obj))
            p = subprocess.run(
                [
                    "python3",
                    "scripts/build_ds4_multispark_expert_manifests.py",
                    "--owner-table-json",
                    owner,
                    "--out-dir",
                    out_dir,
                ],
                check=False,
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
