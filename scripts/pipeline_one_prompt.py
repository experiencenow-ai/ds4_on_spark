#!/usr/bin/env python3
"""Run one real prompt through the DS4 PP=3 pipeline session path."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from scripts.pipeline_session import PipelineSession, PipelineSessionError


def print_record(label: str, obj: object) -> None:
	if dataclasses.is_dataclass(obj):
		payload = dataclasses.asdict(obj)
	else:
		payload = obj
	print(f"=== {label} ===")
	print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str]) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--prompt", required=True)
	ap.add_argument("--max-tokens", type=int, default=8)
	ap.add_argument("--out-dir", default=f"/private/tmp/ds4_lane_a_one_prompt_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
	ap.add_argument("--mode", choices=["pp3", "pp1", "all"], default="all")
	ap.add_argument("--continue-after-pp3-blocker", action="store_true", help="Also run PP=1 baseline when PP=3 worker hook is blocked.")
	args = ap.parse_args(argv)
	session = PipelineSession()
	out_dir = Path(args.out_dir)
	out_dir.mkdir(parents=True, exist_ok=True)
	rc = 0
	pp3_ids: list[int] = []
	if args.mode in ("pp3", "all"):
		try:
			pp3 = session.run_pp3(args.prompt, args.max_tokens, out_dir / "pp3")
			pp3_ids = pp3.generated_token_ids
			print_record("pp3", pp3)
			print(f"PP3_TOKEN_IDS={pp3.generated_token_ids}")
			print(f"PP3_TEXT={pp3.generated_text!r}")
		except PipelineSessionError as e:
			blocked = {
				"blocker_kind": "pp3_pipeline_session_failed",
				"blocker_detail": str(e),
				"out_dir": str(out_dir),
			}
			(out_dir / "pp3_blocker.json").write_text(json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8")
			print_record("pp3_blocked", blocked)
			rc = 2
			if args.mode == "pp3" or not args.continue_after_pp3_blocker:
				return rc
	if args.mode in ("pp1", "all"):
		try:
			pp1 = session.run_pp1_baseline(args.prompt, args.max_tokens, out_dir / "pp1")
			print_record("pp1", pp1)
			print(f"PP1_TOKEN_IDS={pp1.generated_token_ids}")
			print(f"PP1_TEXT={pp1.generated_text!r}")
			if pp3_ids and pp3_ids[:args.max_tokens] != pp1.generated_token_ids[:args.max_tokens]:
				print("PP_COMPARE=fail", file=sys.stderr)
				return 3
			if pp3_ids:
				print("PP_COMPARE=identical_first_tokens")
		except PipelineSessionError as e:
			print_record("pp1_failed", {"blocker_kind": "pp1_failed", "blocker_detail": str(e)})
			return 2
	return rc


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))
