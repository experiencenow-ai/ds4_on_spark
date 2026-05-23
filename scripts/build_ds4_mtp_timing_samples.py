#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ds4_mtp_cli import main
from scripts._lib.mtp_builders.timing_samples import build_report


if __name__ == "__main__":
	raise SystemExit(main(["timing-samples", *sys.argv[1:]]))
