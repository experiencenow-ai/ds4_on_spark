# XHigh Live Validation

These are the first live checks required after the ds4_on_spark v2 substrate lands. They validate the real resident lanes, not the fake runner.

The machine-readable task list is:

```text
profiles/validation/xhigh_live_validation_tasks.json
```

## Static Allocation Under Test

```text
spark0, spark1, spark2, spark3, spark7
  resident Qwen lanes
  profiles: qwen3_6_27b_fp8_efficient_v1, qwen3_6_35b_a3b_fp8_fastest_v1

spark4 + spark5
  grouped DSV4 vLLM/MTP lane
  profile: dsv4_vllm_mtp_smartest_v1

spark6
  antirez/support lane
  profile: dsv4_antirez_smart_v1
```

There is no dynamic model ejection code in this plan. The small Qwen profile stays resident even when idle.

## Shared Request Files

Create request fixtures on each host or in a shared path visible to the command being run.

Qwen lane request file:

```jsonl
{"format":"ds4-inference-request-v1","request_id":"qwen-efficient-smoke","capability":"efficient","chat":true,"immediate":false,"job_class":"summary","max_output_tokens":64,"thinking_budget_tokens":0,"temperature":0,"input":{"messages":[{"role":"user","content":"Reply with exactly: qwen efficient ok"}]},"output_contract":{"format":"text"}}
{"format":"ds4-inference-request-v1","request_id":"qwen-fastest-smoke","capability":"fastest","chat":true,"immediate":false,"job_class":"triage","max_output_tokens":64,"thinking_budget_tokens":0,"temperature":0,"input":{"messages":[{"role":"user","content":"Reply with exactly: qwen fastest ok"}]},"output_contract":{"format":"text"}}
```

DSV4 vLLM/MTP request file:

```jsonl
{"format":"ds4-inference-request-v1","request_id":"dsv4-mtp-chat-smoke","capability":"smartest","chat":true,"immediate":false,"job_class":"tool_chat","max_output_tokens":128,"thinking_budget_tokens":256,"temperature":0,"input":{"messages":[{"role":"user","content":"In one sentence, say the DSV4 MTP lane is reachable."}]},"output_contract":{"format":"text"}}
```

Antirez request file:

```jsonl
{"format":"ds4-inference-request-v1","request_id":"antirez-smart-smoke","capability":"smart","chat":false,"immediate":true,"job_class":"atom_edit","max_output_tokens":128,"thinking_budget_tokens":0,"temperature":0,"input":{"prompt":"Return one short sentence proving the antirez completion lane is reachable."},"output_contract":{"format":"text"}}
```

## Required Checks

### 1. Qwen vLLM Resident Lanes

Run on each Qwen host: `spark0`, `spark1`, `spark2`, `spark3`, and `spark7`.

```bash
ssh spark0 'cd /path/to/ds4_on_spark/v2 && DS4_VLLM_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=src python3 -m ds4_infer.cli submit --profiles-dir profiles/models --requests /tmp/qwen_requests.jsonl --out /tmp/ds4-v2-live/spark0-qwen-vllm --runner vllm --runner-timeout-s 600 --run'
```

Repeat with the node name changed for each resident Qwen lane.

Acceptance:

- `completed_count=2`
- both result records have `status=completed`
- selected profiles include both Qwen profile IDs
- capture `/v1/models` and the response JSONL for the handoff

### 2. Spark4+Spark5 DSV4 vLLM/MTP

Run from a host that can reach the grouped lane endpoint.

```bash
cd /path/to/ds4_on_spark/v2
DS4_VLLM_MTP_BASE_URL=http://spark4:8000 PYTHONPATH=src python3 -m ds4_infer.cli submit \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests /tmp/dsv4_mtp_requests.jsonl \
  --out /tmp/ds4-v2-live/spark45-dsv4-vllm-mtp \
  --runner vllm \
  --runner-timeout-s 1200 \
  --run
```

Acceptance:

- request completes
- selected node is `spark4+spark5`
- transport base URL is the MTP endpoint
- token usage is captured when the endpoint returns it

### 3. Spark6 Antirez Runner

Run on spark6 so `127.0.0.1:8080` is the local antirez endpoint.

```bash
ssh spark6 'cd /path/to/ds4_on_spark/v2 && DS4_ANTIREZ_BASE_URL=http://127.0.0.1:8080 PYTHONPATH=src python3 -m ds4_infer.cli submit --profiles-dir profiles/models --requests /tmp/antirez_requests.jsonl --out /tmp/ds4-v2-live/spark6-antirez --runner antirez --runner-timeout-s 1200 --run'
```

Acceptance:

- request completes
- selected profile is `dsv4_antirez_smart_v1`
- output text is non-empty
- endpoint/version details are captured if available

### 4. Mac Studio Spark Chat

Run from Mac Studio against the resident DSV4 vLLM/MTP lane.

```bash
cd /path/to/ds4_on_spark/v2
DS4_VLLM_MTP_BASE_URL=http://spark4:8000 PYTHONPATH=src python3 -m ds4_chat.cli \
  --registry tools/registry.jsonl \
  --history /tmp/ds4-v2-live/mac-studio-chat-history.json \
  --timeout-s 1200 \
  --max-tokens 512 \
  --ask 'Answer with one sentence: what are the three static DS4 v2 inference lanes?'
```

Acceptance:

- command exits 0
- assistant response is non-empty
- history file is written
- no Spark action is claimed without a tool result

### 5. Rendered Web Tool

Only install Playwright on the web-tool host when rendered web access is needed.

```bash
cd /path/to/ds4_on_spark/v2
python3 -m pip install '.[web]'
python3 -m playwright install chromium
PYTHONPATH=src python3 -m ds4_tools.cli invoke \
  --registry tools/registry.jsonl \
  --tool-id tool:web.fetch \
  --arguments '{"url":"https://example.com","mode":"rendered","max_text_chars":1000}'
```

Acceptance:

- install succeeds when rendered access is needed
- `tool:web.fetch` returns `ok=true`
- returned mode is `rendered`
- text mode remains available without Playwright

## Report Back

The xhigh should attach:

- command lines
- node names
- `/v1/models` or equivalent endpoint status
- response JSONL/manifest paths
- failures with stderr tails
- any observed mismatch between `profiles/topology/static_sparks.json` and live residency
