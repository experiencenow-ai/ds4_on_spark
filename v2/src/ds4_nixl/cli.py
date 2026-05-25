from __future__ import annotations

import argparse
import json
import sys

from .service import NixlDeployment, plan_deployment, write_launch_scripts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-nixl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--deployment", required=True)

    write_scripts = sub.add_parser("write-scripts")
    write_scripts.add_argument("--deployment", required=True)
    write_scripts.add_argument("--output-dir", required=True)

    args = parser.parse_args(argv)

    deployment = NixlDeployment.load(args.deployment)
    if args.cmd == "plan":
        print(json.dumps(plan_deployment(deployment), indent=2, sort_keys=True))
        return 0
    if args.cmd == "write-scripts":
        print(json.dumps(write_launch_scripts(deployment, args.output_dir), indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    sys.exit(main())
