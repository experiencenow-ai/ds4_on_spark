from __future__ import annotations
import argparse
import json
import sys
from ds4_tools.registry import ToolRegistry
from .loop import FakeChatModel, run_agent_loop

def _load_jsonl(path: str) -> list[dict]:
    values: list[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                values.append(json.loads(stripped))
    return values

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_fake = sub.add_parser("run-fake")
    run_fake.add_argument("--registry", required=True)
    run_fake.add_argument("--responses", required=True)
    run_fake.add_argument("--max-tool-rounds", type=int, default=6)
    args = parser.parse_args(argv)
    if args.cmd == "run-fake":
        result = run_agent_loop(model=FakeChatModel(_load_jsonl(args.responses)), registry=ToolRegistry.load(args.registry), max_tool_rounds=args.max_tool_rounds)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)
if __name__ == "__main__":
    sys.exit(main())
