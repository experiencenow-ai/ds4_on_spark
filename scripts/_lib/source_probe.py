from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Pattern


def sha256_file(path: str | Path) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		while True:
			b = f.read(1024 * 1024)
			if not b:
				break
			h.update(b)
	return h.hexdigest()


def scan_file(path: str | Path, patterns: list[tuple[str, Pattern[str]]], max_matches: int = 50) -> list[dict[str, object]]:
	matches = []
	try:
		with open(path, "r", encoding="utf-8", errors="replace") as f:
			for i, line in enumerate(f, start=1):
				ln = line.rstrip("\n")
				for name, rx in patterns:
					if rx.search(ln):
						matches.append({"pattern": name, "line": i, "text": ln[:4000]})
						break
				if len(matches) >= max_matches:
					break
	except Exception:
		return []
	return matches
