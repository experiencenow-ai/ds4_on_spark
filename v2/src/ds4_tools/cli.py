from __future__ import annotations
import argparse
import json
import sys
from .registry import ToolRegistry

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    search = sub.add_parser("search")
    search.add_argument("--registry", required=True)
    search.add_argument("--query", default="")
    search.add_argument("--limit", type=int, default=10)
    describe = sub.add_parser("describe")
    describe.add_argument("--registry", required=True)
    describe.add_argument("--tool-id", required=True)
    invoke = sub.add_parser("invoke")
    invoke.add_argument("--registry", required=True)
    invoke.add_argument("--tool-id", required=True)
    invoke.add_argument("--arguments", required=True)
    args = parser.parse_args(argv)
    registry = ToolRegistry.load(args.registry)
    if args.cmd == "search":
        print(json.dumps(registry.search(args.query, limit=args.limit), indent=2, sort_keys=True)); return 0
    if args.cmd == "describe":
        print(json.dumps(registry.describe(args.tool_id), indent=2, sort_keys=True)); return 0
    if args.cmd == "invoke":
        print(json.dumps(registry.invoke(args.tool_id, json.loads(args.arguments)), indent=2, sort_keys=True)); return 0
    raise AssertionError(args.cmd)
if __name__ == "__main__":
    sys.exit(main())
