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
scripts/ds4_update_spark_nodes.sh
```

Those scripts require the remote repos to be on `main` and clean. They should
fail rather than hide drift.

## Spark0 coordinator relaunch

On spark0, use the repo-owned relaunch script instead of ad-hoc `pkill -f`
commands:

```bash
cd ~/src/ds4_on_spark/v2
python3 scripts/ds4_relaunch_coordinator_api.py --profile throughput
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
