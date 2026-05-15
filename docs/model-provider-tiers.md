# Model Provider Tiers

The DS4 repo should advertise all local and external model engines through one
provider-profile shape. Centaur can then choose a tier without knowing whether a
provider is vLLM, SGLang, llama.cpp, DS4 custom CUDA, a Spark layer pipeline, or
an external frontier placeholder.

This file is metadata-only. It does not configure live endpoints, download
weights, handle API keys, or make throughput claims.

## Tier Vocabulary

| Tier | Meaning | Typical DS4 provider |
| --- | --- | --- |
| `deterministic` | Scripts, parsers, C helpers, benchmarks, validators | local tools |
| `local_small` | Cheap local classification, summary, cleanup, triage | Ling-mini-class, small Qwen-class |
| `local_coder` | Routine code patching, test interpretation, schema repair | Qwen3-Coder-class, Ling-flash-class |
| `near_frontier_local` | Heavy local reasoning and large batch judging | DS4 Spark pipeline |
| `frontier_api` | External review-board placeholder | no local runtime, no key in repo |

The tier is about routing policy. The runtime is a separate field.

## Provider Profile V1

Every profile fixture must use:

```json
{
  "format": "ds4-model-provider-profile-v1",
  "provider_id": "spark-ring-dsv4-layer-pipeline",
  "tier": "near_frontier_local",
  "model_id": "deepseek-ai/DeepSeek-V4-Flash",
  "runtime": "ds4_layer_pipeline",
  "endpoint": null,
  "node_ids": [],
  "provider_kind": "layer_pipeline",
  "supported_lanes": ["hard_reasoning", "batch_judge"],
  "preferred_batch_tokens": 65536,
  "minimum_batch_tokens": 8192,
  "maximum_wait_ms": 100,
  "measured_input_tps": null,
  "measured_output_tps": null,
  "quality_scores": {
    "coding": null,
    "reasoning": null,
    "tool_use": null
  },
  "last_probe_artifact": ""
}
```

Required profile fields:

- `provider_id`: stable ID for accounting and telemetry joins.
- `tier`: one of the shared tier vocabulary values above.
- `model_id`: upstream model ID or local runtime ID.
- `runtime`: one of `deterministic`, `vllm`, `sglang`, `llama_cpp`,
  `ds4_custom_runtime`, `ds4_layer_pipeline`, `simulator`, or `frontier_api`.
- `endpoint`: runtime-agnostic endpoint metadata, or `null` for manifest-bound
  providers.
- `node_ids`: zero or more deployment node IDs. Empty means the provider is
  resolved from an external deployment manifest.
- `provider_kind`: serving topology, for example `independent_lane`,
  `layer_pipeline`, `openai_compatible_endpoint`, `deterministic_tool`,
  `simulator`, or `external_placeholder`.
- `supported_lanes`: task lanes this provider is intended to handle.
- `preferred_batch_tokens`, `minimum_batch_tokens`, `maximum_wait_ms`: batching
  contract for admission and routing.
- `measured_input_tps`, `measured_output_tps`: numbers only when measured under
  the exact runtime; otherwise `null`.
- `quality_scores`: optional score buckets, using `null` until a local quality
  run or public-prior import has been recorded.
- `last_probe_artifact`: required whenever measured throughput is non-null.

## Fixtures

Example fixtures live under `fixtures/model_providers/`:

- `qwen_local_provider.example.json`
- `ling_local_provider.example.json`
- `dsv4_spark_pipeline_provider.example.json`
- `frontier_api_placeholder_provider.example.json`

They intentionally leave measured throughput and quality scores as `null`
unless a matching artifact exists. This avoids turning source/model-card claims
into local DS4 performance claims.

## Validation

Run:

```sh
python3 scripts/validate_model_provider_profiles.py
python3 scripts/validate_model_provider_profiles.py --json
```

Validation rejects:

- unknown tier/runtime/provider-kind values;
- missing batching fields;
- measured throughput without `last_probe_artifact`;
- secret-looking endpoint fields;
- fixed Spark-count fields such as `spark_count`, `num_sparks`, or
  `world_size`.

## Centaur Boundary

Centaur should consume these profiles as provider inventory. It should not
import DS4 CUDA, Spark topology, vLLM, SGLang, or OpenAI client code. The next
integration contract should be:

```text
Centaur model router -> selected provider_id/tier/lane
DS4 model-swarm provider -> batch execution + telemetry
Centaur scoring -> quality, cost, throughput, validation, escalation outcome
```

## References

- Qwen3-Coder-Next model card:
  <https://huggingface.co/Qwen/Qwen3-Coder-Next>
- Ling-V2 repository:
  <https://github.com/inclusionAI/Ling-V2>
- Ling-mini-2.0 model card:
  <https://huggingface.co/inclusionAI/Ling-mini-2.0>
