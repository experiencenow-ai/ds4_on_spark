# Audit handoff

Centaur should own the audit engine. DS4 should own only the target-specific
inputs needed to audit this repository.

## DRY split

Keep in Centaur:

- Complexity scoring implementation.
- Code-rot and similarity audit implementations.
- Generic audit tests and promotion logic.
- Diamond quality checks and archive/promotion semantics.

Keep in ds4_on_spark:

- `.complexity-baseline.json`
- `.audit-baseline.json`
- DS4 model-contract fixtures under `fixtures/model_contract/`
- A tiny wrapper that imports Centaur and points it at this repo.
- CI glue that checks out Centaur and runs the wrapper.

This avoids forking audit rules while keeping DS4 changes gated locally. DS4's
complexity wrapper is `v2/scripts/score_repo_complexity.py`; it imports the
Centaur engine from `CENTAUR_REPO` and keeps only DS4 include patterns and
baseline comparison policy here. The code-rot gate is Centaur's
`v2.audit.repo_code_rot` module, called with DS4 include paths.

## Local command

```bash
CENTAUR_REPO=/private/tmp/centaur-v2-main-latest \
  python3 v2/scripts/score_repo_complexity.py gate --root "$PWD"

PYTHONPATH=/private/tmp/centaur-v2-main-latest \
  python3 -m v2.audit.repo_code_rot \
  --root "$PWD" \
  --include-dir v2/src \
  --include-dir v2/scripts \
  --include-dir v2/tests \
  --docs-dir v2/docs
```

`v2/scripts/run_centaur_audit.sh` runs the complexity gate and the v2 unit
tests for local smoke coverage.

## CI command

`.github/workflows/centaur-audit.yml` checks out `experiencenow-ai/centaur`
into `.centaur-audit` and runs:

```bash
CENTAUR_REPO="$PWD/.centaur-audit" python3 v2/scripts/score_repo_complexity.py gate --root "$PWD"
PYTHONPATH="$PWD/.centaur-audit" python3 -m v2.audit.repo_code_rot --root "$PWD" --include-dir v2/src --include-dir v2/scripts --include-dir v2/tests --docs-dir v2/docs
PYTHONPATH="$PWD/v2/src" python3 -m unittest discover -s v2/tests -v
```

That is the minimal duplicate surface: DS4 has a target profile and baselines;
Centaur remains the source of truth for scoring.
