"""Shared model-contract parsing helpers."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import BinaryIO, Iterable


def read_bytes(f: BinaryIO, n: int) -> bytes:
	data = f.read(n)
	if len(data) != n:
		raise EOFError(f"unexpected EOF reading {n} bytes")
	return data


def find_mtp_layer_ids(weight_keys: Iterable[str]) -> list[int]:
	ids = set()
	for key in weight_keys:
		if not key.startswith("mtp."):
			continue
		parts = key.split(".", 2)
		if len(parts) < 2:
			continue
		try:
			ids.add(int(parts[1]))
		except ValueError:
			continue
	return sorted(ids)


def parse_string_list_assignment(py_path: Path, variable_name: str) -> list[str] | None:
	if not py_path.exists():
		return None
	try:
		mod = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
	except SyntaxError:
		return None
	found: list[list[str]] = []
	for node in ast.walk(mod):
		if not isinstance(node, ast.Assign) or len(node.targets) != 1:
			continue
		target = node.targets[0]
		if not isinstance(target, ast.Name) or target.id != variable_name:
			continue
		if not isinstance(node.value, ast.List):
			continue
		values = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
		if len(values) == len(node.value.elts) and values:
			found.append(values)
	if not found:
		return None
	found.sort(key=len, reverse=True)
	return list(found[0])


def parse_ds4_mtp_sidecar_expected_tensor_names(probe_py: Path) -> list[str] | None:
	return parse_string_list_assignment(probe_py, "expected_names")


def parse_tokenizer_added_token_ids(tokenizer_json: Path) -> dict[str, int] | None:
	if not tokenizer_json.exists():
		return None
	try:
		tok = json.loads(tokenizer_json.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None
	added_tokens = tok.get("added_tokens") if isinstance(tok, dict) else None
	if not isinstance(added_tokens, list):
		return None
	out: dict[str, int] = {}
	for token in added_tokens:
		if not isinstance(token, dict):
			continue
		content = token.get("content", None)
		tid = token.get("id", None)
		if isinstance(content, str) and isinstance(tid, int):
			out[content] = int(tid)
	return out
