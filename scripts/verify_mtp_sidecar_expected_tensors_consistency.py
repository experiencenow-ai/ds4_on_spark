#!/usr/bin/env python3
import argparse
import ast
import re
import sys
from pathlib import Path


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _read_text(path: Path) -> str:
	try:
		return path.read_text(encoding="utf-8")
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	return ""


def _extract_python_expected_names(py_path: Path) -> list[str]:
	src = _read_text(py_path)
	try:
		tree = ast.parse(src, filename=str(py_path))
	except SyntaxError as e:
		_die(f"failed to parse python AST for {py_path}: {e}")

	found: list[list[str]] = []
	for node in ast.walk(tree):
		if not isinstance(node, ast.Assign):
			continue
		for target in node.targets:
			if isinstance(target, ast.Name) and target.id == "expected_names":
				try:
					val = ast.literal_eval(node.value)
				except Exception as e:
					_die(f"expected_names in {py_path} is not a literal list: {e}")
				if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
					_die(f"expected_names in {py_path} is not a list[str]")
				found.append([str(x) for x in val])

	if not found:
		_die(f"did not find expected_names assignment in {py_path}")
	if len(found) > 1:
		_die(f"found multiple expected_names assignments in {py_path}")
	return found[0]


def _extract_cpp_expected_names_from_patch(patch_path: Path) -> list[str]:
	patch_text = _read_text(patch_path)

	needle = (
		"diff --git a/examples/ds4-mtp-sidecar-probe/ds4-mtp-sidecar-probe.cpp "
		"b/examples/ds4-mtp-sidecar-probe/ds4-mtp-sidecar-probe.cpp"
	)
	pos = patch_text.find(needle)
	if pos < 0:
		_die(f"missing ds4-mtp-sidecar-probe.cpp diff header in {patch_path}")

	after = patch_text[pos:]
	lines = after.splitlines()

	hunk_i = -1
	for i, line in enumerate(lines):
		if line.startswith("@@ "):
			hunk_i = i
			break
	if hunk_i < 0:
		_die(f"missing hunk header for ds4-mtp-sidecar-probe.cpp in {patch_path}")

	added: list[str] = []
	for line in lines[hunk_i + 1 :]:
		if line.startswith("diff --git "):
			break
		if line.startswith("+++ "):
			continue
		if line.startswith("+"):
			added.append(line[1:])

	cpp = "\n".join(added) + "\n"

	k_start = cpp.find("static const std::vector<std::string> k = {")
	if k_start < 0:
		_die("unable to locate expected tensor vector initializer in patch cpp hunk")
	k_end = cpp.find("};", k_start)
	if k_end < 0:
		_die("unable to locate end of expected tensor vector initializer in patch cpp hunk")

	block = cpp[k_start:k_end]
	names = re.findall(r'"(mtp\.0\.[^"]+)"', block)
	if not names:
		_die("no mtp.0.* tensor names found in patch cpp expected list")

	# Preserve order but drop duplicates if any show up due to formatting glitches.
	out: list[str] = []
	seen: set[str] = set()
	for n in names:
		if n in seen:
			continue
		seen.add(n)
		out.append(n)
	return out


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--python-probe", default="scripts/model_contract_probe_mtp_sidecar.py")
	ap.add_argument(
		"--patch",
		default="docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-sidecar-probe.patch",
	)
	args = ap.parse_args()

	py_path = Path(args.python_probe)
	patch_path = Path(args.patch)

	py_names = _extract_python_expected_names(py_path)
	cpp_names = _extract_cpp_expected_names_from_patch(patch_path)

	py_set = set(py_names)
	cpp_set = set(cpp_names)

	if len(py_set) != len(py_names):
		_die(f"{py_path} expected_names contains duplicates (len={len(py_names)} uniq={len(py_set)})")
	if len(cpp_set) != len(cpp_names):
		_die(f"{patch_path} expected tensor list contains duplicates (len={len(cpp_names)} uniq={len(cpp_set)})")

	missing_in_cpp = sorted(py_set - cpp_set)
	extra_in_cpp = sorted(cpp_set - py_set)

	if missing_in_cpp:
		_die(f"patch is missing {len(missing_in_cpp)} tensor(s) present in python probe (e.g. {missing_in_cpp[0]!r})")
	if extra_in_cpp:
		_die(f"patch has {len(extra_in_cpp)} extra tensor(s) not present in python probe (e.g. {extra_in_cpp[0]!r})")

	if len(py_names) != 32:
		_die(f"{py_path} expected_names len is {len(py_names)}, expected 32")
	if len(cpp_names) != 32:
		_die(f"{patch_path} expected tensor list len is {len(cpp_names)}, expected 32")

	print("ok=true")


if __name__ == "__main__":
	main()

