from __future__ import annotations

import argparse
import json

from .service import Dsv4HmaDeployment, plan_deployment, write_launch_scripts
from .state_package import HmaPersistentStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-hma")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--deployment", required=True)

    write_scripts = sub.add_parser("write-scripts")
    write_scripts.add_argument("--deployment", required=True)
    write_scripts.add_argument("--output-dir", required=True)

    inspect_store = sub.add_parser("inspect-store")
    inspect_store.add_argument("--store-root", required=True)

    args = parser.parse_args(argv)
    if args.cmd == "plan":
        deployment = Dsv4HmaDeployment.load(args.deployment)
        print(json.dumps(plan_deployment(deployment), indent=2, sort_keys=True))
        return 0
    if args.cmd == "write-scripts":
        deployment = Dsv4HmaDeployment.load(args.deployment)
        print(json.dumps(write_launch_scripts(deployment, args.output_dir), indent=2, sort_keys=True))
        return 0
    if args.cmd == "inspect-store":
        store = HmaPersistentStore(args.store_root)
        print(store.index_path.read_text(encoding="utf-8"), end="")
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
