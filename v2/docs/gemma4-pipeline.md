# Gemma4 pipeline profiles

Gemma4 is wired as an experimental all-Spark vLLM pipeline family. These
profiles are deliberately profile-pin-only and `production_eligible=false`, so
they do not change normal `smart`, `smartest`, or reboot startup behavior.

## Profiles and aliases

| Alias | Profile | Service | Port | Layers | Partition |
| --- | --- | --- | --- | --- | --- |
| `gemma-e2b` | `gemma4_e2b_it_pp8_peer_v1` | `gemma4_e2b_pp8` | 8112 | 35 | `5,5,5,4,4,4,4,4` |
| `gemma-e4b` | `gemma4_e4b_it_pp8_peer_v1` | `gemma4_e4b_pp8` | 8114 | 42 | `6,6,5,5,5,5,5,5` |
| `gemma`, `gemma12`, `gemma4-12b` | `gemma4_12b_it_pp8_peer_v1` | `gemma4_12b_pp8` | 8116 | 48 | `6,6,6,6,6,6,6,6` |
| `gemma26`, `gemma-a4b` | `gemma4_26b_a4b_it_pp8_peer_v1` | `gemma4_26b_a4b_pp8` | 8118 | 30 | `4,4,4,4,4,4,3,3` |
| `gemma31` | `gemma4_31b_it_pp8_peer_v1` | `gemma4_31b_pp8` | 8120 | 60 | `8,8,8,8,7,7,7,7` |

All five services use `spark0` as the OpenAI ingress and `spark0` through
`spark7` as vLLM pipeline ranks. They share the `spark-fleet-0` compute domain
with Qwen27 and DSV4. Gemma launch configs cap vLLM
`--gpu-memory-utilization` at `0.25`, with the dense 31B profile capped at
`0.20`, so experimental Gemma runs can be co-resident with the other resident
pipelines instead of forcing a full-cluster stop.

## Runtime assumptions

Each node must have the model under the node-local Hugging Face cache:

```text
/home/{node}/models/hf/google/gemma-4-E2B-it
/home/{node}/models/hf/google/gemma-4-E4B-it
/home/{node}/models/hf/google/gemma-4-12B-it
/home/{node}/models/hf/google/gemma-4-26B-A4B-it
/home/{node}/models/hf/google/gemma-4-31B-it
```

The launch recipes require the source-built `experiencenow-ai/vllm` runtime,
not a PyPI vLLM fallback. Gemma4 Unified support is carried in
`experiencenow-ai/vllm#279` plus the follow-up helper fix in
`experiencenow-ai/vllm#280`, with merged source commit
`55192abf198725fed935a94acdec27ff1f6a0730`.

The Python runtime also needs Hugging Face `transformers` source with
`transformers.models.gemma4_unified`. The current required source point is
`huggingface/transformers@ece3b9a353b20b69485293927bcc729f8b34844d` or newer.
On spark3, the existing standard venv reported `transformers 5.9.0` but only
contained `gemma4` and `gemma4_assistant`; that runtime registered the vLLM
arch name but failed a direct `gemma4_unified` import. Treat that as a hard
runtime mismatch, not a Gemma model problem.

The initial recipes use plain vLLM pipeline serving with no LMCache, HMA, or
CPU offload connector; the goal is to prove pipeline execution and DS4 routing
first. The recipes still use the DS4 all-Spark pipeline transport convention
from the current DSV4 PP8 deployment: `DS4_PP_TRANSPORT=tcp-staged` and
`VLLM_DS4_PP_EDGE_RAIL=enp`. For Gemma, that convention is wired to the vLLM
TCP tensor-dict transport explicitly: the broad PP device communicator is
disabled, `VLLM_DS4_PP_TCP_TENSOR_DICT=1`, and the TCP bind/advertise host is
the node's 200G fabric IP. Gemma also pins Gloo and vLLM host identity to the
200G fabric because the first live PP8 bring-up otherwise advertised loopback
addresses during process-group formation.

Gemma PP8 disables the hybrid KV cache manager explicitly. Some pipeline ranks
can end up with only one attention group after layer partitioning, and vLLM's
`HybridKVCacheCoordinator` asserts when a rank has fewer than two groups.

## Lifecycle runner

Use the shared pipeline lifecycle runner for Gemma bring-up, the same as Qwen
and DSV4. Do not keep Gemma-specific SSH launch notes outside the repo script.
Always target the specific Gemma service being tested; do not use `--service
all` for Gemma experiments because other developers may have co-resident Qwen or
DSV4 work running. The lifecycle runner rejects mutating `--service all
--execute` calls unless `--allow-all-services` is passed for planned fleet-wide
maintenance. Scoped stops kill the matched service process tree so failed vLLM
worker children do not stay orphaned on the GPU.

Dry-run the standard sequence first:

```bash
cd ~/src/ds4_on_spark/v2
python3 scripts/ds4_pipeline_lifecycle.py --service gemma4_12b_pp8 relaunch
```

Then execute it:

```bash
python3 scripts/ds4_pipeline_lifecycle.py --service gemma4_12b_pp8 relaunch --execute
```

For direct plan inspection from a Spark checkout:

```bash
cd ~/src/ds4_on_spark/v2
PYTHONPATH=src python3 -m ds4_kvcache.cli plan \
  --deployment profiles/kv_cache/gemma4_12b_it_pp8_plain.json
```

Use the matching `profiles/kv_cache/gemma4_*_plain.json` file for the other
family members. Runnable script generation for resident topology pipelines is
deliberately gated behind `scripts/ds4_pipeline_lifecycle.py`.

## Request surface

The OpenAI API model resolver and CLI aliases understand the short names above.
For example:

```json
{
  "model": "gemma12",
  "messages": [{"role": "user", "content": "ping"}],
  "max_tokens": 64,
  "temperature": 0
}
```

That resolves to `gemma4_12b_it_pp8_peer_v1` and sends the live vLLM request to
served model name `gemma-4-12b-it-pp8`.

Thinking is disabled by default through `chat_template_kwargs`:

```json
{"enable_thinking": false}
```

Requests with a positive `thinking_budget_tokens` flip it on for that request.

## Promotion rule

Do not add Gemma to reboot startup or normal `smart` routing until a live PP8
run passes:

```text
1. /v1/models exposes the served Gemma name on the selected port.
2. Single chat/completion requests succeed through DS4 API model alias.
3. Batched requests complete through the queue without starving Qwen/DSV4.
4. DS4-eval runs through the DS4 API path and records accuracy and tok/s.
5. trim_memory works through the pipeline ingress after an abort/reset.
```
