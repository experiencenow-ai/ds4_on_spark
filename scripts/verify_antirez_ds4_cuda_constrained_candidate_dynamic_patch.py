#!/usr/bin/env python3
"""Verify the antirez/ds4 dynamic constrained-candidate patch contract."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import added_patch_text
from scripts._lib.patch_verify import read_text_or_die
from scripts._lib.patch_verify import removed_patch_text
from scripts._lib.patch_verify import run_json_patch_report


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
	text = read_text_or_die(str(path))
	added = added_patch_text(text)
	removed = removed_patch_text(text)
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
	return run_json_patch_report(verify_patch)


if __name__ == "__main__":
	raise SystemExit(main())
