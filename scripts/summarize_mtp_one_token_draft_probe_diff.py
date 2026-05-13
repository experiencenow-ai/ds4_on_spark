#!/usr/bin/env python3
"""Summarize an oracle-vs-candidate one-token MTP probe diff.

This is a small helper for debugging: when the probes disagree, identify the
earliest mismatching stage based on an ordered capture-prefix list.

It is intentionally *fingerprint-first* (FNV64) so we don't need raw tensor
dumps to localize the first divergence.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional

from scripts import diff_mtp_one_token_draft_probe as diff


DEFAULT_STAGE_ORDER = [
	"trunk_token_embd",
	"trunk_pre_hc_head",
	"mtp_input_hc",
	"mtp_block_out_hc",
	"mtp_head_norm",
]


def _load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def _capture_tuple(obj: dict[str, Any], prefix: str) -> tuple[Any, Any, Any]:
	return (
		obj.get(f"{prefix}_fnv64", None),
		obj.get(f"{prefix}_nbytes", None),
		obj.get(f"{prefix}_shape", None),
	)


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


def _sample_stats(a: Any, b: Any) -> Optional[dict[str, Any]]:
	a_list = _as_float_list(a)
	b_list = _as_float_list(b)
	if a_list is None or b_list is None:
		return None
	n = min(len(a_list), len(b_list))
	if n == 0:
		return None
	sum_abs = 0.0
	max_abs = 0.0
	max_i = -1
	max_a = 0.0
	max_b = 0.0
	for i in range(n):
		va = a_list[i]
		vb = b_list[i]
		d = abs(va - vb)
		sum_abs += d
		if d > max_abs:
			max_abs = d
			max_i = i
			max_a = va
			max_b = vb
	return {
		"len_a": len(a_list),
		"len_b": len(b_list),
		"len_cmp": n,
		"mean_abs_diff": (sum_abs / float(n)),
		"max_abs_diff": max_abs,
		"max_idx": max_i,
		"a_at_max": max_a,
		"b_at_max": max_b,
	}


def summarize_one_token_mtp_probe_diff(
	a: dict[str, Any],
	b: dict[str, Any],
	*,
	stage_order: list[str],
) -> dict[str, Any]:
	out: dict[str, Any] = {
		"ok": False,
		"errors": [],
		"notes": [],
		"first_mismatch": None,
		"diff": None,
	}

	d = diff.diff_one_token_mtp_probes(a, b)
	out["diff"] = d

	if d.get("ok", False):
		out["ok"] = True
		return out

	errors: list[str] = out["errors"]
	if not isinstance(d, dict):
		errors.append("diff result is not an object")
		return out

	# Token-level mismatches are the first signal.
	mismatches = d.get("mismatches") or []
	for key in ("base_next_token_id", "mtp_draft_token_id", "prompt_or_sha256"):
		if any(isinstance(m, dict) and m.get("key") == key for m in mismatches):
			out["first_mismatch"] = {"kind": "token", "key": key}
			out["ok"] = False
			return out

	# Next: optional sample arrays, when present and mismatching.
	for prefix in stage_order:
		sample_key = f"{prefix}_sample_f32"
		if any(isinstance(m, dict) and m.get("key") == sample_key for m in mismatches):
			out["first_mismatch"] = {"kind": "sample", "prefix": prefix, "key": sample_key}
			stats = _sample_stats(a.get(sample_key, None), b.get(sample_key, None))
			if stats is not None:
				out["first_mismatch"]["sample_stats"] = stats
			out["ok"] = False
			return out

	# Otherwise, walk the capture stages in order and find the first divergence.
	for prefix in stage_order:
		a_fnv, a_nbytes, a_shape = _capture_tuple(a, prefix)
		b_fnv, b_nbytes, b_shape = _capture_tuple(b, prefix)

		if a_fnv is None and b_fnv is None and a_nbytes is None and b_nbytes is None and a_shape is None and b_shape is None:
			continue

		if (a_fnv, a_nbytes, a_shape) != (b_fnv, b_nbytes, b_shape):
			out["first_mismatch"] = {
				"kind": "capture",
				"prefix": prefix,
				"a": {"fnv64": a_fnv, "nbytes": a_nbytes, "shape": a_shape},
				"b": {"fnv64": b_fnv, "nbytes": b_nbytes, "shape": b_shape},
			}
			sample_key = f"{prefix}_sample_f32"
			stats = _sample_stats(a.get(sample_key, None), b.get(sample_key, None))
			if stats is not None:
				out["first_mismatch"]["sample_stats"] = stats
			out["ok"] = False
			return out

	# Fall back: mismatch exists but doesn't map to our stage list.
	out["first_mismatch"] = {"kind": "unknown"}
	out["ok"] = False
	return out


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--a", required=True, help="Probe JSON A (oracle).")
	ap.add_argument("--b", required=True, help="Probe JSON B (candidate).")
	ap.add_argument(
		"--stage",
		action="append",
		default=[],
		help="Capture prefix order (repeatable). Defaults to a recommended set when omitted.",
	)
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	args = ap.parse_args(argv)

	a = _load_json(Path(args.a))
	b = _load_json(Path(args.b))
	stage_order = list(args.stage) if args.stage else list(DEFAULT_STAGE_ORDER)
	res = summarize_one_token_mtp_probe_diff(
		a if isinstance(a, dict) else {},
		b if isinstance(b, dict) else {},
		stage_order=stage_order,
	)

	if args.json:
		print(json.dumps(res, indent=2, sort_keys=True))
		return 0 if res.get("ok", False) else 1

	if res.get("ok", False):
		print("ok: probes match")
		return 0
	first = res.get("first_mismatch")
	if isinstance(first, dict) and first.get("kind") == "token":
		print(f"mismatch: token key={first.get('key')}")
		return 1
	if isinstance(first, dict) and first.get("kind") == "capture":
		print(f"mismatch: capture prefix={first.get('prefix')}")
		return 1
	print("mismatch: unknown (see --json)")
	return 1


if __name__ == "__main__":
	sys.exit(main())
