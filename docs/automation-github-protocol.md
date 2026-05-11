# Automation GitHub Protocol

All automated work must use pull requests. Direct pushes to `main` are
forbidden.

## Branch Ownership

Each automation owns one branch prefix:

- `codex/loop-spark-access-*`
- `codex/loop-upstream-intake-*`
- `codex/loop-model-contract-*`
- `codex/loop-cuda-probe-*`
- `codex/loop-mtp-cuda-*`
- `codex/loop-baseline-runtime-*`
- `codex/loop-build-skeleton-*`
- `codex/loop-entropy-buffer-*`
- `codex/loop-scheduler-sim-*`
- `codex/loop-ops-hardening-*`

Do not edit a branch owned by another automation unless explicitly asked in the
issue or PR thread.

## Start Of Each Loop

Use the checkout provided by the automation runner as the repository root. Do
not clone `experiencenow-ai/ds4_on_spark` inside that checkout. If the checkout
is detached, create the task branch in place from `origin/main`.

1. `git fetch origin`
2. If `main` exists locally, `git checkout main`
3. `git merge --ff-only origin/main` or create the task branch directly from
   `origin/main` if the checkout is detached
4. Create a fresh branch using the automation-owned prefix and a short suffix

If a previous PR from the same automation is still open, inspect it first. Push
follow-up commits to that same branch only when the new work is the same task.
Otherwise, leave the open PR alone and start a new branch.

If another run of the same automation appears to be active in the same branch
prefix, stop after leaving a short PR comment or status note. Do not create a
second clone to bypass the collision.

## Before Editing

- Read the relevant docs and scripts first.
- Check `git status --short`.
- Preserve unrelated user or automation changes.
- Keep each PR narrow enough to review and merge independently.

## Commit And PR Rules

- Commit only files changed by the current task.
- Use clear commit messages.
- Push the branch to `origin`.
- Open a PR against `main`.
- The PR body must include:
  - Summary
  - Verification commands
  - Spark commands run, when applicable
  - Known risks or blockers

## Merge Rules

The automation may merge its own PR only when all of these are true:

- The PR is not a draft.
- Local verification listed in the PR body has passed.
- GitHub reports the PR is mergeable or the branch is updated from `main`.
- There are no unresolved review comments.
- The change does not require a human secret, paid API decision, destructive
  operation, or hardware change.

Prefer squash merge:

```bash
gh pr merge <number> --squash --delete-branch
```

If merge fails, leave the PR open with a comment explaining the blocker.

## Forbidden Actions

- Do not push directly to `main`.
- Do not force-push another automation's branch.
- Do not rewrite public branch history after review comments unless the branch
  is owned by this automation and no other automation is building on it.
- Do not commit passwords, tokens, raw private keys, or unredacted secrets.
- Do not run destructive commands on Spark or the Mac without explicit approval.
