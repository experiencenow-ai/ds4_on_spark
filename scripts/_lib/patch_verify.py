#!/usr/bin/env python3
"""Shared helpers for text-only patch contract verifiers."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path


def die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def read_text_or_die(path: str) -> str:
	try:
		with open(path, "r", encoding="utf-8") as f:
			return f.read()
	except OSError as exc:
		die(f"failed to read {path}: {exc}")


def added_patch_lines(patch_text: str) -> list[str]:
	return [
		line[1:]
		for line in patch_text.splitlines()
		if line.startswith("+") and not line.startswith("+++ ")
	]


def added_patch_text(patch_text: str) -> str:
	return "\n".join(added_patch_lines(patch_text))


def removed_patch_text(patch_text: str) -> str:
	return "\n".join(
		line[1:]
		for line in patch_text.splitlines()
		if line.startswith("-") and not line.startswith("--- ")
	)


def require_substrings(errors: list[str], text: str, substrings: Iterable[str], label: str = "expected substring") -> None:
	for substring in substrings:
		if substring not in text:
			errors.append(f"missing {label}: {substring!r}")


def extract_added_hunk_or_die(patch_text: str, diff_header: str) -> tuple[str, int, list[str]]:
	pos = patch_text.find(diff_header)
	if pos < 0:
		die(f"missing diff header: {diff_header}")
	lines = patch_text[pos:].splitlines()
	hunk_i = next((i for i,line in enumerate(lines) if line.startswith("@@ ")), -1)
	if hunk_i < 0:
		die(f"missing hunk header after diff header: {diff_header}")
	hunk_hdr = lines[hunk_i]
	try:
		n_decl = int(hunk_hdr.split("+1,", 1)[1].split(" @@")[0])
	except (IndexError, ValueError):
		die(f"unexpected hunk header: {hunk_hdr!r}")
	added = []
	for line in lines[hunk_i + 1:]:
		if line.startswith("diff --git "):
			break
		if line.startswith("+") and not line.startswith("+++ "):
			added.append(line[1:])
	return hunk_hdr, n_decl, added


def run_patch_verifier(validate_patch_text: Callable[[str], list[str]]) -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	errors = validate_patch_text(read_text_or_die(args.patch))
	if errors:
		for error in errors[:64]:
			print(f"error: {error}", file=sys.stderr)
		raise SystemExit(2)
	print("ok=true")


def run_json_patch_report(verify_patch: Callable[[Path], dict[str, object]]) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	result = verify_patch(Path(args.patch))
	print(json.dumps(result, indent=2, sort_keys=True))
	return 0 if result["ok"] else 1
