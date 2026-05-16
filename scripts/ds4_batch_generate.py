#!/usr/bin/env python3
"""Fixture-backed DS4 batch-generate CLI.

This is the production API envelope without a live DS4 runtime backend. It
validates the request, splits output modes into compatible internal groups, and
emits deterministic committed-token records with production eligibility blocked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from validate_ds4_batch_generate import (
	Ds4BatchGenerateError,
	build_result_from_request,
	load_json,
	validate_result,
	write_json,
)


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--request", required=True)
	ap.add_argument("--output", required=True)
	args = ap.parse_args()
	try:
		request = load_json(Path(args.request))
		result = build_result_from_request(request)
		errors = validate_result(result, request)
		if errors:
			raise Ds4BatchGenerateError("; ".join(errors))
		write_json(Path(args.output), result)
		print(json.dumps(result, indent=2, sort_keys=True))
	except (OSError, json.JSONDecodeError, Ds4BatchGenerateError) as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
