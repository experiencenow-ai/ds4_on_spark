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
