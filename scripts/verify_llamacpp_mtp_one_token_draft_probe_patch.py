#!/usr/bin/env python3
import argparse
import sys


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


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()

	patch_text = _read_text(args.patch)

	cpp_header = (
		"diff --git a/examples/ds4-mtp-one-token-draft-probe/ds4-mtp-one-token-draft-probe.cpp "
		"b/examples/ds4-mtp-one-token-draft-probe/ds4-mtp-one-token-draft-probe.cpp"
	)
	hunk_hdr, n_decl, added = _extract_added_hunk(patch_text, cpp_header)
	if len(added) != n_decl:
		_die(
			f"hunk line count mismatch for one-token cpp: declared={n_decl} actual={len(added)} (header={hunk_hdr!r})"
		)

	joined = "\n".join(added) + "\n"
	if "TODO: implement gamma=1 MTP draft compute" not in joined:
		_die("one-token probe cpp hunk missing expected TODO marker (patch likely truncated)")

	hpp_header = (
		"diff --git a/examples/ds4-mtp-one-token-draft-probe/deepseek4_mtp_sidecar.hpp "
		"b/examples/ds4-mtp-one-token-draft-probe/deepseek4_mtp_sidecar.hpp"
	)
	_hhdr, _ndecl, _added = _extract_added_hunk(patch_text, hpp_header)
	if len(_added) != _ndecl:
		_die(
			f"hunk line count mismatch for binder header: declared={_ndecl} actual={len(_added)} (header={_hhdr!r})"
		)

	print("ok=true")


if __name__ == "__main__":
	main()
