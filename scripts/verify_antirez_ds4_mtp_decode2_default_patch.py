#!/usr/bin/env python3
"""Verify the antirez/ds4 MTP decode2-default verifier patch."""

from __future__ import annotations

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


def validate_patch_text(patch_text: str) -> list[str]:
	errors: list[str] = []
	added_lines = [
		line[1:]
		for line in patch_text.splitlines()
		if line.startswith("+") and not line.startswith("+++ ")
	]
	removed_lines = [
		line[1:]
		for line in patch_text.splitlines()
		if line.startswith("-") and not line.startswith("--- ")
	]
	added_text = "\n".join(added_lines)
	removed_text = "\n".join(removed_lines)
	required_substrings = [
		"diff --git a/ds4.c b/ds4.c",
		"int ds4_session_eval_speculative_argmax(ds4_session *s, int first_token,",
	]
	for s in required_substrings:
		if s not in patch_text:
			errors.append(f"missing expected substring: {s!r}")
	for s in [
		"The useful N=2 verifier is the exact decode2 path",
		"that is slower than target-only decode on CUDA/Metal",
		"draft_n == 2 && getenv(\"DS4_MTP_BATCH_VERIFY\") == NULL",
		"ds4: mtp conf drafted=%d committed=%d mtp_top=%d runner=%d margin=%.6f target_next=%d draft_next=%d\\n",
		"row0_top,",
		"drafts[1]);",
	]:
		if s not in added_text:
			errors.append(f"missing expected added substring: {s!r}")
	for s in [
		"draft_n == 2 && strict_mtp && getenv(\"DS4_MTP_BATCH_VERIFY\") == NULL",
		"DS4_MTP_STRICT selects the exact decode verifier",
	]:
		if s not in removed_text:
			errors.append(f"missing expected removed substring: {s!r}")
		if s in added_text:
			errors.append(f"found stale decode2 gate/comment on an added line: {s!r}")
	conf_count = added_text.count("ds4: mtp conf drafted=%d committed=%d mtp_top=%d runner=%d margin=%.6f target_next=%d draft_next=%d\\n")
	if conf_count < 2:
		errors.append("patch must add MTP conf logging for both decode2 full and prefix-1 accept paths")
	return errors


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--patch", required=True)
	args = ap.parse_args()
	errors = validate_patch_text(_read_text(args.patch))
	if errors:
		for e in errors[:64]:
			print(f"error: {e}", file=sys.stderr)
		raise SystemExit(2)
	print("ok=true")


if __name__ == "__main__":
	main()
