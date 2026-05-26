# Static Spark Topology

The production Spark pool is intentionally static. Centaur and DS4 services should not treat the eight Sparks as a model zoo that loads and unloads models per request.

## Allocation

| Spark | Role | Resident profiles |
|---|---|---|
| spark0 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark1 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark2 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark3 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark4 | DSV4 vLLM grouped lane half | `dsv4_vllm_mtp_smartest_v1` |
| spark5 | DSV4 vLLM grouped lane half | `dsv4_vllm_mtp_smartest_v1` |
| spark6 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark7 | Experimental on-demand lane | none |

This gives the service a normal production view of:

- 5 Qwen lanes for `efficient` / `fastest` work;
- 1 DSV4 vLLM grouped lane for `smartest` chat/tool/reasoning work, consuming both spark4 and spark5;
- 1 experimental on-demand lane on spark7.

No model is dynamically ejected from production Sparks. Spark6 is now a normal
Qwen resident lane. Spark7 is intentionally experimental and may lazy-load
models for probes without becoming a production resident lane.

KV-cache experiments should use `ds4_kvcache` deployment files. They do not add
resident profiles to the topology.

## DSV4 Launch Rule

The spark4+spark5 DSV4 lane must use the no-Ray dual-Spark recipe path. This is
not an interchangeable implementation detail. Each Spark has one GPU, and the
working MTP result was produced by vLLM's multi-node `mp` backend with explicit
node ranks, not by Ray placement groups.

Use the service wrapper:

```bash
systemctl --user start ds4-dsv4-vllm.service
```

The service launches:

```text
v2/scripts/ds4_dsv4_recipe_spark45.sh
  -> spark-vllm-docker PR 219
  -> v2/recipes/deepseek-v4-flash-spark45.yaml
  -> run-recipe.sh ... --no-ray --no-cache-dirs -d
```

The recipe runner must use the old working runtime lineage:

```text
spark-vllm-docker: https://github.com/eugr/spark-vllm-docker.git
runner ref:        refs/pull/219/head
runner commit:     7a3249e3b4826233972c147a4fe2c6f791227a0b
vLLM fork:         https://github.com/jasl/vllm.git
vLLM commit:       dda4668b59567416f86956cfe7bbc1eab371a61e
recipe source:     https://github.com/tonyd2wild/deepseek-v4-flash-dual-spark-recipe
recipe commit:     84387a446ae42ca1c98ca912c8136642043ea9c6
```

The working serving command shape is:

```text
TP=2, PP=1, EP enabled
MTP speculative decoding with 2 tokens
max_model_len=200000
max_num_seqs=2
max_num_batched_tokens=8192
block_size=256
fp8 KV cache
FULL_AND_PIECEWISE CUDA graphs
distributed_executor_backend=mp
node ranks: spark4 rank 0, spark5 rank 1 --headless
```

The measured working artifact reported:

```text
API endpoint:       http://10.20.0.14:8000/v1
served model name:  deepseek-v4-flash
API ready:          true
memory used:        75.76 GiB
engine init:        about 176s
MTP load:           about 24-27s per node
target load:        about 114-142s per node
single stream:      about 20.9 generated tok/s
concurrency 2:      about 38-43 aggregate generated tok/s
```

This is the known-good command from the benchmark artifact:

```bash
DOTENV_CONTAINER_NAME=vllm_deepseek_v4_flash \
  ./run-recipe.sh recipes/deepseek-v4-flash-local.yaml --no-ray --no-cache-dirs -d
```

Do not replace this with a Ray vLLM service unless a new benchmark proves the
Ray path reaches API readiness and matches the recipe-backed lane.

Do not "simplify" the DSV4 lane by disabling MTP. MTP was present in the
working config. If a future smoke test needs a smaller shape, record it as a
temporary diagnostic profile, not as the production DSV4 lane.

Latest recovery status after the bad Ray launch attempt:

```text
checked_at: 2026-05-26 14:28 KST
spark4: rebooted, up 8 minutes, GPU clear
spark4 ds4-dsv4-vllm.service: installed, enabled, inactive
spark4 ds4-dsv4-ray-head.service: disabled, inactive
spark5: GPU clear
spark5 ds4-dsv4-ray-worker.service: disabled, inactive
spark4 local port 8000: closed because DSV4 is not currently running
```

This means the cluster is clean for a recipe-backed DSV4 start, and the broken
Ray DSV4 services are no longer part of the startup path.

## Policy

The inference scheduler owns node assignment. Centaur requests a capability and job class; it does not target a Spark directly.

Normal queued requests prefer resident production lanes. Efficient Qwen requests
therefore spread across spark0-3 and spark6. `smart`/`smartest` DSV4 requests
use the spark4+spark5 grouped vLLM lane unless explicitly pinned to a legacy
non-production profile. Dynamic loading is allowed only for unmatched
experimental requests routed to spark7, not for production model ejection.

Qwen capacity planning uses aggregate batched decode. Single-stream Qwen27
decode is about 8 generated tok/s on this Spark shape, while 16-32 running
sequences recover roughly 100-187 generated tok/s aggregate per Spark. Keep
batch workers deep enough to feed vLLM continuous batching before judging lane
throughput.

The topology is stored in:

```text
profiles/topology/static_sparks.json
```

## Startup Warmup

Each production Spark should run the same startup command after reboot:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli startup-models \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --node-id spark0
```

The command reads this topology and warms only that node's resident profiles.
Spark0-3 and spark6 warm both Qwen profiles, spark4 warms the deployed grouped
DSV4 vLLM lane, spark5 records itself as the secondary half of that group, and
spark7 is a clean no-op because it is on demand. Production lanes use the
default `127.0.0.1:8000` gateway.

The user service template is in:

```text
v2/deploy/systemd-user/ds4-startup-models.service
```

Inspect capacity:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli topology \
  --topology profiles/topology/static_sparks.json \
  --capacity
```

Submit a request batch through the topology planner:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests requests.jsonl \
  --batch-id topology-smoke
```

Queue submission records selected nodes. Individual responses include the selected node assignment. The DSV4 vLLM profile appears as `spark4+spark5` with `node_ids=["spark4", "spark5"]`. The Spark runner now fails closed when a live model call has no selected node.

## Why this exists

The earlier approach made every local LLM attempt an experiment. Batch size, thinking budget, backend, and model loading decisions leaked into Centaur. Static residency turns Spark inference into a service boundary: production lanes are boring and measurable, and the scheduler does not unload resident models for lopsided short-term usage.
