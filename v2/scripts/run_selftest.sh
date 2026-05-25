#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
