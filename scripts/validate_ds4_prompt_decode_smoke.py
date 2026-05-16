#!/usr/bin/env python3
"""Validate DS4 prompt-decode smoke and token-commit export artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
	from scripts import build_ds4_prompt_decode_smoke as smoke
except ImportError:
	import build_ds4_prompt_decode_smoke as smoke


def load_json(path: Path) -> dict:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("paths", nargs="+")
	args = ap.parse_args()
	failed = False
	for raw in args.paths:
		path = Path(raw)
		try:
			obj = load_json(path)
			if obj.get("format") == smoke.TOKEN_COMMIT_FORMAT:
				errors = smoke.validate_token_commit_export(obj)
			else:
				errors = smoke.validate_artifact(obj)
		except (OSError, ValueError, json.JSONDecodeError) as exc:
			errors = [str(exc)]
		if errors:
			failed = True
			for error in errors:
				print(f"error: {path}: {error}")
		else:
			print(f"ok: {path}")
	return 2 if failed else 0


if __name__ == "__main__":
	raise SystemExit(main())
