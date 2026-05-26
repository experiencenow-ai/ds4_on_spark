from __future__ import annotations
import argparse
import sys
from .plan import build_calibration_plan, write_plan_jsonl

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-calibrate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--profile-id", required=True)
    plan.add_argument("--batch-sizes", default="1,2,4,8,16,32")
    plan.add_argument("--modes", default="completion,chat")
    args = parser.parse_args(argv)
    if args.cmd == "plan":
        batch_sizes = [int(item) for item in args.batch_sizes.split(",") if item]
        modes = [item for item in args.modes.split(",") if item]
        sys.stdout.write(write_plan_jsonl(build_calibration_plan(profile_id=args.profile_id, modes=modes, batch_sizes=batch_sizes)))
        return 0
    raise AssertionError(args.cmd)
if __name__ == "__main__":
    sys.exit(main())
