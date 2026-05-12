# Baseline: Git Shim For Worktree Checkouts

Some Codex-provided worktree checkouts can read from `.git`, but fail to write
into the per-worktree gitdir (for example `FETCH_HEAD`) due to filesystem
permissions. This shows up as errors like:

```text
error: cannot open .../.git/worktrees/<id>/FETCH_HEAD: Operation not permitted
```

The baseline/runtime scripts prefer `DS4_GIT_DIR` + `DS4_GIT_WORK_TREE` when
recording the repo revision, and automation loops often need `git fetch origin`.

This repo includes a helper that creates a **local writable** gitdir shim under
the checkout root: `.codex_git/`.

## Create the shim

From the repo root:

```sh
scripts/run_baseline_git_shim.sh
```

It copies the current worktree gitdir (referenced by the root `.git` file) into
`.codex_git/` and rewrites the `commondir` pointer to the shared object store.
The shim directory is ignored by git via `.gitignore`.

Optional override: if your checkout is already using an alternate gitdir (for
example `.codex_git_worktree`), set `SOURCE_GIT_DIR`:

```sh
SOURCE_GIT_DIR=.codex_git_worktree scripts/run_baseline_git_shim.sh
```

## Use the shim for git commands

```sh
git --git-dir=.codex_git --work-tree=. fetch origin
git --git-dir=.codex_git --work-tree=. checkout -b codex/loop-baseline-runtime-<suffix> origin/main
```

## Use the shim for baseline reports

Most baseline scripts record `ds4_on_spark commit` using `DS4_GIT_DIR` and
`DS4_GIT_WORK_TREE` when they are set. After creating the shim:

```sh
DS4_GIT_DIR=.codex_git DS4_GIT_WORK_TREE=. scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

This keeps the report’s commit hash stable even when the worktree `.git` path
is non-writable.
