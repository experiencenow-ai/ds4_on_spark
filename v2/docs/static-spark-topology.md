# Static Spark Topology

The production Spark pool is intentionally static. Centaur and DS4 services should not treat the eight Sparks as a model zoo that loads and unloads models per request.

## Allocation

| Spark | Role | Resident profiles |
|---|---|---|
| spark0 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark1 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark2 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark3 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1`, `qwen3_6_35b_a3b_fp8_fastest_v1` |
| spark4 | DSV4 vLLM/MTP grouped lane half | `dsv4_vllm_mtp_smartest_v1` |
| spark5 | DSV4 vLLM/MTP grouped lane half | `dsv4_vllm_mtp_smartest_v1` |
| spark6 | Antirez/support/urgent lane | `dsv4_antirez_smart_v1` |
| spark7 | Experiment lane | dynamic profiles only after explicit opt-in |

This gives the service a normal production view of:

- 4 Qwen lanes for `efficient` / `fastest` work;
- 1 DSV4 vLLM/MTP grouped lane for `smartest` chat/tool/reasoning work, consuming both spark4 and spark5;
- 1 antirez/support lane for `smart` completion and urgent support work;
- 1 experiment lane that may load/unload models without perturbing production lanes.

No Qwen profile is resident on spark6. Spark6 is reserved for antirez/support and does not have enough headroom for the Qwen resident pair.

## Policy

The inference scheduler owns node assignment. Centaur requests a capability and job class; it does not target a Spark directly.

Normal queued requests prefer resident production lanes. Immediate requests prefer a reserved lane only when that lane has the requested resident profile. Efficient Qwen requests therefore remain on spark0-3; smart antirez requests may use spark6. The experiment lane is not used for production routing unless `allow_dynamic_load_for_unmatched_profiles` is explicitly enabled in the topology file.

The topology is stored in:

```text
profiles/topology/static_sparks.json
```

Inspect capacity:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli topology \
  --topology profiles/topology/static_sparks.json \
  --capacity
```

Run a request batch through the topology planner:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli submit \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests requests.jsonl \
  --out /tmp/ds4_infer_run \
  --runner fake \
  --run
```

The batch manifest records `topology_id` and `selected_nodes`. Individual responses include the selected node assignment. The MTP profile appears as `spark4+spark5` with `node_ids=["spark4", "spark5"]`. This is a planning/contract layer; real network dispatch belongs in the runner implementation.

## Why this exists

The earlier approach made every local LLM attempt an experiment. Batch size, thinking budget, backend, and model loading decisions leaked into Centaur. Static residency turns Spark inference into a service boundary: production lanes are boring and measurable, while only spark7 performs model-loading experiments.
