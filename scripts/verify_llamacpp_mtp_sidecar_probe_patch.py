#!/usr/bin/env python3
import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._lib.patch_verify import die
from scripts._lib.patch_verify import extract_added_hunk_or_die
from scripts._lib.patch_verify import read_text_or_die


def _extract_cpp_hunk(patch_text: str) -> tuple[str, int, list[str]]:
	needle = "diff --git a/examples/ds4-mtp-sidecar-probe/ds4-mtp-sidecar-probe.cpp b/examples/ds4-mtp-sidecar-probe/ds4-mtp-sidecar-probe.cpp"
	return extract_added_hunk_or_die(patch_text, needle)


def main() -> None:
	import argparse

	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	patch_text = read_text_or_die(args.patch)
	hunk_hdr, n_decl, added = _extract_cpp_hunk(patch_text)

	if len(added) != n_decl:
		die(f"hunk line count mismatch for ds4-mtp-sidecar-probe.cpp: declared={n_decl} actual={len(added)} (header={hunk_hdr!r})")

	joined = "\n".join(added) + "\n"
	if "return ok ? 0 : 3;" not in joined:
		die("probe cpp hunk missing expected tail 'return ok ? 0 : 3;' (patch likely truncated)")

	print("ok=true")


if __name__ == "__main__":
	main()
