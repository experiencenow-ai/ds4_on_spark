#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m ds4_infer.sparkrunner_adapter "$@"
