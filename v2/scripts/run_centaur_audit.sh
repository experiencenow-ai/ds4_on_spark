#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${CENTAUR_REPO:=/private/tmp/centaur-v2-main-latest}"
: "${COMPLEXITY_BASE_REF:=origin/main}"
: "${COMPLEXITY_GATE_OUTPUT:=/tmp/ds4_complexity_gate.json}"
: "${COMPLEXITY_COST_OUTPUT:=/tmp/ds4_complexity_cost.md}"
export CENTAUR_REPO

python3 "$ROOT/v2/scripts/score_repo_complexity.py" gate-pr --root "$ROOT" --base-ref "$COMPLEXITY_BASE_REF" --output "$COMPLEXITY_GATE_OUTPUT"
python3 "$ROOT/v2/scripts/render_complexity_cost.py" "$COMPLEXITY_GATE_OUTPUT" --output "$COMPLEXITY_COST_OUTPUT"
PYTHONPATH="$CENTAUR_REPO" python3 -m v2.audit.repo_code_rot \
  --root "$ROOT" \
  --include-dir v2/src \
  --include-dir v2/scripts \
  --docs-dir v2/docs
PYTHONPATH="$ROOT/v2/src" python3 -m unittest discover -s "$ROOT/v2/tests" -v
