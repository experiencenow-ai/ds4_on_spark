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


def _extract_cpp_hunk(patch_text: str) -> tuple[str, int, list[str]]:
	needle = "diff --git a/examples/ds4-mtp-sidecar-probe/ds4-mtp-sidecar-probe.cpp b/examples/ds4-mtp-sidecar-probe/ds4-mtp-sidecar-probe.cpp"
	pos = patch_text.find(needle)
	if pos < 0:
		_die("missing ds4-mtp-sidecar-probe.cpp diff header")

	# Parse just the first hunk header of the added file.
	after = patch_text[pos:]
	lines = after.splitlines()

	hunk_i = -1
	for i, line in enumerate(lines):
		if line.startswith("@@ "):
			hunk_i = i
			break
	if hunk_i < 0:
		_die("missing hunk header for ds4-mtp-sidecar-probe.cpp")

	hunk_hdr = lines[hunk_i]
	# Expect format: @@ -0,0 +1,N @@
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
	hunk_hdr, n_decl, added = _extract_cpp_hunk(patch_text)

	if len(added) != n_decl:
		_die(f"hunk line count mismatch for ds4-mtp-sidecar-probe.cpp: declared={n_decl} actual={len(added)} (header={hunk_hdr!r})")

	joined = "\n".join(added) + "\n"
	if "return ok ? 0 : 3;" not in joined:
		_die("probe cpp hunk missing expected tail 'return ok ? 0 : 3;' (patch likely truncated)")

	print("ok=true")


if __name__ == "__main__":
	main()

