import unittest

from scripts._lib.diamond_local_model import DiamondLocalModelClient
from scripts._lib.diamond_local_model import DiamondLocalModelError


class DiamondLocalModelTest(unittest.TestCase):
    def test_endpoint_is_required_without_fallback(self) -> None:
        client = DiamondLocalModelClient("")
        with self.assertRaisesRegex(DiamondLocalModelError, "no fallback provider"):
            client.propose_refactor("def f():\n    return 1\n", "inline_path")


if __name__ == "__main__":
    unittest.main()
