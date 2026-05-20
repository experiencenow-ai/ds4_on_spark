import unittest
from pathlib import Path

from scripts import prepare_ds4_vllm_python_headers as prep


class PrepareDs4VllmPythonHeadersTest(unittest.TestCase):
    def test_include_path_orders_generic_parent_before_versioned_dirs(self) -> None:
        result = prep.include_path(
            Path("/tmp/ds4-python312-dev"),
            python_version="3.12",
            arch_triplet="aarch64-linux-gnu",
        )
        self.assertEqual(
            result,
            "/tmp/ds4-python312-dev/usr/include:"
            "/tmp/ds4-python312-dev/usr/include/python3.12:"
            "/tmp/ds4-python312-dev/usr/include/aarch64-linux-gnu/python3.12",
        )


if __name__ == "__main__":
    unittest.main()
