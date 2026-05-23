"""Shared CLI helpers for JSON artifact validators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Iterable


ArtifactLoader = Callable[[Path], dict[str, Any]]
ArtifactValidator = Callable[[dict[str, Any]], list[str]]


def validate_artifact_paths(paths: Iterable[str], load_json: ArtifactLoader, validate_artifact: ArtifactValidator) -> int:
	failed = False
	for raw in paths:
		path = Path(raw)
		try:
			errors = validate_artifact(load_json(path))
		except (OSError, ValueError, json.JSONDecodeError) as exc:
			print(str(exc))
			return 1
		if errors:
			failed = True
			for error in errors:
				print(f"error: {path}: {error}")
		else:
			print(f"ok: {path}")
	return 2 if failed else 0


def legacy_path_validation(argv: list[str], commands: tuple[str, ...], load_json: ArtifactLoader, validate_artifact: ArtifactValidator) -> int | None:
	if len(argv) > 1 and argv[1] not in (*commands, "-h", "--help"):
		return validate_artifact_paths(argv[1:], load_json, validate_artifact)
	return None


def add_validate_subcommand(subparsers: Any) -> None:
	validate = subparsers.add_parser("validate")
	validate.add_argument("paths", nargs="+")
