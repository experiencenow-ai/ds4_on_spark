#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${CENTAUR_REPO:=/private/tmp/centaur-v2-main-latest}"
export CENTAUR_REPO

python3 "$ROOT/v2/scripts/score_repo_complexity.py" gate --root "$ROOT"
PYTHONPATH="$CENTAUR_REPO" python3 -m v2.audit.repo_code_rot \
  --root "$ROOT" \
  --include-dir v2/src \
  --include-dir v2/scripts \
  --include-dir v2/tests \
  --docs-dir v2/docs
PYTHONPATH="$ROOT/v2/src" python3 -m unittest discover -s "$ROOT/v2/tests" -v
