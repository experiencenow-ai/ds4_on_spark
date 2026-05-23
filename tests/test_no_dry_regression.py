from __future__ import annotations

import ast
import hashlib
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIN_DUPLICATE_FUNCTION_LINES = 40


def duplicate_function_bodies(paths: list[Path], *, min_lines: int = MIN_DUPLICATE_FUNCTION_LINES) -> dict[str, list[dict[str, object]]]:
	duplicates: dict[str, list[dict[str, object]]] = defaultdict(list)
	for path in paths:
		tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
		for node in ast.walk(tree):
			if not isinstance(node, ast.FunctionDef):
				continue
			line_count = int((node.end_lineno or node.lineno) - node.lineno + 1)
			if line_count < min_lines:
				continue
			body = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
			digest = hashlib.md5(body.encode("utf-8")).hexdigest()
			duplicates[digest].append(
				{
					"path": str(_display_path(path)),
					"function": node.name,
					"line_count": line_count,
				}
			)
	return {digest: items for digest, items in duplicates.items() if len(items) > 1}


def _display_path(path: Path) -> Path:
	try:
		return path.relative_to(ROOT)
	except ValueError:
		return path


class NoDryRegressionTest(unittest.TestCase):
	def test_duplicate_detector_catches_large_same_body_functions(self) -> None:
		source = "\n".join(
			[
				"def alpha():",
				*[f"    value_{i} = {i}" for i in range(45)],
				"    return value_44",
				"",
				"def beta():",
				*[f"    value_{i} = {i}" for i in range(45)],
				"    return value_44",
				"",
			]
		)
		with tempfile.TemporaryDirectory() as tmpdir:
			path = Path(tmpdir) / "dup.py"
			path.write_text(source, encoding="utf-8")
			duplicates = duplicate_function_bodies([path], min_lines=40)
		self.assertEqual(len(duplicates), 1)

	def test_top_level_scripts_have_no_large_duplicate_function_bodies(self) -> None:
		paths = sorted((ROOT / "scripts").glob("*.py"))
		duplicates = duplicate_function_bodies(paths)
		self.assertEqual(duplicates, {})


if __name__ == "__main__":
	unittest.main()
