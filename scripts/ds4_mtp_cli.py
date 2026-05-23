#!/usr/bin/env python3
"""Unified entrypoint for DS4 MTP artifact builders."""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


MODULE_BY_COMMAND = {
	"integrity": "scripts._lib.mtp_builders.benchmark_integrity",
	"k2-production": "scripts._lib.mtp_builders.k2_production_benchmark",
	"k-sweep": "scripts._lib.mtp_builders.k_sweep",
	"slowpath-report": "scripts._lib.mtp_builders.slowpath_report",
	"timing-samples": "scripts._lib.mtp_builders.timing_samples",
	"timing-summary": "scripts._lib.mtp_builders.timing_samples_summary",
	"verifier-economics": "scripts._lib.mtp_builders.verifier_economics",
}


def main(argv: list[str] | None = None) -> int:
	args = list(sys.argv[1:] if argv is None else argv)
	if not args or args[0] in {"-h", "--help"}:
		print("usage: ds4_mtp_cli.py <command> [args...]", file=sys.stderr)
		print("commands: " + ", ".join(sorted(MODULE_BY_COMMAND)), file=sys.stderr)
		return 0 if args else 2
	command = args.pop(0)
	module = MODULE_BY_COMMAND.get(command)
	if module is None:
		print(f"unknown command: {command}", file=sys.stderr)
		print("commands: " + ", ".join(sorted(MODULE_BY_COMMAND)), file=sys.stderr)
		return 2
	builder = importlib.import_module(module)
	main_func = getattr(builder, "main")
	if len(inspect.signature(main_func).parameters) == 0:
		old_argv = sys.argv
		try:
			sys.argv = [command] + args
			return int(main_func())
		finally:
			sys.argv = old_argv
	return int(main_func(args))


if __name__ == "__main__":
	raise SystemExit(main())
