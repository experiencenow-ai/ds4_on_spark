#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path


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


def _expected_runtime_commit(patch_path: str) -> str | None:
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
	expected_commit = _expected_runtime_commit(args.patch)

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
	if expected_commit is not None:
		runtime_lines = [ln for ln in added if "runtime_commit" in ln]
		if len(runtime_lines) < 1:
			_die("expected at least one runtime_commit printf line, got 0")
		for line in runtime_lines:
			m = re.search(r',\s*"([0-9a-f]{7,})"\);', line)
			if not m:
				_die(f"failed to parse runtime_commit from line: {line!r}")
			actual_commit = m.group(1)
			if actual_commit != expected_commit:
				_die(
					f"runtime_commit mismatch: expected {expected_commit} (from filename), got {actual_commit}"
				)
	if (
		"TODO: implement gamma=1 MTP draft compute" not in joined
		and "compute_mtp_gamma1_block" not in joined
	):
		_die("one-token probe cpp hunk missing expected TODO or gamma1 implementation marker (patch likely truncated)")
	if "compute_mtp_gamma1_block" in joined and "mtp_block_out_hc_fnv64" not in joined:
		_die("one-token probe gamma1 implementation missing mtp_block_out_hc fingerprint output")

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
