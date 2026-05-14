import json
import os
import subprocess
import tempfile
import unittest
from array import array


def _write_i32_dump(path: str, rows: list[list[int]]) -> None:
    data = array("i")
    for row in rows:
        for v in row:
            data.append(int(v))
    with open(path, "wb") as f:
        f.write(data.tobytes())


class BuildDs4ExpertOwnerTableTest(unittest.TestCase):
    def test_cli_writes_json_and_c_header(self) -> None:
        layers = [
            [[0, 1], [0, 1], [2, 3], [2, 3]],
            [[4, 5], [4, 5], [6, 7], [6, 7]],
        ]
        with tempfile.TemporaryDirectory() as td:
            _write_i32_dump(os.path.join(td, "ffn_moe_topk-0_pos0.i32"), layers[0])
            _write_i32_dump(os.path.join(td, "ffn_moe_topk-1_pos0.i32"), layers[1])
            out_json = os.path.join(td, "owner.json")
            out_h = os.path.join(td, "owner.h")
            subprocess.run(
                [
                    "python3",
                    "scripts/build_ds4_expert_owner_table.py",
                    "--dump-dir",
                    td,
                    "--pos",
                    "0",
                    "--topk",
                    "2",
                    "--experts",
                    "8",
                    "--logical-lanes",
                    "8",
                    "--sparks",
                    "2",
                    "--json-out",
                    out_json,
                    "--c-header-out",
                    out_h,
                    "--c-symbol",
                    "test_owner",
                ],
                check=True,
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with open(out_json, "r", encoding="utf-8") as f:
                obj = json.loads(f.read())
            self.assertEqual(obj["schema"], "ds4_expert_owner_table_v1")
            self.assertEqual(obj["owner_table"][1][4:8], [0, 0, 0, 0])
            with open(out_h, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("#pragma once", text)
            self.assertIn("test_owner[2][8]", text)


if __name__ == "__main__":
    unittest.main()
