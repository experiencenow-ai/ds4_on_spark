# Zero-Drift Deployment

Deployment and benchmark tests must use code that has reached `main`.

The required path is:

```text
local fix -> local validation -> PR -> merge to main -> Spark git pull -> rebuild/install -> restart -> API test
```

Do not validate deployment behavior from:

```text
dirty Spark checkouts
local Mac files copied over SSH or scp
unmerged branches
downloaded zip snapshots
manual one-off edits on Spark nodes
raw model ports when the test is about DS4 queue/API behavior
```

Engine-only diagnostics may use the model port directly, but deployment,
queueing, KV-cache, and benchmark claims must go through the spark0 coordinator
API after the corresponding DS4 and vLLM changes have been merged and pulled.

Before any Spark test, sync and verify the canonical checkouts:

```bash
scripts/spark_sync_standard_repos.sh
```

For DS4-only deployment updates:

```bash
scripts/ds4_pull_spark_nodes.sh
```

That command only pulls `origin/main` on reachable Spark checkouts. It does not
rewrite runtime env, install systemd units, or restart services. Legacy
runtime-config and spark4/spark5 DSV4 restart modes are disabled; resident
pipeline side effects go through the lifecycle runner below.

Those scripts require the remote repos to be on `main` and clean. They should
fail rather than hide drift.

## GitHub PR workflow

Use the repo-owned PR helper instead of typing raw `gh pr create/checks/merge`
commands:

```bash
scripts/ds4_github_pr.py create --title "Short PR title" --body-file /tmp/pr-body.md
scripts/ds4_github_pr.py checks
scripts/ds4_github_pr.py merge
```

For the full standard path from a feature branch:

```bash
scripts/ds4_github_pr.py ship --title "Short PR title" --body-file /tmp/pr-body.md
```

The helper pushes the current branch first, creates the PR with an explicit
`--head`, waits for checks to pass, and only then merges. This avoids GitHub CLI
guesswork such as creating a PR before the branch has an upstream or relying on
`gh` to infer the head branch.

The default merge method is a normal merge commit so branch-level commit history
lands on `main`. Pass `--method squash` only when flattening a tiny branch is
intentional.

## Pipeline lifecycle

For resident Qwen, DSV4, and Gemma pipeline tests, use the shared lifecycle
runner instead of hand-written thread-local SSH commands:

```bash
cd ~/src/ds4_on_spark/v2
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 relaunch
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 relaunch --execute
```

The dry run prints the standard action sequence. The executed relaunch uses the
same script path for every pipeline:

```text
pull -> stop -> write-scripts -> launch -> probe
```

General fixes to topology, launch, stop, probe, or coordinator defaults belong
in the lifecycle/coordinator code first, then each model-specific branch pulls
or rebases onto `main`.

## Spark0 coordinator relaunch

On spark0, use the repo-owned relaunch script instead of ad-hoc `pkill -f`
commands:

```bash
cd ~/src/ds4_on_spark/v2
python3 scripts/ds4_relaunch_coordinator_api.py --profile resident128
```

The relaunch script:

```text
git pull --ff-only origin main
make if a Makefile exists, otherwise compile and run focused coordinator tests
stop the old coordinator with exact PID discovery
start the coordinator with the current dispatcher/cohort defaults
verify /ds4/dispatcher/status
```

The stop script never kills by matching a shell command string. It scans `ps`,
selects only the actual coordinator command (`python -m ds4_infer.api` or the
repo launcher), adds descendants, sends SIGTERM, and force-kills only the
surviving exact PIDs.
