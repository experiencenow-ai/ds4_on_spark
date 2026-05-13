#!/usr/bin/env python3
"""Compare one-token probe captures under alternate HC-major layouts.

`scripts/diff_mtp_one_token_draft_probe.py` intentionally ignores keys ending in
`*_hc_major_fnv64` so that layout experiments can be analyzed separately without
breaking the primary oracle diff.

This helper answers: "Do these probes match if I compare A's canonical capture
against B's HC-major version (or vice versa)?"
"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


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
		prefix = k[: -len("_fnv64")]
		if prefix.endswith("_hc_major"):
			prefix = prefix[: -len("_hc_major")]
		if prefix:
			out.add(prefix)
	return out


def _cmp(out: dict[str, Any], a: dict[str, Any], b: dict[str, Any], *, prefix: str, a_key: str, b_key: str) -> None:
	ka = f"{prefix}{a_key}"
	kb = f"{prefix}{b_key}"
	va = a.get(ka, None)
	vb = b.get(kb, None)
	if va is None or vb is None:
		out["pairs"].append(
			{
				"prefix": prefix,
				"a_key": ka,
				"b_key": kb,
				"status": "missing",
				"a_present": (va is not None),
				"b_present": (vb is not None),
			}
		)
		return
	out["pairs"].append(
		{
			"prefix": prefix,
			"a_key": ka,
			"b_key": kb,
			"status": "match" if va == vb else "mismatch",
			"a_fnv64": va,
			"b_fnv64": vb,
		}
	)


def compare_hc_layout(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
	out: dict[str, Any] = {
		"ok": False,
		"errors": [],
		"pairs": [],
	}
	if not isinstance(a, dict) or not isinstance(b, dict):
		out["errors"].append("probe JSON must be objects")
		return out

	prefixes = sorted(_capture_prefixes(a) | _capture_prefixes(b))
	if not prefixes:
		out["errors"].append("no *_fnv64 captures found in either probe")
		return out

	for prefix in prefixes:
		_cmp(out, a, b, prefix=prefix, a_key="_fnv64", b_key="_fnv64")
		_cmp(out, a, b, prefix=prefix, a_key="_fnv64", b_key="_hc_major_fnv64")
		_cmp(out, a, b, prefix=prefix, a_key="_hc_major_fnv64", b_key="_fnv64")
		_cmp(out, a, b, prefix=prefix, a_key="_hc_major_fnv64", b_key="_hc_major_fnv64")

	out["ok"] = True
	return out


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--a", required=True, help="Probe JSON A.")
	ap.add_argument("--b", required=True, help="Probe JSON B.")
	ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
	args = ap.parse_args(argv)

	a = _load_json(Path(args.a))
	b = _load_json(Path(args.b))
	res = compare_hc_layout(a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {})

	if args.json:
		print(json.dumps(res, indent=2, sort_keys=True))
		return 0 if res.get("ok", False) else 1

	if not res.get("ok", False):
		for e in res.get("errors", [])[:64]:
			print(f"error: {e}")
		return 1

	print("ok: compared")
	return 0


if __name__ == "__main__":
	sys.exit(main())

