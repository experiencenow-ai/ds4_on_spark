#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _read_text(path: Path) -> str:
	try:
		return path.read_text(encoding="utf-8", errors="replace")
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	return ""


def _extract_ds4_expected_names(ds4_c_path: Path) -> list[str]:
	src = _read_text(ds4_c_path)

	m = re.search(r"\bmtp_weights_bind\s*\([^)]*\)\s*\{", src)
	if m is None:
		_die(f"unable to locate mtp_weights_bind(...) in {ds4_c_path}")

	brace = src.find("{", m.end() - 1)
	if brace < 0:
		_die(f"unable to locate opening brace for mtp_weights_bind in {ds4_c_path}")

	level = 0
	end = -1
	for i in range(brace, len(src)):
		c = src[i]
		if c == "{":
			level += 1
		elif c == "}":
			level -= 1
			if level == 0:
				end = i + 1
				break

	if end < 0:
		_die(f"unterminated mtp_weights_bind body in {ds4_c_path}")

	body = src[brace:end]
	raw = re.findall(r'"(mtp\.0\.[^"]+)"', body)
	if not raw:
		_die(f"no mtp.0.* tensor names found in mtp_weights_bind body in {ds4_c_path}")

	out: list[str] = []
	seen: set[str] = set()
	for n in raw:
		if n in seen:
			continue
		seen.add(n)
		out.append(n)
	return out


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


def main() -> None:
	ap = argparse.ArgumentParser(
		description="Verify mtp.0.* tensor-name contract against pinned antirez/ds4 mtp_weights_bind() list."
	)
	ap.add_argument("--ds4-c", default="upstreams/ds4/ds4.c", help="Path to upstreams/ds4/ds4.c")
	ap.add_argument("--python-probe", default="scripts/model_contract_probe_mtp_sidecar.py")
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON result.")
	args = ap.parse_args()

	ds4_c_path = Path(args.ds4_c)
	py_path = Path(args.python_probe)

	ds4_names = _extract_ds4_expected_names(ds4_c_path)
	py_names = _extract_python_expected_names(py_path)

	ds4_set = set(ds4_names)
	py_set = set(py_names)

	missing_in_python = [n for n in ds4_names if n not in py_set]
	extra_in_python = [n for n in py_names if n not in ds4_set]
	order_mismatches: list[dict[str, str]] = []

	if len(ds4_set) != len(ds4_names):
		_die(f"{ds4_c_path} contains duplicate mtp.0.* tensor names in mtp_weights_bind()")
	if len(py_set) != len(py_names):
		_die(f"{py_path} expected_names contains duplicates (len={len(py_names)} uniq={len(py_set)})")

	if ds4_set == py_set:
		ds4_pos = {n: i for i, n in enumerate(ds4_names)}
		for i, n in enumerate(py_names):
			if ds4_pos.get(n, i) != i:
				order_mismatches.append({"name": n, "python_index": str(i), "ds4_index": str(ds4_pos.get(n, -1))})

	ok = (not missing_in_python) and (not extra_in_python)

	if args.json:
		out = {
			"ok": bool(ok),
			"ds4_c": str(ds4_c_path),
			"python_probe": str(py_path),
			"ds4_count": int(len(ds4_names)),
			"python_count": int(len(py_names)),
			"missing_in_python": missing_in_python,
			"extra_in_python": extra_in_python,
			"order_mismatches": order_mismatches[:64],
		}
		print(json.dumps(out, indent=2, sort_keys=True))
	else:
		if ok:
			print("ok=true")
		else:
			if missing_in_python:
				print(f"missing_in_python={len(missing_in_python)} (e.g. {missing_in_python[0]!r})")
			if extra_in_python:
				print(f"extra_in_python={len(extra_in_python)} (e.g. {extra_in_python[0]!r})")
			raise SystemExit(1)


if __name__ == "__main__":
	main()
