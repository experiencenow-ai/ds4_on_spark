#!/usr/bin/env python3
"""Shared Python helpers used by the Centaur diamond loop shell scripts.

The shell driver, review-queue release helper, and apply_approved helper all
need small JSON/path utilities. Each used to inline a python heredoc with
near-identical preambles, which the complexity gate flagged as repeated
normalized blocks. Extracting them here removes the duplication and gives
us one place to harden the contract.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


def utc_now() -> dt.datetime:
	return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def parse_time(value: str) -> dt.datetime:
	if not value:
		return utc_now()
	if value.endswith("Z"):
		value = value[:-1] + "+00:00"
	parsed = dt.datetime.fromisoformat(value)
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=dt.timezone.utc)
	return parsed.astimezone(dt.timezone.utc).replace(microsecond=0)


def safe_segment(value: str, limit: int = 180, fallback: str = "item") -> str:
	safe = re.sub(r"[^A-Za-z0-9_.@+-]+", "_", value).strip("_")
	return safe[:limit] or fallback


def safe_path_segment(value: str, limit: int = 80, fallback: str = "candidate") -> str:
	"""Path-safe variant used by apply_approved (stricter regex, dash instead of underscore)."""
	safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
	safe = safe.replace("..", ".")
	return (safe[:limit] or fallback).rstrip(".-") or fallback


def load_json(path: Path) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as source:
		data = json.load(source)
	if not isinstance(data, dict):
		raise ValueError(f"{path} did not contain a JSON object")
	return data


def write_json(path: Path, data: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract_source_from_text(text: str) -> str:
	"""Extract Python source from a code-fenced LLM response, or return text as-is."""
	stripped = text.strip()
	fenced = re.search(r"```(?:python)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
	if fenced:
		return fenced.group(1).strip() + "\n"
	return stripped + ("\n" if stripped else "")
