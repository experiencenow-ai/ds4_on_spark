#!/usr/bin/env python3
"""Compare one-token MTP HC fingerprints with layout-normalized candidates.

This helps triage "oracle vs candidate" mismatches where the only difference is
the HC tensor memory layout (for example [4096,4] vs [4,4096]).

Expected usage:
- A is the oracle (e.g. antirez/ds4) emitting `{prefix}_fnv64`.
- B is the candidate (e.g. llama.cpp) emitting both `{prefix}_fnv64` and an
  optional `{prefix}_hc_major_fnv64` where the HC bytes are re-ordered to match
  the oracle's expected major layout before hashing.
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


HC_PREFIXES = [
	"trunk_pre_hc_head",
	"mtp_input_hc",
	"mtp_block_out_hc",
]
VECTOR_PREFIXES = [
	"trunk_token_embd",
	"mtp_head_norm",
]
STAT_SUFFIXES = [
	"f32_count",
	"f32_sum",
	"f32_l2",
	"f32_absmax",
	"f32_min",
	"f32_max",
]


def _load_json(path: Path) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as f:
		obj = json.load(f)
	if not isinstance(obj, dict):
		raise SystemExit(f"{path}: top-level JSON is not an object")
	return obj


def _get(obj: dict[str, Any], key: str) -> Any:
	return obj.get(key, None)


def _stat_delta(a: Any, b: Any) -> Optional[float]:
	if isinstance(a, (int, float)) and isinstance(b, (int, float)):
		return float(b) - float(a)
	return None


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
	rows: list[dict[str, Any]] = []
	for prefix in VECTOR_PREFIXES:
		raw_a = _get(a, f"{prefix}_fnv64")
		raw_b = _get(b, f"{prefix}_fnv64")
		rows.append(
			{
				"prefix": prefix,
				"kind": "vector_raw",
				"a_raw_fnv64": raw_a,
				"b_raw_fnv64": raw_b,
				"raw_match": raw_a is not None and raw_a == raw_b,
				"a_shape": _get(a, f"{prefix}_shape"),
				"b_shape": _get(b, f"{prefix}_shape"),
			}
		)

	for prefix in HC_PREFIXES:
		raw_a = _get(a, f"{prefix}_fnv64")
		raw_b = _get(b, f"{prefix}_fnv64")
		hc_b = _get(b, f"{prefix}_hc_major_fnv64")
		row: dict[str, Any] = {
			"prefix": prefix,
			"kind": "hc",
			"a_raw_fnv64": raw_a,
			"b_raw_fnv64": raw_b,
			"b_hc_major_fnv64": hc_b,
			"raw_match": raw_a is not None and raw_a == raw_b,
			"hc_major_match": raw_a is not None and raw_a == hc_b,
			"a_shape": _get(a, f"{prefix}_shape"),
			"b_shape": _get(b, f"{prefix}_shape"),
			"b_hc_major_shape": _get(b, f"{prefix}_hc_major_shape"),
		}

		stats: dict[str, Any] = {}
		for suffix in STAT_SUFFIXES:
			av = _get(a, f"{prefix}_{suffix}")
			bv = _get(b, f"{prefix}_{suffix}")
			if av is not None or bv is not None:
				stats[suffix] = {"a": av, "b": bv, "delta_b_minus_a": _stat_delta(av, bv)}
		if stats:
			row["stats"] = stats
		rows.append(row)

	ok_layout = all(bool(r.get("hc_major_match", False)) for r in rows if r.get("kind") == "hc" and r.get("a_raw_fnv64") is not None)
	ok_raw_vectors = all(bool(r.get("raw_match", False)) for r in rows if r.get("kind") == "vector_raw" and r.get("prefix") == "trunk_token_embd")

	return {
		"ok": bool(ok_layout and ok_raw_vectors),
		"layout_matches_all_hc": bool(ok_layout),
		"trunk_token_embd_raw_match": bool(ok_raw_vectors),
		"rows": rows,
		"notes": [
			"a is normally antirez/ds4 oracle; b is normally llama.cpp candidate",
			"hc_major_match compares a raw HC fingerprint against b's layout-normalized fingerprint",
		],
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--a", required=True, help="Probe JSON A, usually antirez oracle.")
	ap.add_argument("--b", required=True, help="Probe JSON B, usually llama.cpp candidate.")
	ap.add_argument("--json", action="store_true", help="Emit JSON.")
	args = ap.parse_args(argv)

	result = compare(_load_json(Path(args.a)), _load_json(Path(args.b)))
	if args.json:
		print(json.dumps(result, indent=2, sort_keys=True))
	else:
		print(
			f"ok={str(result['ok']).lower()} layout_matches_all_hc={str(result['layout_matches_all_hc']).lower()} trunk_token_embd_raw_match={str(result['trunk_token_embd_raw_match']).lower()}"
		)
		for row in result["rows"]:
			if row["kind"] == "hc":
				print(f"{row['prefix']}: raw_match={row['raw_match']} hc_major_match={row['hc_major_match']}")
			else:
				print(f"{row['prefix']}: raw_match={row['raw_match']}")

	return 0 if result["ok"] else 1


if __name__ == "__main__":
	sys.exit(main())

