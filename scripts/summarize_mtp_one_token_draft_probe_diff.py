#!/usr/bin/env python3
"""Summarize an oracle-vs-candidate one-token MTP draft probe diff.

This is a convenience wrapper around `scripts/diff_mtp_one_token_draft_probe.py`
that produces a stage-ordered summary so we can quickly identify the first
intermediate that diverges (useful when the draft token ID mismatches).
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from scripts import diff_mtp_one_token_draft_probe as diff  # noqa: E402


PIPELINE_ORDER = [
	"trunk_token_embd",
	"mtp_enorm",
	"mtp_eproj",
	"mtp_eproj_hc",
	"trunk_pre_hc_head",
	"mtp_hnorm_hc",
	"mtp_hproj_hc",
	"mtp_input_hc",
	"mtp_block_out_hc",
	"mtp_head_norm",
]


def _load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


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


def _stage_status(a: dict[str, Any], b: dict[str, Any], prefix: str) -> dict[str, Any]:
	fnv_key = f"{prefix}_fnv64"
	nbytes_key = f"{prefix}_nbytes"
	shape_key = f"{prefix}_shape"

	fa = a.get(fnv_key, None)
	fb = b.get(fnv_key, None)
	if fa is None and fb is None:
		return {"prefix": prefix, "status": "missing_both"}
	if fa is None:
		return {"prefix": prefix, "status": "missing_a"}
	if fb is None:
		return {"prefix": prefix, "status": "missing_b"}
	if fa == fb:
		return {
			"prefix": prefix,
			"status": "match",
			"fnv64": fa,
			"nbytes": a.get(nbytes_key, None),
			"shape": a.get(shape_key, None),
		}
	return {
		"prefix": prefix,
		"status": "mismatch",
		"a_fnv64": fa,
		"b_fnv64": fb,
		"a_nbytes": a.get(nbytes_key, None),
		"b_nbytes": b.get(nbytes_key, None),
		"a_shape": a.get(shape_key, None),
		"b_shape": b.get(shape_key, None),
	}


def summarize_one_token_diff(a: dict[str, Any], b: dict[str, Any], *, sample_tol: float) -> dict[str, Any]:
	base = diff.diff_one_token_mtp_probes(a, b, sample_tol=float(sample_tol))

	found = sorted(_capture_prefixes(a) | _capture_prefixes(b))
	if found:
		prefixes = [p for p in PIPELINE_ORDER if p in found] + [p for p in found if p not in PIPELINE_ORDER]
	else:
		prefixes = list(PIPELINE_ORDER)

	stages = [_stage_status(a, b, p) for p in prefixes]

	first_diverge: Optional[str] = None
	for s in stages:
		if s.get("status") not in ("match", "missing_both"):
			first_diverge = str(s.get("prefix"))
			break

	out = {
		"ok": bool(base.get("ok", False)),
		"first_diverge": first_diverge,
		"stages": stages,
		"diff": base,
	}
	return out


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--a", required=True, help="Probe JSON A (oracle).")
	ap.add_argument("--b", required=True, help="Probe JSON B (candidate).")
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	ap.add_argument("--sample-tol", type=float, default=1.0e-5, help="Max abs diff allowed for *_sample_f32 arrays.")
	args = ap.parse_args(argv)

	a = _load_json(Path(args.a))
	b = _load_json(Path(args.b))

	if not isinstance(a, dict) or not isinstance(b, dict):
		out = {"ok": False, "errors": ["probe JSON must be objects"]}
		if args.json:
			print(json.dumps(out, indent=2, sort_keys=True))
		else:
			print("error: probe JSON must be objects", file=sys.stderr)
		return 1

	out = summarize_one_token_diff(a, b, sample_tol=float(args.sample_tol))
	if args.json:
		print(json.dumps(out, indent=2, sort_keys=True))
		return 0 if out.get("ok", False) else 1

	ok = bool(out.get("ok", False))
	first = out.get("first_diverge", None)
	if first is not None:
		print(f"first_diverge: {first}")
	print(f"ok: {str(ok).lower()}")
	return 0 if ok else 1


if __name__ == "__main__":
	sys.exit(main())
