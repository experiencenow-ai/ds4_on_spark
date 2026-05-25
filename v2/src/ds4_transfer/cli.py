from __future__ import annotations

import argparse
import json
import sys

from .service import TransferRequest, TransferTopology, plan_transfer, run_transfer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-transfer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--topology", required=True)
    plan.add_argument("--request-json", required=True)

    run = sub.add_parser("run")
    run.add_argument("--topology", required=True)
    run.add_argument("--request-json", required=True)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--timeout-s", type=int, default=3600)

    args = parser.parse_args(argv)
    topology = TransferTopology.load(args.topology)
    request = TransferRequest.from_json(json.loads(args.request_json))
    if args.cmd == "plan":
        print(json.dumps(plan_transfer(topology, request), indent=2, sort_keys=True))
        return 0
    if args.cmd == "run":
        print(json.dumps(run_transfer(topology, request, dry_run=args.dry_run, timeout_s=args.timeout_s), indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    sys.exit(main())
