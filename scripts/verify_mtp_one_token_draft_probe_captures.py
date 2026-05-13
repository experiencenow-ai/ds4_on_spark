#!/usr/bin/env python3
"""Validate that a one-token MTP draft probe JSON includes expected capture keys.

This gate is intentionally lightweight: it does not require model weights or CUDA.
It only checks the presence and basic shape of `*_fnv64` captures so downstream
oracle-vs-candidate diffs can localize correctness mismatches before acceptance
sweeps.

Reference:
- docs/mtp-one-token-draft-probe.md (optional debug keys)
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


DEFAULT_PREFIXES = [
	"trunk_token_embd",
	"trunk_pre_hc_head",
	"mtp_input_hc",
	"mtp_block_out_hc",
	"mtp_head_norm",
]

EXTENDED_PREFIXES = DEFAULT_PREFIXES + [
	"mtp_enorm",
	"mtp_eproj",
	"mtp_eproj_hc",
	"mtp_hnorm_hc",
	"mtp_hproj_hc",
]

PROFILE_PREFIXES = {
	"default": DEFAULT_PREFIXES,
	"extended": EXTENDED_PREFIXES,
}


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
	if val is None:
		return
	if not isinstance(val, int):
		errors.append(f"key {key} has type {type(val).__name__}, expected int")


def _expect_shape(key: str, val: Any, errors: list[str]) -> None:
	if val is None:
		return
	if not isinstance(val, list):
		errors.append(f"key {key} has type {type(val).__name__}, expected list[int]")
		return
	for i, v in enumerate(val[:32]):
		if not isinstance(v, int):
			errors.append(f"key {key}[{i}] has type {type(v).__name__}, expected int")
			return


def _as_float_list(val: Any) -> Optional[list[float]]:
	if val is None:
		return None
	if not isinstance(val, list):
		return None
	out: list[float] = []
	for v in val[:1024]:
		if isinstance(v, bool):
			return None
		if not isinstance(v, (int, float)):
			return None
		out.append(float(v))
	return out


def verify_probe_captures(probe: dict[str, Any], *, profile: str) -> dict[str, Any]:
	errors: list[str] = []
	warnings: list[str] = []

	required = PROFILE_PREFIXES.get(profile, None)
	if required is None:
		return {
			"ok": False,
			"errors": [f"unknown profile: {profile!r}"],
			"warnings": [],
			"profile": profile,
			"required_prefixes": [],
			"missing_prefixes": [],
			"present_prefixes": [],
		}

	present_prefixes: set[str] = set()
	for k in probe.keys():
		if not isinstance(k, str):
			continue
		if not k.endswith("_fnv64"):
			continue
		if k.endswith("_hc_major_fnv64"):
			continue
		prefix = k[: -len("_fnv64")]
		if prefix:
			present_prefixes.add(prefix)

	missing: list[str] = []
	incomplete: list[str] = []

	for prefix in required:
		fnv_key = f"{prefix}_fnv64"
		nbytes_key = f"{prefix}_nbytes"
		shape_key = f"{prefix}_shape"
		sample_key = f"{prefix}_sample_f32"
		hc_major_key = f"{prefix}_hc_major_fnv64"

		fnv = probe.get(fnv_key, None)
		nbytes = probe.get(nbytes_key, None)
		shape = probe.get(shape_key, None)
		sample = probe.get(sample_key, None)

		if fnv is None and nbytes is None and shape is None:
			if probe.get(hc_major_key, None) is not None:
				warnings.append(f"capture present only as {hc_major_key}; prefer {fnv_key}/{nbytes_key}/{shape_key}")
			missing.append(prefix)
			continue

		if fnv is None or nbytes is None or shape is None:
			incomplete.append(prefix)

		if fnv is not None and not _is_hex_u64(fnv):
			errors.append(f"{fnv_key} is not a 16-nybble lowercase hex string")
		_expect_int(nbytes_key, nbytes, errors)
		_expect_shape(shape_key, shape, errors)

		if sample is not None:
			sample_list = _as_float_list(sample)
			if sample_list is None:
				errors.append(f"{sample_key} is present but is not a float list")

	for prefix in incomplete:
		warnings.append(f"capture has partial keys: {prefix} (expected _fnv64 + _nbytes + _shape)")

	for prefix in missing:
		errors.append(f"missing capture prefix: {prefix}")

	return {
		"ok": (len(errors) == 0),
		"errors": errors,
		"warnings": warnings,
		"profile": profile,
		"required_prefixes": list(required),
		"missing_prefixes": missing,
		"present_prefixes": sorted(present_prefixes),
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--probe-json", required=True, help="Path to one-token draft probe JSON output.")
	ap.add_argument(
		"--profile",
		default="default",
		choices=sorted(PROFILE_PREFIXES.keys()),
		help="Which capture set to require (default: default).",
	)
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	args = ap.parse_args(argv)

	doc = _load_json(Path(args.probe_json))
	if not isinstance(doc, dict):
		out = {
			"ok": False,
			"errors": ["probe-json top-level is not an object"],
			"warnings": [],
			"profile": str(args.profile),
			"required_prefixes": list(PROFILE_PREFIXES.get(str(args.profile), [])),
			"missing_prefixes": [],
			"present_prefixes": [],
		}
		if args.json:
			print(json.dumps(out, indent=2, sort_keys=True))
			return 1
		print("error: probe-json top-level is not an object", file=sys.stderr)
		return 1

	result = verify_probe_captures(doc, profile=str(args.profile))
	if args.json:
		print(json.dumps(result, indent=2, sort_keys=True))
		return 0 if result.get("ok", False) else 1

	for w in result.get("warnings", [])[:64]:
		print(f"warning: {w}")
	for e in result.get("errors", [])[:64]:
		print(f"error: {e}")
	print(f"ok: {str(bool(result.get('ok', False))).lower()}")
	return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
	sys.exit(main())

