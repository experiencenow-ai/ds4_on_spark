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
