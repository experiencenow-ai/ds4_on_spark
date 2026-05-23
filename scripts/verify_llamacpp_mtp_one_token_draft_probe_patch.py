#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import die
from scripts._lib.patch_verify import extract_added_hunk_or_die
from scripts._lib.patch_verify import read_text_or_die


def _extract_added_hunk(patch_text: str, needle: str) -> tuple[str, int, list[str]]:
	return extract_added_hunk_or_die(patch_text, needle)


def _expected_runtime_commit(patch_path: str) -> str | None:
	name = Path(patch_path).name
	m = re.search(r"deepseek-v4-flash-cuda-spark-([0-9a-f]+)-mtp-one-token", name)
	if m:
		return m.group(1)
	return None


def main() -> None:
	import argparse

	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()

	patch_text = read_text_or_die(args.patch)
	expected_commit = _expected_runtime_commit(args.patch)

	cpp_header = (
		"diff --git a/examples/ds4-mtp-one-token-draft-probe/ds4-mtp-one-token-draft-probe.cpp "
		"b/examples/ds4-mtp-one-token-draft-probe/ds4-mtp-one-token-draft-probe.cpp"
	)
	hunk_hdr, n_decl, added = _extract_added_hunk(patch_text, cpp_header)
	if len(added) != n_decl:
		die(
			f"hunk line count mismatch for one-token cpp: declared={n_decl} actual={len(added)} (header={hunk_hdr!r})"
		)

	joined = "\n".join(added) + "\n"
	if expected_commit is not None:
		runtime_lines = [ln for ln in added if "runtime_commit" in ln]
		if len(runtime_lines) < 1:
			die("expected at least one runtime_commit printf line, got 0")
		for line in runtime_lines:
			m = re.search(r',\s*"([0-9a-f]{7,})"\);', line)
			if not m:
				die(f"failed to parse runtime_commit from line: {line!r}")
			actual_commit = m.group(1)
			if actual_commit != expected_commit:
				die(
					f"runtime_commit mismatch: expected {expected_commit} (from filename), got {actual_commit}"
				)
	if (
		"TODO: implement gamma=1 MTP draft compute" not in joined
		and "compute_mtp_gamma1_block" not in joined
	):
		die("one-token probe cpp hunk missing expected TODO or gamma1 implementation marker (patch likely truncated)")
	if "compute_mtp_gamma1_block" in joined and "mtp_block_out_hc_fnv64" not in joined:
		die("one-token probe gamma1 implementation missing mtp_block_out_hc fingerprint output")

	required_capture_keys = [
		"mtp_enorm_fnv64",
		"mtp_eproj_fnv64",
		"mtp_eproj_hc_fnv64",
		"mtp_hnorm_hc_fnv64",
		"mtp_hproj_hc_fnv64",
		"mtp_input_hc_fnv64",
	]
	for key in required_capture_keys:
		if key not in joined:
			die(f"one-token probe cpp missing expected capture key: {key}")

	hpp_header = (
		"diff --git a/examples/ds4-mtp-one-token-draft-probe/deepseek4_mtp_sidecar.hpp "
		"b/examples/ds4-mtp-one-token-draft-probe/deepseek4_mtp_sidecar.hpp"
	)
	_hhdr, _ndecl, _added = _extract_added_hunk(patch_text, hpp_header)
	if len(_added) != _ndecl:
		die(
			f"hunk line count mismatch for binder header: declared={_ndecl} actual={len(_added)} (header={_hhdr!r})"
		)

	print("ok=true")


if __name__ == "__main__":
	main()
