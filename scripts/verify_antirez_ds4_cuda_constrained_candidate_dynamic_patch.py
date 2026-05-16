#!/usr/bin/env python3
"""Verify the antirez/ds4 dynamic constrained-candidate patch contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_SNIPPETS = [
	"static uint32_t cuda_stack_probe_count_constrained_ids(void)",
	"const uint32_t constrained_capacity = cuda_stack_probe_count_constrained_ids();",
	"int32_t *constrained_ids = constrained_capacity != 0 ? xmalloc",
	"cuda_stack_probe_parse_constrained_ids(constrained_ids, constrained_capacity)",
	"constrained_capacity != constrained_count",
	"constrained token commit parsed %u candidate ids, expected %u",
	"constrained_token_count_requested",
	"constrained_token_count_enforced",
	"free(constrained_ids)",
]

FORBIDDEN_SNIPPETS = [
	"int32_t constrained_ids[256]",
	"cuda_stack_probe_parse_constrained_ids(constrained_ids, 256u)",
]


def verify_patch(path: Path) -> dict[str, object]:
	text = path.read_text(encoding="utf-8")
	added = "\n".join(
		line[1:]
		for line in text.splitlines()
		if line.startswith("+") and not line.startswith("+++ ")
	)
	removed = "\n".join(
		line[1:]
		for line in text.splitlines()
		if line.startswith("-") and not line.startswith("--- ")
	)
	missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in added]
	forbidden = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet in added]
	not_removed = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet not in removed]
	return {
		"format": "ds4-antirez-constrained-candidate-dynamic-patch-check-v1",
		"patch": str(path),
		"ok": len(missing) == 0 and len(forbidden) == 0 and len(not_removed) == 0,
		"missing": missing,
		"forbidden": forbidden,
		"not_removed": not_removed,
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	result = verify_patch(Path(args.patch))
	print(json.dumps(result, indent=2, sort_keys=True))
	return 0 if result["ok"] else 1


if __name__ == "__main__":
	raise SystemExit(main())
