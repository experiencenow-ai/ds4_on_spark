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
  python3 v2/scripts/score_repo_complexity.py gate-pr \
  --root "$PWD" \
  --base-ref origin/main \
  --output /tmp/ds4_complexity_gate.json

python3 v2/scripts/render_complexity_cost.py \
  /tmp/ds4_complexity_gate.json \
  --output /tmp/ds4_complexity_cost.md

PYTHONPATH=/private/tmp/centaur-v2-main-latest \
  python3 -m v2.audit.repo_code_rot \
  --root "$PWD" \
  --include-dir v2/src \
  --include-dir v2/scripts \
  --docs-dir v2/docs
```

`gate-pr` compares the current checkout against the requested base ref, so a
PR is charged only for the complexity delta it introduces. It skips
`v2/tests/**`, reports total score and repeated-block deltas as context, and
gates only on shape regressions such as oversized functions/files and new
over-50-line functions. The static baseline gate remains available as
`gate-baseline` for explicit baseline maintenance, but CI uses base-ref
comparisons for both PRs and pushes. `gate` is a safe alias for `gate-pr`.
The gate JSON includes a `cost` block, and CI renders that cost into both the
job summary and an upserted PR comment.

`v2/scripts/run_centaur_audit.sh` runs the PR-delta complexity gate, code-rot
gate, and the v2 unit tests for local smoke coverage. Override
`COMPLEXITY_BASE_REF` when the target branch is not `origin/main`.

## CI command

`.github/workflows/centaur-audit.yml` checks out `experiencenow-ai/centaur`
into `.centaur-audit` and runs:

```bash
CENTAUR_REPO="$PWD/.centaur-audit" python3 v2/scripts/score_repo_complexity.py gate-pr --root "$PWD" --base-ref "$BASE_SHA_OR_BEFORE_SHA" --output .centaur-complexity-gate.json
python3 v2/scripts/render_complexity_cost.py .centaur-complexity-gate.json --output .centaur-complexity-cost.md
PYTHONPATH="$PWD/.centaur-audit" python3 -m v2.audit.repo_code_rot --root "$PWD" --include-dir v2/src --include-dir v2/scripts --docs-dir v2/docs
PYTHONPATH="$PWD/v2/src" python3 -m unittest discover -s v2/tests -v
```

That is the minimal duplicate surface: DS4 has a target profile and baselines;
Centaur remains the source of truth for scoring.

## Clean xhigh workspaces

Do not rebase or rewrite shared `main` to clean up local agent trees. Dirty
trees are local state, not a property of `main`. Give each xhigh a fresh
worktree from the current base instead:

```bash
python3 v2/scripts/xhigh_clean_workspace.py --name xhigh7 --fetch
```

The helper creates `/private/tmp/ds4_xhigh_workspaces/xhigh7` from
`origin/main` without touching the current checkout. If an existing xhigh
worktree is dirty, it fails closed and tells the operator to choose a new name
or clean that specific workspace.
