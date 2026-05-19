import tempfile
import unittest
from pathlib import Path

from scripts import patch_ray_ds4_spark_startup as patcher


SCRIPTS_PY = """def start():
    has_ray_client = get_ray_client_dependency_error() is None
    if has_ray_client and ray_client_server_port is None:
        ray_client_server_port = 10001
    ray_params = RayParams()
"""


NODE_PY = """class Node:
    def start_api_server(self):
        stdout_log_fname, stderr_log_fname = self.get_log_file_names(
            "dashboard", unique=True, create_out=True, create_err=True
        )
        self._webui_url, process_info = ray._private.services.start_api_server()
"""


class PatchRayDs4SparkStartupTest(unittest.TestCase):
    def test_text_patches_are_idempotent(self) -> None:
        scripts = patcher.patch_scripts_py(SCRIPTS_PY)
        node = patcher.patch_node_py(NODE_PY)
        self.assertEqual(scripts, patcher.patch_scripts_py(scripts))
        self.assertEqual(node, patcher.patch_node_py(node))
        self.assertIn("ray_client_server_port = None", scripts)
        self.assertIn("return", node)

    def test_apply_patch_writes_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "ray" / "scripts").mkdir(parents=True)
            (site / "ray" / "_private").mkdir(parents=True)
            scripts = site / "ray" / "scripts" / "scripts.py"
            node = site / "ray" / "_private" / "node.py"
            scripts.write_text(SCRIPTS_PY, encoding="utf-8")
            node.write_text(NODE_PY, encoding="utf-8")
            result = patcher.apply_patch(site, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertTrue((scripts.with_name(scripts.name + ".bak")).exists())
            self.assertTrue((node.with_name(node.name + ".bak")).exists())
            result2 = patcher.apply_patch(site, backup_suffix=".bak", write=True)
            self.assertFalse(result2["changed"])


if __name__ == "__main__":
    unittest.main()
