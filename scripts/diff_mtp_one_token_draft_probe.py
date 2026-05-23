#!/usr/bin/env python3
"""Diff two one-token MTP draft probe JSON blobs.

This is intended for "oracle vs candidate" comparisons before running MTP
acceptance sweeps. It is strict by default: token IDs and intermediate tensor
fingerprints must match when present.

Probe format reference:
- docs/mtp.md (required keys + optional debug keys)
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


DEFAULT_CAPTURE_KEYS = [
	"trunk_token_embd",
	"trunk_pre_hc_head",
	"mtp_input_hc",
	"mtp_block_out_hc",
	"mtp_head_norm",
]


def _capture_prefixes(obj: dict[str, Any]) -> set[str]:
	out: set[str] = set()
	for k in obj.keys():
		if not isinstance(k, str):
			continue
		if not k.endswith("_fnv64"):
			continue
		if k.endswith("_hc_major_fnv64"):
			continue
		prefix = k[: -len("_fnv64")]
		if prefix:
			out.add(prefix)
	return out


def _load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def _get(obj: dict[str, Any], key: str) -> Any:
	return obj.get(key, None)


def _is_hex_u64(s: Any) -> bool:
	if not isinstance(s, str):
		return False
	if len(s) != 16:
		return False
	for c in s:
		if c not in "0123456789abcdef":
			return False
	return True


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


def _cmp_sample_f32(
	out: dict[str, Any],
	key: str,
	a: Any,
	b: Any,
	*,
	tol: float,
) -> None:
	a_list = _as_float_list(a)
	b_list = _as_float_list(b)
	if a_list is None and b_list is None:
		return
	if a_list is None or b_list is None:
		out["notes"].append(f"sample differs: {key} present_in_a={a_list is not None} present_in_b={b_list is not None}")
		return
	if len(a_list) != len(b_list):
		out["mismatches"].append(
			{
				"key": key,
				"reason": "sample_len",
				"a_len": len(a_list),
				"b_len": len(b_list),
			}
		)
		return
	max_abs = 0.0
	max_i = -1
	max_a = 0.0
	max_b = 0.0
	for i, (va, vb) in enumerate(zip(a_list, b_list)):
		d = abs(va - vb)
		if d > max_abs:
			max_abs = d
			max_i = i
			max_a = va
			max_b = vb
	if max_abs > tol:
		out["mismatches"].append(
			{
				"key": key,
				"reason": "sample_tol",
				"tol": tol,
				"max_abs_diff": max_abs,
				"max_idx": max_i,
				"a_at_max": max_a,
				"b_at_max": max_b,
			}
		)


def _cmp_value(
	out: dict[str, Any],
	key: str,
	a: Any,
	b: Any,
	*,
	required: bool,
) -> None:
	if a is None and b is None:
		if required:
			out["errors"].append(f"missing key in both probes: {key}")
		return
	if a is None or b is None:
		out["mismatches"].append({"key": key, "a": a, "b": b, "reason": "missing"})
		return
	if a != b:
		out["mismatches"].append({"key": key, "a": a, "b": b, "reason": "different"})


def diff_one_token_mtp_probes(
	a: dict[str, Any],
	b: dict[str, Any],
	*,
	require_token_match: bool = True,
	require_capture_match: bool = True,
	sample_tol: float = 1.0e-5,
) -> dict[str, Any]:
	out: dict[str, Any] = {
		"ok": False,
		"errors": [],
		"mismatches": [],
		"notes": [],
	}

	if not isinstance(a, dict) or not isinstance(b, dict):
		out["errors"].append("probe JSON must be objects")
		return out

	# Context keys should be present, but do not require equality: oracle vs candidate
	# comparisons will often use different runtime repos/commits and different local paths.
	for k in ("runtime_repo", "runtime_commit", "trunk_gguf_path", "mtp_sidecar_path"):
		va = _get(a, k)
		vb = _get(b, k)
		if va is None and vb is None:
			out["errors"].append(f"missing key in both probes: {k}")
			continue
		if va is None or vb is None:
			out["mismatches"].append({"key": k, "a": va, "b": vb, "reason": "missing"})
			continue
		if va != vb:
			out["notes"].append(f"context differs: {k}")

	prompt_a = _get(a, "prompt_sha256") if _get(a, "prompt_sha256") is not None else _get(a, "prompt")
	prompt_b = _get(b, "prompt_sha256") if _get(b, "prompt_sha256") is not None else _get(b, "prompt")
	_cmp_value(out, "prompt_or_sha256", prompt_a, prompt_b, required=True)

	if require_token_match:
		for k in ("base_next_token_id", "mtp_draft_token_id"):
			_cmp_value(out, k, _get(a, k), _get(b, k), required=True)
	else:
		out["notes"].append("token ID comparison disabled")

	# Optional debug captures: compare any `*_fnv64` captures when present in either probe.
	# This lets new intermediate captures be added without patching this script.
	found_prefixes = sorted(_capture_prefixes(a) | _capture_prefixes(b))
	using_default_prefixes = (len(found_prefixes) == 0)
	prefixes = found_prefixes if found_prefixes else list(DEFAULT_CAPTURE_KEYS)

	for prefix in prefixes:
		fnv_key = f"{prefix}_fnv64"
		nbytes_key = f"{prefix}_nbytes"
		shape_key = f"{prefix}_shape"
		sample_key = f"{prefix}_sample_f32"

		fnv_a, fnv_b = _get(a, fnv_key), _get(b, fnv_key)
		if fnv_a is None and fnv_b is None:
			if require_capture_match and using_default_prefixes:
				out["mismatches"].append({"key": fnv_key, "a": None, "b": None, "reason": "missing_both"})
			elif require_capture_match:
				out["notes"].append(f"capture missing in both probes: {prefix}")
			continue

		if fnv_a is not None and not _is_hex_u64(fnv_a):
			out["errors"].append(f"{fnv_key} in probe A is not a 16-nybble lowercase hex string")
		if fnv_b is not None and not _is_hex_u64(fnv_b):
			out["errors"].append(f"{fnv_key} in probe B is not a 16-nybble lowercase hex string")

		_cmp_value(out, fnv_key, fnv_a, fnv_b, required=require_capture_match)
		_cmp_value(out, nbytes_key, _get(a, nbytes_key), _get(b, nbytes_key), required=require_capture_match)
		_cmp_value(out, shape_key, _get(a, shape_key), _get(b, shape_key), required=require_capture_match)
		_cmp_sample_f32(out, sample_key, _get(a, sample_key), _get(b, sample_key), tol=float(sample_tol))

	out["ok"] = (len(out["errors"]) == 0 and len(out["mismatches"]) == 0)
	return out


def _print_human(result: dict[str, Any]) -> int:
	ok = bool(result.get("ok", False))
	if ok:
		print("ok: probes match")
		return 0
	for e in result.get("errors", [])[:64]:
		print(f"error: {e}")
	for m in result.get("mismatches", [])[:64]:
		k = m.get("key")
		r = m.get("reason")
		print(f"mismatch: {k} ({r})")
	return 1


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--a", required=True, help="Probe JSON A (oracle).")
	ap.add_argument("--b", required=True, help="Probe JSON B (candidate).")
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	ap.add_argument("--no-token-match", action="store_true", help="Do not require token ID matches.")
	ap.add_argument("--no-capture-match", action="store_true", help="Do not require debug capture matches.")
	ap.add_argument("--sample-tol", type=float, default=1.0e-5, help="Max abs diff allowed for *_sample_f32 arrays.")
	args = ap.parse_args(argv)

	a = _load_json(Path(args.a))
	b = _load_json(Path(args.b))
	result = diff_one_token_mtp_probes(
		a if isinstance(a, dict) else {},
		b if isinstance(b, dict) else {},
		require_token_match=not args.no_token_match,
		require_capture_match=not args.no_capture_match,
		sample_tol=float(args.sample_tol),
	)

	if args.json:
		print(json.dumps(result, indent=2, sort_keys=True))
		return 0 if result.get("ok", False) else 1

	return _print_human(result)


if __name__ == "__main__":
	sys.exit(main())
