#!/usr/bin/env python3
"""Verify required debug capture keys exist in an MTP one-token draft probe JSON.

The one-token probe contract (`scripts/model_contract_validate_mtp_one_token_draft_probe.py`)
intentionally treats debug capture keys as optional so runtimes can stage wiring.

Before running MTP acceptance sweeps, we want a *repeatable guardrail* that both
oracle and candidate probes emit (and therefore can diff) a stable set of
intermediate fingerprints.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


DEFAULT_REQUIRED_PREFIXES = [
	"trunk_token_embd",
	"trunk_pre_hc_head",
	"mtp_input_hc",
	"mtp_block_out_hc",
	"mtp_head_norm",
]


def _load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def _is_hex_u64(s: Any) -> bool:
	if not isinstance(s, str):
		return False
	if len(s) != 16:
		return False
	for c in s:
		if c not in "0123456789abcdef":
			return False
	return True


def _expect_int(key: str, val: Any, errors: list[str]) -> None:
	if not isinstance(val, int):
		errors.append(f"key {key} has type {type(val).__name__}, expected int")


def _expect_shape(key: str, val: Any, errors: list[str]) -> None:
	if not isinstance(val, list):
		errors.append(f"key {key} has type {type(val).__name__}, expected list")
		return
	for i, v in enumerate(val[:64]):
		if not isinstance(v, int):
			errors.append(f"key {key}[{i}] has type {type(v).__name__}, expected int")
			return
		if v <= 0:
			errors.append(f"key {key}[{i}] is {v}, expected > 0")
			return


def verify_required_captures(
	probe: dict[str, Any],
	*,
	required_prefixes: list[str],
) -> dict[str, Any]:
	out: dict[str, Any] = {
		"ok": False,
		"errors": [],
		"warnings": [],
		"required_prefixes": list(required_prefixes),
	}

	if not isinstance(probe, dict):
		out["errors"].append("probe JSON must be an object")
		return out

	errors: list[str] = out["errors"]
	warnings: list[str] = out["warnings"]

	for prefix in required_prefixes:
		fnv_key = f"{prefix}_fnv64"
		nbytes_key = f"{prefix}_nbytes"
		shape_key = f"{prefix}_shape"

		fnv = probe.get(fnv_key, None)
		nbytes = probe.get(nbytes_key, None)
		shape = probe.get(shape_key, None)

		if fnv is None and nbytes is None and shape is None:
			errors.append(f"missing capture prefix: {prefix} (expected {fnv_key}/{nbytes_key}/{shape_key})")
			continue

		# Partial presence is usually a bug in probe emitters; make it explicit.
		if fnv is None:
			errors.append(f"missing key: {fnv_key}")
		if nbytes is None:
			errors.append(f"missing key: {nbytes_key}")
		if shape is None:
			errors.append(f"missing key: {shape_key}")

		if fnv is not None and not _is_hex_u64(fnv):
			errors.append(f"{fnv_key} is not a 16-nybble lowercase hex string")

		if nbytes is not None:
			_expect_int(nbytes_key, nbytes, errors)
			if isinstance(nbytes, int) and nbytes <= 0:
				errors.append(f"key {nbytes_key} is {nbytes}, expected > 0")

		if shape is not None:
			_expect_shape(shape_key, shape, errors)

		if isinstance(nbytes, int) and isinstance(shape, list) and len(shape) == 0:
			warnings.append(f"key {shape_key} is empty (unexpected for {prefix})")

	out["ok"] = (len(errors) == 0)
	return out


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--probe-json", required=True, help="Path to one-token draft probe JSON output.")
	ap.add_argument(
		"--require",
		action="append",
		default=[],
		help="Capture prefix to require (repeatable). Defaults to a recommended set when omitted.",
	)
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	args = ap.parse_args(argv)

	probe = _load_json(Path(args.probe_json))
	required = list(args.require) if args.require else list(DEFAULT_REQUIRED_PREFIXES)
	res = verify_required_captures(probe if isinstance(probe, dict) else {}, required_prefixes=required)

	if args.json:
		print(json.dumps(res, indent=2, sort_keys=True))
		return 0 if res.get("ok", False) else 1

	if res.get("ok", False):
		print("ok: required captures present")
		return 0
	for e in (res.get("errors") or [])[:64]:
		print(f"error: {e}")
	for w in (res.get("warnings") or [])[:64]:
		print(f"warning: {w}")
	return 1


if __name__ == "__main__":
	sys.exit(main())

