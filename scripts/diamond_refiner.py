#!/usr/bin/env python3
"""Run the DS4 diamond-refinement Phase-A loop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from diamond_refinement_domain import FORMAT
from diamond_refinement_domain import run_synthetic


def main() -> int:
    parser = argparse.ArgumentParser(description="Run diamond refinement candidates in a verifier sandbox.")
    parser.add_argument("--synthetic", action="store_true", help="Run the Phase-A synthetic coal-to-diamond example.")
    parser.add_argument("--output", type=Path, help="Write the JSON artifact to this path.")
    args = parser.parse_args()
    if not args.synthetic:
        parser.error("Phase A currently supports --synthetic only.")
    record = run_synthetic(args.output)
    if record.get("format") != FORMAT:
        raise RuntimeError("internal format mismatch")
    sys.stdout.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return 0 if record.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
