#!/usr/bin/env python3
"""Lightweight structural verifier for the llama.cpp one-token MTP probe patch.

This is a diff-gate, not a build/test. It makes sure the patch keeps emitting
the oracle-diff keys (FNV-1a 64-bit fingerprints + shape/nbytes metadata) with a
stable hashing implementation so `scripts/diff_mtp_one_token_draft_probe.py`
remains a meaningful correctness guardrail.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


def _die(msg: str) -> None:
	print(msg, file=sys.stderr)
	raise SystemExit(2)


def _read_text(path: str) -> str:
	try:
		with open(path, "r", encoding="utf-8") as f:
			return f.read()
	except OSError as e:
		_die(f"failed to read {path}: {e}")
	return ""


def validate_patch_text(patch_text: str, *, patch_path: Optional[str] = None) -> list[str]:
	errors: list[str] = []
	expected_commit = _expected_runtime_commit(patch_path) if patch_path is not None else None

	cpp_header = (
		"diff --git a/examples/ds4-mtp-one-token-draft-probe/ds4-mtp-one-token-draft-probe.cpp "
		"b/examples/ds4-mtp-one-token-draft-probe/ds4-mtp-one-token-draft-probe.cpp"
	)
	hunk_hdr, n_decl, added = _extract_added_hunk(patch_text, cpp_header)
	if len(added) != n_decl:
		errors.append(
			f"hunk line count mismatch for one-token cpp: declared={n_decl} actual={len(added)} (header={hunk_hdr!r})"
		)

	joined = "\n".join(added) + "\n"

	if expected_commit is not None:
		runtime_lines = [ln for ln in added if "runtime_commit" in ln]
		if len(runtime_lines) != 1:
			errors.append(f"expected exactly one runtime_commit printf line, got {len(runtime_lines)}")
		else:
			m = re.search(r',\s*"([0-9a-f]{7,})"\);', runtime_lines[0])
			if not m:
				errors.append(f"failed to parse runtime_commit from line: {runtime_lines[0]!r}")
			else:
				actual_commit = m.group(1)
				if actual_commit != expected_commit:
					errors.append(
						f"runtime_commit mismatch: expected {expected_commit} (from filename), got {actual_commit}"
					)

	if "TODO: implement gamma=1 MTP draft compute" not in joined:
		errors.append("one-token probe cpp hunk missing expected TODO marker (patch likely truncated)")

	# The oracle diff relies on stable FNV-1a 64-bit hashing. Keep it byte-based and
	# lowercase 16-nybble hex formatted to match the ds4 oracle patch.
	required_fnv_markers = [
		"static uint64_t fnv1a64(",
		"uint64_t h = 14695981039346656037ull;",
		"h ^= (uint64_t) p[i];",
		"h *= 1099511628211ull;",
		"%016llx",
	]
	for marker in required_fnv_markers:
		if marker not in joined:
			errors.append(f"missing expected FNV marker in cpp hunk: {marker!r}")

	# Require the baseline capture keys so diffs remain actionable while draft
	# compute is still under implementation.
	required_capture_keys = [
		"trunk_token_embd_fnv64",
		"trunk_token_embd_nbytes",
		"trunk_token_embd_shape",
		"trunk_pre_hc_head_fnv64",
		"trunk_pre_hc_head_nbytes",
		"trunk_pre_hc_head_shape",
		"mtp_input_hc_fnv64",
		"mtp_input_hc_nbytes",
		"mtp_input_hc_shape",
		"mtp_head_norm_fnv64",
		"mtp_head_norm_nbytes",
		"mtp_head_norm_shape",
	]
	for k in required_capture_keys:
		if f"\\\"{k}\\\"" not in joined:
			errors.append(f"missing expected JSON key in cpp hunk: {k!r}")

	hpp_header = (
		"diff --git a/examples/ds4-mtp-one-token-draft-probe/deepseek4_mtp_sidecar.hpp "
		"b/examples/ds4-mtp-one-token-draft-probe/deepseek4_mtp_sidecar.hpp"
	)
	_hhdr, _ndecl, _added = _extract_added_hunk(patch_text, hpp_header)
	if len(_added) != _ndecl:
		errors.append(
			f"hunk line count mismatch for binder header: declared={_ndecl} actual={len(_added)} (header={_hhdr!r})"
		)

	return errors


def _extract_added_hunk(patch_text: str, needle: str) -> tuple[str, int, list[str]]:
	pos = patch_text.find(needle)
	if pos < 0:
		_die(f"missing diff header: {needle}")

	after = patch_text[pos:]
	lines = after.splitlines()

	hunk_i = -1
	for i, line in enumerate(lines):
		if line.startswith("@@ "):
			hunk_i = i
			break
	if hunk_i < 0:
		_die(f"missing hunk header after diff header: {needle}")

	hunk_hdr = lines[hunk_i]
	try:
		right = hunk_hdr.split("+1,", 1)[1]
		n_str = right.split(" @@")[0]
		n_decl = int(n_str)
	except Exception:
		_die(f"unexpected hunk header: {hunk_hdr!r}")

	added: list[str] = []
	for line in lines[hunk_i + 1 :]:
		if line.startswith("diff --git "):
			break
		if line.startswith("+++ "):
			continue
		if line.startswith("+"):
			added.append(line[1:])

	return hunk_hdr, n_decl, added


def _expected_runtime_commit(patch_path: str) -> Optional[str]:
	name = Path(patch_path).name
	m = re.search(r"deepseek-v4-flash-cuda-spark-([0-9a-f]+)-mtp-one-token", name)
	if m:
		return m.group(1)
	return None


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()

	patch_text = _read_text(args.patch)
	errors = validate_patch_text(patch_text, patch_path=args.patch)
	if errors:
		for e in errors[:64]:
			print(f"error: {e}", file=sys.stderr)
		raise SystemExit(2)

	print("ok=true")


if __name__ == "__main__":
	main()
