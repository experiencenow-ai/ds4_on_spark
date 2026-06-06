# DS4 Pipeline Lifecycle

All resident pipeline tests must use the same repo-owned lifecycle runner. Do
not keep separate thread-local commands for Qwen, DSV4, and Gemma. The service
id is the parameter; the process is shared.

```bash
cd ~/src/ds4_on_spark/v2
python3 scripts/ds4_pipeline_lifecycle.py --service gemma4_12b_pp8 relaunch
python3 scripts/ds4_pipeline_lifecycle.py --service gemma4_12b_pp8 relaunch --execute
```

Without `--execute`, side-effecting actions print the plan only. With
`--execute`, `relaunch` expands to:

```text
pull -> stop -> write-scripts -> launch -> probe
```

The runner reads:

```text
profiles/topology/static_sparks.json
profiles/models/*.json
profiles/kv_cache/*.json
```

That gives every pipeline the same topology, service id, model profile, KV
deployment, node order, port, kill match, launch script generation, and probe
path.

## Standard actions

List configured resident services:

```bash
python3 scripts/ds4_pipeline_lifecycle.py list
```

Check local profile/topology/deployment consistency:

```bash
python3 scripts/ds4_pipeline_lifecycle.py audit
```

Inspect live vLLM processes for one service:

```bash
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 status
```

Run the standard pull-only Spark sync:

```bash
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 pull --execute
```

Stop only the selected service's matching vLLM processes:

```bash
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 stop --execute
```

Generate launch scripts from the selected service's KV deployment on every
rank node:

```bash
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 write-scripts --execute
```

Launch the selected service's non-entry ranks first, then the spark0 entry
rank:

```bash
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 launch --execute
```

Probe the selected service from its topology entry node:

```bash
python3 scripts/ds4_pipeline_lifecycle.py --service qwen27_bf16_pp8 probe
```

## Blocked old paths

The old spark4/spark5 DSV4 launchers are disabled and exit with an error:

```text
scripts/ds4_dsv4_spark45_local_vllm.sh
scripts/ds4_dsv4_recipe_spark45.sh
```

The fleet updater refuses `--runtime-config`, `--restart-dsv4`,
`DS4_UPDATE_MODE=runtime-config`, `DS4_INSTALL_DSV4_LOCAL=1`, and
`DS4_RESTART_DSV4=1`. `scripts/ds4_update_spark_nodes.sh --code-only` remains
valid because the lifecycle runner uses it for the pull step.

Direct `ds4_kvcache.cli write-scripts` is also blocked for resident topology
pipeline deployments unless it is called by `ds4_pipeline_lifecycle.py`.
Read-only `plan` remains available.

## Branch discipline

Model-family branches may move independently:

```text
codex/qwen27-pp8-bringup
codex/dsv4-pp8-quality
codex/gemma4-pp8-bringup
```

General fixes belong in the shared lifecycle/topology/coordinator path first.
After those fixes merge to `main`, every model-family branch rebases or merges
`main` and uses the same lifecycle runner again. That keeps discoveries from
one pipeline visible to the others without copying fixes between ad-hoc shell
snippets.

## Promotion boundary

The lifecycle runner standardizes mechanics; it does not make an experimental
pipeline production eligible. Promotion still requires the model profile to
become `production_eligible=true` and pass the DS4 API, queue, throughput,
quality, and trim/reset gates documented for that model family.
