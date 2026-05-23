#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ds4_mtp_cli import main
from scripts._lib.mtp_builders.k2_production_benchmark import build_artifact


if __name__ == "__main__":
	raise SystemExit(main(["k2-production", *sys.argv[1:]]))
