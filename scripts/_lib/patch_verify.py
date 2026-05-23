#!/usr/bin/env python3
"""Shared helpers for text-only patch contract verifiers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable


def read_text_or_die(path: str) -> str:
	try:
		with open(path, "r", encoding="utf-8") as f:
			return f.read()
	except OSError as exc:
		print(f"failed to read {path}: {exc}", file=sys.stderr)
		raise SystemExit(2) from exc


def added_patch_text(patch_text: str) -> str:
	return "\n".join(
		line[1:]
		for line in patch_text.splitlines()
		if line.startswith("+") and not line.startswith("+++ ")
	)


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
