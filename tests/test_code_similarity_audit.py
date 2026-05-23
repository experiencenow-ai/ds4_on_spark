import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import audit_code_similarity as sim


class CodeSimilarityAuditTest(unittest.TestCase):
    def test_pair_keys_ignore_line_number_drift(self) -> None:
        pairs = [{"left": "scripts/one.py::main@10", "right": "scripts/two.py::main@50"}]
        self.assertEqual(
            sim.pair_keys(pairs),
            {"scripts/one.py::main@* <=> scripts/two.py::main@*"},
        )

    def test_synthetic_near_duplicate_uses_centaur_similarity(self) -> None:
        centaur_root = sim.resolve_centaur_root(Path.cwd(), None)
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "left.py").write_text(
                textwrap.dedent(
                    """
                    def calculate_total(items):
                        total = 0
                        for item in items:
                            total += item.value
                        if total < 0:
                            total = 0
                        return total
                    """
                ),
                encoding="utf-8",
            )
            (scripts / "right.py").write_text(
                textwrap.dedent(
                    """
                    def compute_sum(rows):
                        answer = 0
                        for row in rows:
                            answer += row.value
                        if answer < 0:
                            answer = 0
                        return answer
                    """
                ),
                encoding="utf-8",
            )
            result = sim.run_similarity_audit(root, centaur_root, 0.85, 1, 5, 20)
        self.assertEqual(result["centaur_import"], "from centaur import dry_similarity as centaur_dry_similarity")
        self.assertGreaterEqual(result["pair_count"], 1)
        self.assertGreaterEqual(float(result["pairs"][0]["score"]), 0.85)


if __name__ == "__main__":
    unittest.main()
